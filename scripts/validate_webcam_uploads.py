#!/usr/bin/env python3
"""Check independent webcam clips through the unchanged simple upload HTTP API."""
import argparse,json,sys,threading,time
from pathlib import Path
from urllib.request import Request,urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from doppler_dox.server import make_server

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--with-history',action='store_true',help='Also submit Moosehead context and run the real historical-data matcher')
args=parser.parse_args()
server=make_server(port=0)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
base=f'http://127.0.0.1:{server.server_port}'

def call(path,body=None):
    data=body if isinstance(body,bytes) else json.dumps(body).encode() if body is not None else None
    request=Request(base+path,data=data,headers={'X-Workbench-Token':server.app.token})
    with urlopen(request,timeout=60) as response:return json.load(response)

rows=[]
try:
    for name,media,expected in [('lorain','outputs/webcam-validation/lorain/clip-00000.webm','inconclusive'),
                                ('moosehead','outputs/webcam-validation/moosehead/clip-00000.webm','needs_context'),
                                ('lake-hood','data/webcam-validation/lake-hood-live.m4a','inconclusive')]:
        call('/api/simple/upload',Path(media).read_bytes())
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            state=call('/api/simple/state')
            if state['status']!='analyzing':break
            time.sleep(.2)
        assert state['status']==expected,(name,state['status'],state.get('message'))
        assert 'location' not in state,(name,'unexpected map pin before supported matching')
        if args.with_history and name=='moosehead':
            case=next(c for c in json.loads(Path('cases/webcam-benchmark.json').read_text())['cameras'] if c['id']=='moosehead')
            from datetime import datetime,timezone
            call('/api/simple/continue',dict(recorded_at=datetime.fromtimestamp(case['recording_start_epoch'],timezone.utc).isoformat(),latitude=case['starting_area'][0],longitude=case['starting_area'][1]))
            deadline=time.monotonic()+600
            while time.monotonic()<deadline:
                state=call('/api/simple/state')
                if state['status']!='analyzing':break
                time.sleep(.5)
            assert state['status'] in ('inconclusive','match','unavailable'),state['status']
        state.pop('token',None)
        rows.append(dict(camera=name,response=state))
        print(name,state['status'],flush=True)
        call('/api/simple/reset',{})
    Path('outputs/webcam-validation/upload-api.json').write_text(json.dumps(rows,indent=2))
finally:
    server.shutdown();server.server_close();thread.join()
