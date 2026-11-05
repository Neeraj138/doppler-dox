"""Automatic, template-proposed aircraft ridge detection.

Templates propose signals; fitted ridges and local brightness decide whether to keep
one. Detections remain hypotheses: other moving tonal sources can look similar.
"""
import numpy as np
from scipy.ndimage import map_coordinates, maximum_filter
from scipy.signal import fftconvolve
from .physics import flyby, fit_flyby


def detect_events(spec, progress=None, max_events=6):
    def report(message, value):
        if progress:
            progress(message, value)
    if spec.duration < 20:
        return []
    report('Listening for passing aircraft', .12)
    times = np.arange(spec.t[0], spec.t[-1], 2.)
    frequencies = np.geomspace(40, 700, 192)
    coords = np.stack(np.broadcast_arrays((frequencies[:, None]-spec.f[0])/(spec.f[1]-spec.f[0]),
                                         (times[None, :]-spec.t[0])/(spec.t[1]-spec.t[0])))
    image = map_coordinates(spec.db, coords, order=1, mode='nearest')
    log_step = np.log(frequencies[1]/frequencies[0])
    relative = np.arange(-60., 61., 2.)
    proposals = []
    models = [(v,d) for v in (50,80,110,140,180,220) for d in (500,1500,3500,6500)]
    for i,(speed,distance) in enumerate(models):
        report('Listening for passing aircraft', .12+.26*i/len(models))
        ratios = flyby(relative, 1., speed, distance, 0.)
        shifts = np.rint(np.log(ratios)/log_step).astype(int)
        half = int(np.max(np.abs(shifts)))+1
        kernel = np.zeros((2*half+1,len(relative)),dtype=np.float32)
        kernel[half+shifts,np.arange(len(relative))]=1/len(relative)
        values = fftconvolve(image, kernel[::-1,::-1],mode='same')
        valid = (frequencies>=55)&(frequencies<=450)
        values[~valid,:]=-100
        values[:, times < 25]=-100
        values[:, times > spec.duration-25]=-100
        peaks=(values == maximum_filter(values,size=(9,21)))&(values>3.)
        yy,xx=np.where(peaks)
        if not len(xx):
            continue
        order=np.argsort(values[yy,xx])[-12:]
        proposals.extend((float(values[y,x]),float(times[x]),float(frequencies[y]),speed,distance)
                         for y,x in zip(yy[order],xx[order]))
    proposals.sort(reverse=True)
    selected=[]
    for proposal in proposals:
        if any(abs(proposal[1]-p[1])<35 and .8<proposal[2]/p[2]<1.25 for p in selected):
            continue
        selected.append(proposal)
        if len(selected)>=32:
            break
    events=[]
    for i,(strength,cpa,f0,speed,distance) in enumerate(selected):
        report('Checking the sounds we found', .4+.28*i/max(1,len(selected)))
        best=None
        for half_window in (45,60):
            start=max(float(spec.t[0]),cpa-half_window)
            end=min(float(spec.t[-1]),cpa+half_window)
            guide_t=np.linspace(start,end,17)
            guide_f=flyby(guide_t,f0,speed,distance,cpa)
            low=max(20,float(guide_f.min())-9)
            high=min(800,float(guide_f.max())+9)
            try:
                points=spec.trace(start,end,low,high,np.column_stack((guide_t,guide_f)).tolist())
                event=fit_flyby(points)
            except ValueError:
                continue
            if not event['searchable'] or not 35<=event['speed_mps']<=240 or event['distance_m']>15000:
                continue
            p=np.asarray(event['points'])
            brightness=spec.brightness(p[:,0],p[:,1],harmonics=1)
            if brightness<5 or event['rms_hz']/event['f0']>.012:
                continue
            event['detection_strength']=float(brightness)
            quality=brightness-100*event['rms_hz']/event['f0']
            if best is None or quality>best[0]:
                best=(quality,event)
        if best:
            events.append(best[1])
    events.sort(key=lambda e:-e['detection_strength'])
    unique=[]
    for event in events:
        # One pass can produce several harmonics and slightly different fit CPAs.
        if any(abs(event['cpa_s']-other['cpa_s'])<65 for other in unique):
            continue
        unique.append(event)
        if len(unique)>=max_events:
            break
    report('Aircraft check complete', .7)
    return unique
