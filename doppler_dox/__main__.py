import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Local aircraft Doppler workbench')
    sub = parser.add_subparsers(dest='command')
    serve = sub.add_parser('serve', help='Start the local browser workbench')
    serve.add_argument('--port', type=int, default=8765)
    serve.add_argument('--case', help='Preload a local case with its real media, tracks and measured events')
    demo = sub.add_parser('demo', help='Run a reproducible synthetic end-to-end search')
    demo.add_argument('--output', default='outputs/demo.json')
    demo.add_argument('--score-mode', choices=['brightness', 'trace'], default='trace')
    demo.add_argument('--seed', type=int, default=7)
    fetch = sub.add_parser('fetch-history', help='Download official ADS-B daily archives (several GB; resumable)')
    fetch.add_argument('day')
    fetch.add_argument('--output', required=True)
    ingest = sub.add_parser('ingest', help='Stream readsb split tar archives into bounded track CSV')
    ingest.add_argument('parts', nargs='+')
    ingest.add_argument('--output', required=True)
    ingest.add_argument('--bbox', nargs=4, type=float, required=True, metavar=('WEST','SOUTH','EAST','NORTH'))
    ingest.add_argument('--start', required=True)
    ingest.add_argument('--end', required=True)
    ingest.add_argument('--types')
    ingest.add_argument('--altitude', choices=['geometric','barometric'], default='geometric')
    ingest.add_argument('--altitude-offset', type=float, default=0, help='Explicit datum correction in metres')
    export = sub.add_parser('export-demo', help='Write demo WAV, tracks CSV and runnable case JSON')
    export.add_argument('--output', default='outputs/demo')
    run = sub.add_parser('run', help='Search a saved JSON case and local media/tracks')
    run.add_argument('case')
    args = parser.parse_args()
    if args.command in (None, 'serve'):
        from .server import make_server
        server = make_server(port=getattr(args, 'port', 8765), case_path=getattr(args, 'case', None))
        print(f'Doppler Dox is ready at http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return
    if args.command == 'fetch-history':
        from .fetch import fetch_history
        print('\n'.join(fetch_history(args.day, args.output)))
        return
    if args.command == 'ingest':
        from .ingest import convert_traces
        print(convert_traces(args.parts, args.output, args.bbox, args.start, args.end, args.types, args.altitude, args.altitude_offset))
        return
    if args.command == 'export-demo':
        from .demo import make_demo
        from .audio import RATE
        from scipy.io import wavfile
        d = make_demo()
        folder = Path(args.output)
        folder.mkdir(parents=True, exist_ok=True)
        wavfile.write(folder/'synthetic-demo.wav', RATE, d['samples'])
        (folder/'demo-tracks.csv').write_text(d['tracks_csv'])
        (folder/'case.json').write_text(json.dumps(dict(audio='synthetic-demo.wav', tracks='demo-tracks.csv',
            events=d['events'], config=d['config'], output='result.json'), indent=2))
        print(f'Demo fixtures exported to {folder}')
        return
    from .search import run_search
    if args.command == 'demo':
        from .demo import make_demo
        d = make_demo(args.seed)
        config = dict(d['config'], score_mode=args.score_mode)
        result = run_search(d['spec'], d['tracks'], d['events'], config)
        result['truth'] = d['truth']
        result['events'] = d['events']
        output = Path(args.output)
    else:
        from .audio import Spectrogram, decode
        from .physics import fit_flyby
        from .tracks import load_tracks, Elevations
        case_path = Path(args.case).resolve()
        case = json.loads(case_path.read_text())
        base = case_path.parent
        spec = Spectrogram(decode((base/case['audio']).read_bytes()))
        tracks, _ = load_tracks((base/case['tracks']).read_text())
        config = case['config']
        events = [fit_flyby(e['points'], config.get('sound_speed', 343)) for e in case['events']]
        elevations = Elevations((base/case['elevations']).read_text()) if case.get('elevations') else None
        result = run_search(spec, tracks, events, config, elevations)
        output = base/case.get('output', 'result.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False))
    print(f'{len(result["candidates"])} flight assignment(s); report: {output}')
    if result['candidates']:
        r = result['candidates'][0]
        print(f'Best: {r["latitude"]:.6f}, {r["longitude"]:.6f}; score={r["score"]:.3f}')


if __name__ == '__main__':
    main()
