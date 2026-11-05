"""Deterministic fictional two-pass challenge; independent retarded-phase renderer."""
import csv
import io
import numpy as np
from .audio import RATE, Spectrogram
from .physics import ecef, fit_flyby
from .tracks import load_tracks

TRUTH = (40.01, -74.99)
EPOCH = 1793491200.0


def make_demo(seed=7):
    rng = np.random.default_rng(seed)
    lat, lon = TRUTH
    observer = ecef(lat, lon, 0)
    duration = 240
    audio_t = np.arange(duration*RATE)/RATE
    samples = rng.normal(0, .025, len(audio_t)) + .008*np.sin(2*np.pi*60*audio_t)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['track_id', 'time', 'latitude', 'longitude', 'altitude_m', 'engine'])
    events = []
    for name, center, speed, offset, height, f0, axis in (
            ('DEMO-PROP-01', 55, 80, 400, 1000, 130, 'east'),
            ('DEMO-PROP-02', 175, 95, -300, 1400, 185, 'north')):
        def position(t):
            along = speed*(np.asarray(t)-center)
            x, y = (along, np.full_like(along, offset)) if axis == 'east' else (np.full_like(along, offset), along)
            return ecef(lat+y/111320, lon+x/(111320*np.cos(np.radians(lat))), height)
        def emission(receive):
            # Fixed-point retarded phase solve, independent of the fitted/scoring models.
            te = np.asarray(receive).copy()
            for _ in range(24):
                te = receive-np.linalg.norm(position(te)-observer, axis=-1)/343
            return te
        te = emission(audio_t)
        amplitude = .14*np.exp(-.5*((te-center)/22)**2)
        for harmonic, weight in ((1, 1), (2, .5), (3, .3)):
            samples += amplitude*weight*np.sin(2*np.pi*f0*harmonic*te + .3*harmonic)
        for t in np.arange(-30, duration+31, 2.):
            along = speed*(t-center)
            x, y = (along, offset) if axis == 'east' else (offset, along)
            writer.writerow([name, EPOCH+t, lat+y/111320, lon+x/(111320*np.cos(np.radians(lat))), height, 'T'])
        cpa = center+np.sqrt(offset**2+height**2)/343
        times = np.linspace(cpa-27, cpa+27, 109)
        frequency = f0*(emission(times+.005)-emission(times-.005))/.01
        events.append(fit_flyby(np.column_stack((times, frequency))))
    samples = samples.astype(np.float32)
    tracks_csv = output.getvalue()
    tracks, summary = load_tracks(tracks_csv)
    return dict(spec=Spectrogram(samples), samples=samples, tracks=tracks, tracks_csv=tracks_csv,
                track_summary=summary, events=events, truth=dict(latitude=lat, longitude=lon),
                config=dict(south=lat-.009, north=lat+.009, west=lon-.012, east=lon+.012,
                            spacing_m=200, elevation_m=0, score_mode='brightness', silence=False,
                            sound_speed=343, clock_sweep_s=3, offset_tolerance_s=8))
