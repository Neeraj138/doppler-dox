import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Local aircraft Doppler workbench')
    sub = parser.add_subparsers(dest='command')
    serve = sub.add_parser('serve', help='Start the local browser workbench')
    serve.add_argument('--port', type=int, default=8765)
    demo = sub.add_parser('demo', help='Run a reproducible synthetic end-to-end search')
    demo.add_argument('--output', default='outputs/demo.json')
    demo.add_argument('--score-mode', choices=['brightness', 'trace'], default='trace')
    demo.add_argument('--seed', type=int, default=7)
    run = sub.add_parser('run', help='Search a saved JSON case and local media/tracks')
    run.add_argument('case')
    args = parser.parse_args()
    if args.command in (None, 'serve'):
        from .server import make_server
        server = make_server(port=getattr(args, 'port', 8765))
        print(f'Doppler Dox is ready at http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
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
