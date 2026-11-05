#!/usr/bin/env python3
"""Exercise real local media/track files through the same HTTP API as the UI.

Run from the repository root. No synthetic audio or tracks are created.
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from doppler_dox.server import make_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    case = json.loads(args.case.read_text())
    base = args.case.resolve().parent
    server = make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    token = ''
    checks = []

    def request(path, body=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
        req = Request(url+path, data=data, headers={'X-Workbench-Token': token})
        with urlopen(req, timeout=120) as response:
            return json.load(response)

    try:
        token = request('/api/state')['token']
        for path in ('/', '/app.js', '/style.css'):
            with urlopen(url+path) as response:
                assert response.status == 200 and len(response.read()) > 100
        checks.append('Frontend HTML/CSS/JS assets served successfully (visual browser test not available).')
        media = base/case['audio']
        tracks = base/case['tracks']
        print(f'Importing real media: {media.name}', flush=True)
        duration = request('/api/audio', media.read_bytes())['duration']
        assert duration >= 8
        checks.append(f'Real media decoded: {duration:.3f} seconds.')
        imported = request('/api/tracks', tracks.read_bytes())
        checks.append(f'Real flight tracks imported: {imported["tracks"]} segments, {imported["positions"]} positions.')
        points = case['events'][0]['points']
        times, freqs = zip(*points)
        view = request(f'/api/view?start={min(times)}&end={max(times)}&low={max(20,min(freqs)-5)}&high={min(800,max(freqs)+5)}')
        assert view['width'] > 8 and len(view['pixels']) > 20
        checks.append('Real-media spectrogram endpoint returned a populated image.')
        fitted = []
        for i, event in enumerate(case['events']):
            fit = request('/api/fit', {'points': event['points'], 'sound_speed':case['config'].get('sound_speed',343)})
            assert fit['searchable'], f'Event {i+1} is inconclusive.'
            fitted.append(fit)
            checks.append(f'Event {i+1}: f0={fit["f0"]:.3f} Hz, speed={fit["speed_mps"]:.2f} m/s, slant={fit["distance_m"]:.1f} m, RMS={fit["rms_hz"]:.3f} Hz.')
        request('/api/events', {'events':fitted})
        if case.get('background_window'):
            traced = request('/api/trace', case['background_window'])
            fit = request('/api/fit',traced)
            assert not fit['searchable'], 'Background control incorrectly accepted a usable aircraft curve.'
            checks.append('Background control from the same real recording was marked inconclusive.')
        print('Running actual-trajectory search through HTTP…', flush=True)
        request('/api/search',case['config'])
        deadline = time.monotonic()+300
        last_phase = None
        while time.monotonic() < deadline:
            state = request('/api/state')
            job = state['job']
            if job['phase'] != last_phase:
                print(f'{job["phase"]}: {job["progress"]:.0%}', flush=True)
                last_phase = job['phase']
            if job['status'] == 'error':
                raise AssertionError(job['phase'])
            if job['status'] == 'complete':
                break
            time.sleep(.5)
        else:
            raise TimeoutError('Search exceeded the five-minute validation budget.')
        exported = request('/api/export')
        assert exported['candidates'], 'No consistent location candidate for the real test.'
        assert exported['geojson']['type'] == 'FeatureCollection'
        assert len(exported['geojson']['features']) == len(exported['candidates'])
        checks.append(f'Asynchronous search completed; exported {len(exported["candidates"])} ranked flight assignments and valid GeoJSON.')
        best = exported['candidates'][0]
        # Deliberately corrupt the observed pair timing, keeping the actual media and tracks.
        if len(fitted) == 2:
            corrupt = dict(fitted[1])
            corrupt['points'] = [[t+300,f] for t,f in corrupt['points']]
            request('/api/events',{'events':[fitted[0],corrupt]})
            request('/api/search',dict(case['config'],offset_tolerance_s=.5))
            deadline = time.monotonic()+180
            while time.monotonic() < deadline:
                state=request('/api/state')
                if state['job']['status'] in ('complete','error'):
                    break
                time.sleep(.5)
            assert state['job']['status']=='complete' and not state['result']['candidates'], 'Timing negative control did not reject the mismatched passes.'
            checks.append('Real-track negative control with deliberately inconsistent event spacing produced no candidates.')
        exported['validation'] = dict(checks=checks, media_file=media.name, tracks_file=tracks.name,
                                      kind='real-media / real historical ADS-B, bounded known-site consistency check',
                                      source=case.get('source',{}))
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(exported,indent=2,allow_nan=False))
        print('\n'.join(checks), flush=True)
        print(f'Best real candidate: {best["latitude"]:.6f}, {best["longitude"]:.6f}; score={best["score"]:.3f}; tracks={best["tracks"]}', flush=True)
        print(f'Export: {args.output}',flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
