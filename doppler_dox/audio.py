"""Bounded local decoding, whitening, ridge extraction and brightness scoring."""
import base64
import math
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from scipy import signal
from scipy.ndimage import map_coordinates, median_filter

RATE = 2000
MAX_DURATION = 3600


def decode(data):
    if not data:
        raise ValueError('Empty media file.')
    with tempfile.TemporaryDirectory(prefix='doppler-') as folder:
        source = Path(folder)/'input.media'
        target = Path(folder)/'audio.f32'
        source.write_bytes(data)
        try:
            proc = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-protocol_whitelist', 'file,pipe',
                                   '-i', str(source), '-vn', '-ac', '1', '-ar', str(RATE),
                                   '-t', str(MAX_DURATION+1), '-f', 'f32le', str(target)],
                                  capture_output=True, timeout=90)
        except FileNotFoundError as exc:
            raise ValueError('Install ffmpeg to import audio/video.') from exc
        if proc.returncode or not target.exists():
            raise ValueError('Cannot decode media. Use a valid WAV, MP3, FLAC, MP4 or WebM file.')
        samples = np.fromfile(target, dtype='<f4')
    if len(samples) > (MAX_DURATION+.5)*RATE:
        raise ValueError('Recording exceeds the 60-minute limit. Trim it first.')
    samples = samples[:MAX_DURATION*RATE]  # tolerate sub-second codec padding
    if len(samples) < 8*RATE:
        raise ValueError('Use a recording at least 8 seconds long.')
    if not np.isfinite(samples).all():
        raise ValueError('Media contains non-finite samples.')
    return samples


class Spectrogram:
    def __init__(self, samples, rate=RATE):
        self.duration = len(samples)/rate
        # 2-second Hann windows: 0.5 Hz bins; adapt time hop for long recordings.
        nperseg = 2*rate
        hop = max(rate//4, math.ceil(len(samples)/14000))
        f, t, power = signal.spectrogram(samples, fs=rate, window='hann', nperseg=nperseg,
                                         noverlap=max(0, nperseg-hop), mode='psd')
        keep = (f >= 20) & (f <= 800)
        self.f, self.t = f[keep], t
        db = 10*np.log10(np.maximum(power[keep], 1e-20))
        # Remove persistent hum and normalize each time slice's broadband level.
        db -= np.median(db, axis=1, keepdims=True)
        # A coarse 2-second lattice makes 20-second running-median whitening
        # practical even for hour-long media, removing intermittent mains hum.
        stride = max(1, round(2/(t[1]-t[0])))
        coarse = db[:, ::stride]
        baseline = median_filter(coarse, size=(1, 11), mode='nearest')
        index = np.arange(db.shape[1])/stride
        lower = np.minimum(index.astype(int), coarse.shape[1]-1)
        upper = np.minimum(lower+1, coarse.shape[1]-1)
        weight = index-lower
        db -= baseline[:, lower]*(1-weight)+baseline[:, upper]*weight
        db -= np.median(db, axis=0, keepdims=True)
        self.db = np.clip(db, -20, 50).astype(np.float32)

    def view(self, start=0, end=None, low=40, high=600):
        end = self.duration if end is None else end
        if not 0 <= start < end <= self.duration+.01 or not 20 <= low < high <= 800:
            raise ValueError('Invalid time/frequency bounds (20–800 Hz).')
        ti = np.flatnonzero((self.t >= start) & (self.t <= end))
        fi = np.flatnonzero((self.f >= low) & (self.f <= high))
        if len(ti) < 2 or len(fi) < 2:
            raise ValueError('Select a wider time/frequency range.')
        ti = ti[::max(1, math.ceil(len(ti)/1400))]
        fi = fi[::max(1, math.ceil(len(fi)/600))]
        pixels = np.clip((self.db[np.ix_(fi, ti)] + 5)/35*255, 0, 255).astype(np.uint8)
        return dict(width=len(ti), height=len(fi), pixels=base64.b64encode(pixels.tobytes()).decode(),
                    start=float(self.t[ti[0]]), end=float(self.t[ti[-1]]),
                    low=float(self.f[fi[0]]), high=float(self.f[fi[-1]]), duration=self.duration)

    def trace(self, start, end, low, high, anchors=None):
        """Viterbi ridge path with bounded bin-to-bin slope and sub-bin peak interpolation."""
        self.view(start, end, low, high)  # validate bounds
        ti = np.flatnonzero((self.t >= start) & (self.t <= end))
        fi = np.flatnonzero((self.f >= low) & (self.f <= high))
        if len(ti)*len(fi) > 3_000_000:
            raise ValueError('Narrow the trace window (time × frequency too large).')
        values = self.db[np.ix_(fi, ti)].copy()
        if anchors:
            anchors = np.asarray(anchors, dtype=float)
            if anchors.ndim != 2 or anchors.shape[1] != 2 or len(anchors) < 2 or len(anchors) > 1000 or not np.isfinite(anchors).all():
                raise ValueError('Provide 2–1000 finite time/frequency anchors.')
            anchors = anchors[np.argsort(anchors[:, 0])]
            center = np.interp(self.t[ti], anchors[:, 0], anchors[:, 1])
            values[np.abs(self.f[fi, None]-center[None, :]) > 7] = -1e9
        previous = values[:, 0].copy()
        parents = np.zeros(values.shape, dtype=np.int16)
        max_jump = max(2, int(3*np.median(np.diff(self.t))/np.diff(self.f)[0]))
        offsets = np.arange(-max_jump, max_jump+1)
        for j in range(1, len(ti)):
            index = np.arange(len(fi))[:, None]+offsets
            valid = (index >= 0) & (index < len(fi))
            options = np.where(valid, previous[np.clip(index, 0, len(fi)-1)] - .8*np.abs(offsets), -1e12)
            k = np.argmax(options, axis=1)
            parents[:, j] = np.clip(index[np.arange(len(fi)), k], 0, len(fi)-1)
            previous = values[:, j] + options[np.arange(len(fi)), k]
        path = np.empty(len(ti), dtype=int)
        path[-1] = np.argmax(previous)
        for j in range(len(ti)-1, 0, -1):
            path[j-1] = parents[path[j], j]
        bins = fi[path]
        y0 = self.db[np.maximum(bins-1, 0), ti]
        y1 = self.db[bins, ti]
        y2 = self.db[np.minimum(bins+1, len(self.f)-1), ti]
        denom = y0-2*y1+y2
        delta = np.divide(.5*(y0-y2), denom, out=np.zeros_like(y1), where=np.abs(denom)>1e-5)
        freqs = self.f[bins] + np.clip(delta, -.5, .5)*(self.f[1]-self.f[0])
        step = max(1, len(ti)//400)
        return np.column_stack((self.t[ti], freqs))[::step].tolist()

    def brightness_sweep(self, times, ratios, fundamentals, harmonics=3):
        """Vectorized brightness scores for several fundamental frequencies."""
        times, ratios, fundamentals = map(np.asarray, (times, ratios, fundamentals))
        if times.min() < self.t[0] or times.max() > self.t[-1]:
            return np.full(len(fundamentals), -100.)
        scores = np.zeros(len(fundamentals))
        counts = np.zeros(len(fundamentals))
        time_index = (times-self.t[0])/(self.t[1]-self.t[0])
        for harmonic in range(1, harmonics+1):
            ff = fundamentals[:, None]*ratios[None, :]*harmonic
            valid = (ff.min(axis=1) >= self.f[0]) & (ff.max(axis=1) <= self.f[-1])
            coords = np.stack(((ff-self.f[0])/(self.f[1]-self.f[0]), np.broadcast_to(time_index, ff.shape)))
            values = map_coordinates(self.db, coords, order=1, mode='constant', cval=-100).mean(axis=1)
            scores += np.where(valid, values, 0)
            counts += valid
        return np.divide(scores, counts, out=np.full(len(scores), -100.), where=counts>0)

    def brightness(self, times, frequencies, harmonics=3):
        return float(self.brightness_sweep(times, frequencies, [1.], harmonics)[0])
