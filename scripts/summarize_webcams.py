#!/usr/bin/env python3
"""Create a compact, reviewable record of the completed real-webcam runs."""
import json
from pathlib import Path

manifest=json.loads(Path('cases/webcam-benchmark.json').read_text())
summary=dict(protocol=manifest['method'],independent_sources=[])
for case in manifest['cameras']:
    report=json.loads((Path(case['output'])/'benchmark.json').read_text())
    entry={k:case[k] for k in ('id','url','operator','starting_area','reference','reference_note')}
    entry['clips']=[]
    for clip in report['clips']:
        row={k:clip[k] for k in ('offset_s','duration_s','status','sha256','clock_basis','recording_start_epoch')}
        row['candidate_curves']=len(clip['events'])
        row['matched_events_requested']=min(2,len(clip['events']))
        if clip.get('result'):
            row['counts']=clip['result']['counts']
            row['returned_candidates']=len(clip['result']['candidates'])
        if clip.get('message'):row['message']=clip['message']
        if clip.get('track_import_error'):row['track_import_error']=clip['track_import_error']
        entry['clips'].append(row)
    metadata=Path(f'data/webcam-validation/{case["id"]}-tracks.metadata.json')
    if metadata.exists():entry['track_ingest']=json.loads(metadata.read_text())
    summary['independent_sources'].append(entry)
summary['accepted_pins']=sum(c['status']=='match' for s in summary['independent_sources'] for c in s['clips'])
summary['verified_location_matches']=0 if not summary['accepted_pins'] else 'Requires independent review of each returned pin'
summary['conclusion']='No independently verified location result. Inconclusive responses are not successful geolocation. This selected sample does not estimate a population success rate.' if not summary['accepted_pins'] else 'Returned pins require independent review; this sample does not establish a population success rate.'
Path('docs/webcam-results.json').write_text(json.dumps(summary,indent=2))
print('Saved docs/webcam-results.json')
