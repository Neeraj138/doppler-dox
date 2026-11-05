#!/usr/bin/env python3
"""Reproducible tests against independently published webcam recordings.

Only original/remuxed real audio is read. Reference camera locations are used after
inference to measure error, never supplied as search bounds or candidate points.
"""
import argparse
import csv
import io
import hashlib
import json
import math
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from doppler_dox.audio import Spectrogram,decode
from doppler_dox.detect import detect_events
from doppler_dox.tracks import load_tracks
from doppler_dox.search import run_search
from doppler_dox.simple import assess_result
from doppler_dox.physics import ecef


def segments(media,directory,duration):
    for offset in range(0,int(duration),3600):
        length=min(3599.5,duration-offset-.5)
        if length<20:
            continue
        destination=directory/f'clip-{offset:05d}.webm'
        if not destination.exists():
            subprocess.run(['ffmpeg','-v','error','-i',str(media),'-ss',str(offset),'-t',str(length),
                            '-vn','-c:a','copy','-avoid_negative_ts','make_zero','-y',str(destination)],check=True)
        yield offset,destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--detect-only',action='store_true')
    parser.add_argument('--only',help='Test just the named camera')
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text())
    for case in manifest['cameras']:
        if args.only and case['id']!=args.only:
            continue
        output=Path(case['output']);output.mkdir(parents=True,exist_ok=True)
        media=Path(case['media']);metadata=json.loads(Path(case['metadata']).read_text())
        rows=[]
        track_rows=None
        if not args.detect_only and case.get('tracks') and Path(case['tracks']).exists():
            track_rows=list(csv.DictReader(io.StringIO(Path(case['tracks']).read_text())))
        source_start=case.get('recording_start_epoch',metadata['release_timestamp'])
        for offset,clip in segments(media,output,metadata['duration']):
            started=time.monotonic()
            spec=Spectrogram(decode(clip.read_bytes()))
            found=detect_events(spec)
            tracks=None
            if track_rows:
                selected_rows=[r for r in track_rows if source_start+offset-180 <= float(r['time']) <= source_start+offset+spec.duration+180]
                if selected_rows:
                    buffer=io.StringIO();writer=csv.DictWriter(buffer,fieldnames=selected_rows[0].keys());writer.writeheader();writer.writerows(selected_rows)
                    try: tracks,stats=load_tracks(buffer.getvalue())
                    except ValueError: tracks=None
            row=dict(offset_s=offset,duration_s=spec.duration,media=str(clip),events=found,
                     status='no_usable_signal' if not found else 'detected',recording_start_epoch=source_start+offset,
                     clock_basis=case.get('clock_basis','YouTube release_timestamp + source offset, uncorrected for broadcast latency'),
                     sha256=hashlib.sha256(clip.read_bytes()).hexdigest())
            print(case['id'],offset,'detected',len(found),[(round(e['cpa_s'],1),round(e['f0'],1),round(e['speed_mps'],1)) for e in found],flush=True)
            if found and tracks is not None:
                lat,lon=case['starting_area']
                radius=10000
                dy=radius/111320;dx=radius/(111320*math.cos(math.radians(lat)))
                spacing=max(200,math.ceil(math.sqrt(4*radius*radius*len(tracks)/230000)/50)*50)
                config=dict(south=lat-dy,north=lat+dy,west=lon-dx,east=lon+dx,spacing_m=spacing,
                            elevation_m=0,sound_speed=343,score_mode='brightness',candidate_limit=500,
                            clock_sweep_s=8,offset_tolerance_s=8,frequency_tolerance=.1,
                            speed_tolerance=.45,range_tolerance=.5,harmonics=3,silence=False,
                            recording_start=source_start+offset)
                selected=sorted(found[:2],key=lambda e:e['cpa_s'])
                row['config']=config
                try:
                    result=run_search(spec,tracks,selected,config)
                    best,message=assess_result(result,selected)
                    row['result']=result
                    row['status']='match' if best else 'inconclusive'
                    row['message']=message
                    if best and case.get('reference'):
                        row['reference_error_m']=float(np.linalg.norm(ecef(best['latitude'],best['longitude'])-ecef(*case['reference'])))
                except ValueError as exc:
                    row['status']='input_or_coverage_failure';row['message']=str(exc)
            elif found and not args.detect_only:
                row['status']='flight_data_unavailable'
            row['elapsed_s']=time.monotonic()-started
            rows.append(row)
            (output/('detections.json' if args.detect_only else 'benchmark.json')).write_text(json.dumps(dict(camera=case,clips=rows),indent=2))
            print('  outcome',row['status'],'error',row.get('reference_error_m'),flush=True)
        print('Saved',case['id'],flush=True)


if __name__=='__main__':
    main()
