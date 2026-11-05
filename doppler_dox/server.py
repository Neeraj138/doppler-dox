"""Loopback-only local workbench. Sessions are ephemeral and bounded."""
import hmac
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import numpy as np
from .audio import Spectrogram, decode
from .physics import fit_flyby
from .tracks import load_tracks, Elevations
from .search import run_search

STATIC = Path(__file__).parent/'static'
MAX_BYTES = 128*1024*1024


class Application:
    def __init__(self):
        self.lock = threading.Lock()
        self.spec = None
        self.events = []
        self.tracks = []
        self.elevations = None
        self.result = None
        self.job = dict(status='idle', phase='', progress=0)
        self.token = secrets.token_urlsafe(24)
        self.demo_cache = None

    def check_mutable(self):
        if self.job['status'] == 'running':
            raise ValueError('A search is running. Wait for it to finish before changing inputs.')

    def search(self, config):
        with self.lock:
            self.check_mutable()
            if self.spec is None or not self.tracks or not self.events:
                raise ValueError('Load audio, flight tracks and at least one fitted event first.')
            # Snapshot references; input mutations remain locked until the worker finishes.
            spec, tracks, events, elevations = self.spec, self.tracks, list(self.events), self.elevations
            self.job = dict(status='running', phase='Starting search', progress=0)
            self.result = None
        def update(phase, fraction):
            with self.lock:
                self.job.update(phase=phase, progress=fraction)
        def worker():
            try:
                result = run_search(spec, tracks, events, config, elevations, update)
                with self.lock:
                    self.result = result
                    self.job.update(status='complete', phase='Complete', progress=1)
            except Exception as exc:
                with self.lock:
                    self.job.update(status='error', phase=str(exc), progress=0)
        threading.Thread(target=worker, daemon=True).start()


def make_server(host='127.0.0.1', port=8765):
    if host not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('The workbench binds to loopback only.')
    app = Application()
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, format, *args):
            pass

        def reply(self, status, data, content_type='application/json'):
            if content_type == 'application/json':
                data = json.dumps(data, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            return self.headers.get('Host', '') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {'error': 'Invalid Host header.'})
            path = urlparse(self.path).path
            try:
                if path == '/api/state':
                    with app.lock:
                        return self.reply(200, dict(token=app.token, events=app.events, tracks=len(app.tracks),
                                                   has_audio=app.spec is not None, job=app.job, result=app.result))
                if path == '/api/view':
                    if app.spec is None:
                        raise ValueError('Load audio first.')
                    args = {k: float(v[0]) for k, v in parse_qs(urlparse(self.path).query).items() if k in ('start','end','low','high')}
                    return self.reply(200, app.spec.view(**args))
                if path == '/api/export':
                    if app.result is None:
                        raise ValueError('Run a search first.')
                    result = dict(app.result, events=app.events)
                    result['geojson'] = dict(type='FeatureCollection', features=[dict(type='Feature',
                        geometry=dict(type='Point', coordinates=[r['longitude'], r['latitude']]),
                        properties={k:v for k,v in r.items() if k not in ('curves', 'latitude', 'longitude')})
                        for r in app.result['candidates']])
                    return self.reply(200, result)
                if path == '/api/track-map':
                    return self.reply(200, {'tracks': [dict(id=t.id, points=t.geographic[::max(1, len(t.geographic)//500)]) for t in app.tracks]})
                if path == '/api/demo-tracks':
                    if app.demo_cache is None:
                        raise ValueError('Load the demo first.')
                    return self.reply(200, app.demo_cache['tracks_csv'].encode(), 'text/csv')
                names = {'/':'index.html', '/app.js':'app.js', '/style.css':'style.css'}
                if path not in names:
                    return self.reply(404, {'error':'Not found.'})
                name = names[path]
                mime = {'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8'}[name.split('.')[-1]]
                return self.reply(200, (STATIC/name).read_bytes(), mime)
            except (ValueError, TypeError) as exc:
                self.reply(400, {'error':str(exc)})

        def do_POST(self):
            if not self.valid_host() or not hmac.compare_digest(self.headers.get('X-Workbench-Token',''), app.token):
                self.close_connection = True
                return self.reply(403, {'error':'Invalid local session token. Refresh the page.'})
            origin = self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
                self.close_connection = True
                return self.reply(403, {'error':'Cross-origin requests are not allowed.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > MAX_BYTES:
                    self.close_connection = True
                    return self.reply(413, {'error':'Upload must be 1 byte to 128 MiB.'})
                self.connection.settimeout(90)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError('Incomplete request.')
                path = urlparse(self.path).path
                if path == '/api/search':
                    app.search(json.loads(raw))
                    return self.reply(202, {'status':'running'})
                with app.lock:
                    app.check_mutable()
                    if path == '/api/demo':
                        from .demo import make_demo
                        if app.demo_cache is None:
                            app.demo_cache = make_demo()
                        d = app.demo_cache
                        app.spec, app.tracks = d['spec'], d['tracks']
                        app.events = list(d['events'])
                        app.elevations, app.result = None, None
                        return self.reply(200, dict(events=app.events, config=d['config'], truth=d['truth'],
                                                    tracks=d['track_summary'], duration=app.spec.duration))
                    if path == '/api/audio':
                        app.spec = Spectrogram(decode(raw))
                        app.events, app.result = [], None
                        return self.reply(200, dict(duration=app.spec.duration))
                    if path == '/api/tracks':
                        app.tracks, summary = load_tracks(raw.decode('utf-8-sig'))
                        app.result = None
                        return self.reply(200, summary)
                    if path == '/api/elevations':
                        app.elevations = Elevations(raw.decode('utf-8-sig'))
                        app.result = None
                        return self.reply(200, {'status':'Elevation samples loaded.'})
                    data = json.loads(raw)
                    if path == '/api/trace':
                        if app.spec is None:
                            raise ValueError('Load audio first.')
                        return self.reply(200, {'points': app.spec.trace(**data)})
                    if path == '/api/fit':
                        return self.reply(200, fit_flyby(data['points'], float(data.get('sound_speed',343))))
                    if path == '/api/events':
                        if not isinstance(data.get('events'), list) or len(data['events']) > 2:
                            raise ValueError('Provide up to two events.')
                        # Refit supplied points; never trust client-supplied physical parameters.
                        app.events = [fit_flyby(e['points'], float(data.get('sound_speed',343))) for e in data['events']]
                        app.result = None
                        return self.reply(200, {'events':app.events})
                    if path == '/api/reset-elevations':
                        app.elevations = None
                        app.result = None
                        return self.reply(200, {'status':'Using flat elevation.'})
                    return self.reply(404, {'error':'Not found.'})
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                self.reply(400, {'error':str(exc)})
            except Exception:
                self.reply(500, {'error':'Unexpected processing failure. Check media/track format and retry.'})
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.app = app
    return server
