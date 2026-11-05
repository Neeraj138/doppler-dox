#!/usr/bin/env python3
"""Verify the upload-first flow against the original public recording."""
import json
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request,urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from doppler_dox.server import make_server


def validate(case_path,output):
    case_path=Path(case_path).resolve()
    case=json.loads(case_path.read_text())
    server=make_server(port=0,case_path=case_path)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    def request(path,body=None,token=''):
        data=body if isinstance(body,bytes) else json.dumps(body).encode() if body is not None else None
        with urlopen(Request(base+path,data=data,headers={'X-Workbench-Token':token}),timeout=120) as response:
            return json.load(response)
    try:
        for path in ('/','/app.js','/style.css','/lab','/lab.js','/lab.css','/vendor/leaflet.js','/vendor/leaflet.css'):
            with urlopen(base+path) as response:
                assert response.status==200 and len(response.read())>100
        state=request('/api/simple/state')
        assert state['has_example']
        media=(case_path.parent/case['audio']).read_bytes()
        print('Uploading original real recording; no traces, events or location settings supplied.',flush=True)
        request('/api/simple/upload',media,state['token'])
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            state=request('/api/simple/state')
            if state['status']!='analyzing':
                break
            time.sleep(.25)
        assert state['status']=='match',state
        assert state['flyovers']==2,state
        assert state['location']['latitude'] and state['location']['longitude']
        with urlopen(base+'/api/state') as response:
            work=json.load(response)
        assert [e['cpa_s'] for e in work['events']] != [e.get('cpa_s') for e in case['events']], 'Manual case traces must not drive the upload flow.'
        tracks=work['result']['candidates'][0]['tracks']
        assert tracks==['a1dfeb:3','ace391:3'],tracks
        state.pop('token',None)
        result=dict(public=state,matched_tracks=tracks,detected_events=[{k:e[k] for k in ('cpa_s','f0','speed_mps','distance_m','rms_hz')} for e in work['events']])
        Path(output).write_text(json.dumps(result,indent=2))
        print('PASS: upload -> automatic aircraft detection -> actual flight matching -> map coordinates.',flush=True)
        print(json.dumps(state,indent=2),flush=True)
        return result
    finally:
        server.shutdown();server.server_close();thread.join()

if __name__=='__main__':
    validate(sys.argv[1],sys.argv[2])
