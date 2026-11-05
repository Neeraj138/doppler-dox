"""Upload-first orchestration; signal processing and flight data stay backstage."""
import hashlib
import json
import math
import subprocess
import tempfile
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
import numpy as np
from .audio import decode, Spectrogram
from .detect import detect_events
from .search import run_search
from .tracks import load_tracks, timestamp
from .physics import ecef


def media_time(raw):
    """A metadata timestamp is a hint requiring confirmation, never a GPS answer."""
    with tempfile.TemporaryDirectory(prefix='doppler-meta-') as folder:
        path=Path(folder)/'media'
        path.write_bytes(raw)
        try:
            process=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_entries',
                                    'format_tags=creation_time,date,com.apple.quicktime.creationdate',
                                    '-of','json',str(path)],capture_output=True,timeout=15)
            tags=json.loads(process.stdout).get('format',{}).get('tags',{})
            for key in ('creation_time','com.apple.quicktime.creationdate','date'):
                if tags.get(key):
                    t=timestamp(tags[key])
                    return datetime.fromtimestamp(t,timezone.utc).isoformat()
        except (ValueError,OSError,subprocess.TimeoutExpired):
            pass
    return None


def assess_result(result, events):
    """Reject weak or geographically ambiguous evidence; never invent a pin."""
    if not result['candidates']:
        return None, 'We couldn’t match the aircraft sounds to this area and time. Try a wider starting area or check the recording time.'
    best=result['candidates'][0]
    if any(value<2 for value in best['event_scores']) or best['score']<4:
        return None, 'We heard a possible flyover, but the match is too weak to place a pin. A clearer or longer recording may help.'
    # A single straight pass often gives several near-equal locations even for one ID.
    distant=[]
    point=ecef(best['latitude'],best['longitude'])
    for candidate in result.get('heatmap',[]):
        if np.linalg.norm(ecef(candidate['latitude'],candidate['longitude'])-point)>1500:
            distant.append(candidate['score'])
    if distant and max(distant)>best['score']-.35:
        return None, 'More than one place fits this recording. Try a longer clip with another flyover so we can narrow it down.'
    return best, None


class SimpleFlow:
    def __init__(self, app, cache_directory, example=None):
        self.app=app
        self.cache=Path(cache_directory)
        self.example=example
        self.pending=None
        self.state=dict(status='idle',progress=0,message='',has_example=example is not None)

    def public(self):
        return dict(self.state)

    def update(self, message, progress):
        with self.app.lock:
            self.state.update(message=message,progress=float(progress))
            self.app.job.update(phase=message,progress=float(progress))

    def finish(self,status,message,**extra):
        with self.app.lock:
            self.state.update(status=status,message=message,progress=1 if status=='match' else 0,**extra)
            self.app.job.update(status='complete',phase=message,progress=self.state['progress'])

    def launch(self, raw=None, name='', context=None, example=False):
        with self.app.lock:
            self.app.check_mutable()
            if raw is None and not example and self.pending is None:
                raise ValueError('Choose a recording first.')
            if example and not self.example:
                raise ValueError('The real example is not available on this server.')
            self.state=dict(status='analyzing',progress=.02,message='Opening your recording',has_example=self.example is not None)
            self.app.job=dict(status='running',progress=.02,phase='Opening your recording')
            self.app.result=None
        def worker():
            try:
                self._run(raw,name,context,example)
            except (HTTPError,URLError,TimeoutError) as exc:
                self.finish('unavailable','Flight history is unavailable for that time right now. Recent recordings may need to wait until the daily archive is published. Try again later.')
            except ValueError as exc:
                message = str(exc)
                if any(word in message for word in ('Track CSV', 'track ', 'tracks', 'positions', 'segments', 'altitude')):
                    message = 'The available flight history does not cover this recording well enough. Try another time or recording.'
                elif 'budget' in message or 'Search is too large' in message:
                    message = 'That area has too much air traffic for this search. Try a shorter clip with one clear flyover.'
                self.finish('inconclusive',message)
            except Exception:
                self.finish('error','We couldn’t process this file. Try the original audio or video again.')
        threading.Thread(target=worker,daemon=True).start()

    def _run(self,raw,name,context,use_example):
        known=False
        if use_example:
            raw=self.example['path'].read_bytes()
            name=self.example['path'].name
        if raw is not None:
            self.pending=None
            self.update('Listening for aircraft in your recording',.06)
            spec=Spectrogram(decode(raw))
            events=detect_events(spec,self.update)
            recorded=media_time(raw)
            digest=hashlib.sha256(raw).hexdigest()
            known=bool(self.example and digest==self.example['digest'])
            self.pending=dict(spec=spec,events=events,name=name,recorded_at=recorded,known=known)
            with self.app.lock:
                self.app.spec=spec
                self.app.events=events[:2]
            if not events:
                return self.finish('inconclusive','No clear aircraft flyover found. Try recording a plane from its approach until the sound fades, without cuts or music.',file_name=name)
        pending=self.pending
        spec,events=pending['spec'],pending['events']
        known=pending['known']
        self.state['file_name']=pending['name']
        self.state['duration_s']=spec.duration
        if known and context is None:
            tracks=self.example['tracks']
            config=dict(self.example['config'])
            area_label='Oyster Bay, New York'
            if len(events)<2:
                return self.finish('inconclusive','We found only one usable pass in this clip. Try a recording with a fuller aircraft approach and departure.')
        else:
            if not context or not context.get('recorded_at') or context.get('latitude') is None or context.get('longitude') is None:
                return self.finish('needs_context','We found a possible flyover. Give us a recording time and a rough starting area to look around.',
                                   recorded_at=pending['recorded_at'],file_name=pending['name'])
            start=timestamp(str(context['recorded_at']))
            if start>datetime.now(timezone.utc).timestamp()+300:
                raise ValueError('That recording time is in the future. Check the date and timezone.')
            lat,lon=float(context['latitude']),float(context['longitude'])
            if not np.isfinite([lat,lon]).all() or not -80<=lat<=80 or not -179<=lon<=179:
                raise ValueError('Choose a starting area on the map, away from the poles or date line.')
            radius=10000
            dy=radius/111320
            dx=radius/(111320*math.cos(math.radians(lat)))
            config=dict(south=lat-dy,north=lat+dy,west=lon-dx,east=lon+dx,
                        spacing_m=500,elevation_m=0,sound_speed=343,score_mode='brightness',
                        candidate_limit=500,clock_sweep_s=8,offset_tolerance_s=8,
                        frequency_tolerance=.1,speed_tolerance=.45,range_tolerance=.5,
                        harmonics=3,silence=False,recording_start=start)
            self.update('Getting flight history for that time',.72)
            tracks=self._get_tracks(start,spec.duration,lat,lon)
            # Choose spacing automatically to remain within the actual CPU budget.
            area=4*radius*radius
            config['spacing_m']=max(200,math.ceil(math.sqrt(area*len(tracks)/230000)/50)*50)
            area_label='your starting area'
        self.update('Matching the sounds to nearby flight paths',.77)
        # Loudest distinct passes first; no manual traces or cached answer points.
        selected=sorted(events[:2],key=lambda e:e['cpa_s'])
        if len(selected)==1 and not config.get('recording_start'):
            return self.finish('needs_context','We found one flyover. Add its recording time and a rough starting area.',recorded_at=pending['recorded_at'])
        def progress(phase,fraction):
            self.update('Matching flight paths' if fraction<.7 else 'Narrowing down the location',.77+.21*fraction)
        result=run_search(spec,tracks,selected,config,progress=progress)
        with self.app.lock:
            self.app.tracks=tracks
            self.app.events=selected
            self.app.config=config
            self.app.result=result
        best,message=assess_result(result,selected)
        if best is None:
            return self.finish('inconclusive',message)
        return self.finish('match','We found a possible location.',
                           location=dict(latitude=best['latitude'],longitude=best['longitude']),
                           area=area_label,flyovers=len(selected),
                           note='An experimental estimate, not a verified location. Compare it with where the clip was actually recorded.')

    def _get_tracks(self,start,duration,lat,lon):
        # Reuse a supplied real dataset only when its time AND spatial coverage fit.
        if self.example:
            tracks=self.example['tracks']
            config=self.example['config']
            earliest=min(t.times[0] for t in tracks)
            latest=max(t.times[-1] for t in tracks)
            if earliest<=start and latest>=start+duration and config['south']<=lat<=config['north'] and config['west']<=lon<=config['east']:
                return tracks
        from .fetch import fetch_history
        from .ingest import convert_traces
        start_dt=datetime.fromtimestamp(start-180,timezone.utc)
        end_dt=datetime.fromtimestamp(start+duration+180,timezone.utc)
        days=[]
        day=start_dt.date()
        while day<=end_dt.date():
            days.append(day.isoformat())
            day+=timedelta(days=1)
        frames=[]
        # The observer region is 10 km radius; buffer aircraft tracks by another 20 km.
        dy=30000/111320
        dx=30000/(111320*math.cos(math.radians(lat)))
        bbox=[lon-dx,lat-dy,lon+dx,lat+dy]
        self.cache.mkdir(parents=True,exist_ok=True)
        for day in days:
            directory=self.cache/day
            parts=fetch_history(day,directory)
            key=hashlib.sha256(json.dumps([bbox,start,duration]).encode()).hexdigest()[:16]
            output=directory/f'region-{key}.csv'
            if not output.exists():
                convert_traces(parts,output,bbox,start-180,start+duration+180,directory/'aircraft-types.json')
            frames.append(output.read_text())
        text=frames[0]+''.join('\n'.join(frame.splitlines()[1:])+'\n' for frame in frames[1:])
        tracks,_=load_tracks(text)
        return tracks
