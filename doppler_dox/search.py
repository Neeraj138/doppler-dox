"""Coarse filters followed by locked-clock trajectory scoring and local refinement."""
from itertools import product
import math
import numpy as np
from .physics import ecef


def number(config, key, default, low, high):
    value = float(config.get(key, default))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{key} must be between {low} and {high}.')
    return value


def run_search(spec, tracks, events, config, elevations=None, progress=None):
    if not 1 <= len(events) <= 2:
        raise ValueError('Fit one or two events before searching.')
    c = number(config, 'sound_speed', 343, 300, 370)
    south = number(config, 'south', 40, -85, 85)
    north = number(config, 'north', 41, -85, 85)
    west = number(config, 'west', -74, -180, 180)
    east = number(config, 'east', -73, -180, 180)
    if south >= north or west >= east or north-south > 2 or east-west > 3:
        raise ValueError('Use ordered bounds covering at most 2° latitude × 3° longitude (no antimeridian crossing).')
    spacing = number(config, 'spacing_m', 200, 50, 5000)
    tolerance = number(config, 'offset_tolerance_s', 8, .5, 60)
    speed_tol = number(config, 'speed_tolerance', .4, .05, 1)
    range_tol = number(config, 'range_tolerance', .45, .05, 1)
    flat = number(config, 'elevation_m', 0, -500, 9000)
    frequency_tol = number(config, 'frequency_tolerance', .08, .005, .25)
    shift_limit = number(config, 'clock_sweep_s', 5, 0, 30)
    harmonics = int(number(config, 'harmonics', 3, 1, 5))
    mode = config.get('score_mode', 'brightness')
    if mode not in ('trace', 'brightness'):
        raise ValueError('score_mode must be brightness or trace.')
    start_time = config.get('recording_start')
    if len(events) == 1 and start_time is None:
        raise ValueError('A single event requires recording_start (UTC epoch or ISO time).')
    from .tracks import timestamp
    if start_time is not None:
        start_time = timestamp(str(start_time))
    events = sorted(events, key=lambda e: e['cpa_s'])
    if len(events) == 2 and events[1]['cpa_s']-events[0]['cpa_s'] < 8:
        raise ValueError('Select two distinct, non-overlapping passes at least 8 seconds apart.')
    lat_step = spacing/111320
    lon_step = spacing/(111320*np.cos(np.radians((south+north)/2)))
    lats = np.arange(south, north+lat_step*.001, lat_step)
    lons = np.arange(west, east+lon_step*.001, lon_step)
    cells = len(lats)*len(lons)
    if cells > 12000 or cells*len(tracks) > 300000:
        raise ValueError('Search is too large for the local CPU budget. Increase spacing or narrow bounds/tracks (12,000 cells / 300,000 cell-track pairs).')
    coarse = []
    counts = dict(grid_cells=cells, geometry_matches=0, timing_matches=0, silence_rejected=0)
    def report(phase, fraction):
        if progress:
            progress(phase, fraction)

    def elevation(lat, lon):
        return elevations.at(lat, lon) if elevations else flat

    for row, lat in enumerate(lats):
        report('Filtering geometry and event timing', .05+.35*row/max(1, len(lats)))
        for lon in lons:
            alt = elevation(lat, lon)
            obs = ecef(lat, lon, alt)
            passes = [t.cpa(obs, c) for t in tracks]
            choices = []
            for event in events:
                choices.append([i for i, p in enumerate(passes)
                                if not p['edge'] and p['distance'] < 15000
                                and abs(p['speed']/event['speed_mps']-1) <= speed_tol
                                and abs(p['distance']/event['distance_m']-1) <= range_tol])
            if any(not choices_for_event for choices_for_event in choices):
                continue
            counts['geometry_matches'] += 1
            # Avoid combinatorial explosion in dense traffic.
            if math.prod(map(len, choices)) > 1000:
                raise ValueError('Too many matching flight pairs; tighten fit tolerances or bounds.')
            for pair in product(*choices):
                if len(set(pair)) != len(pair):
                    continue
                first = passes[pair[0]]
                if start_time is not None and abs(first['received']-(start_time+events[0]['cpa_s'])) > tolerance:
                    continue
                if len(pair) == 2:
                    second = passes[pair[1]]
                    if abs((second['received']-first['received'])-(events[1]['cpa_s']-events[0]['cpa_s'])) > tolerance:
                        continue
                    if config.get('silence', False):
                        threshold = .8*max(first['distance'], second['distance'])
                        if any(i not in pair and first['received']+10 < p['received'] < second['received']-10
                               and p['distance'] < threshold for i, p in enumerate(passes)):
                            counts['silence_rejected'] += 1
                            continue
                counts['timing_matches'] += 1
                error = sum(abs(passes[i]['distance']/e['distance_m']-1)+abs(passes[i]['speed']/e['speed_mps']-1)
                            for i, e in zip(pair, events))
                coarse.append((error, float(lat), float(lon), alt, pair))
    if not coarse:
        return dict(candidates=[], heatmap=[], counts=counts,
                    warnings=['No consistent candidate. Check track coverage, timestamps, elevation, fit bounds and weather assumptions.'])
    # Keep a bounded shortlist spread across distinct track assignments.
    grouped = {}
    for item in sorted(coarse):
        grouped.setdefault(item[4], []).append(item)
    shortlist = []
    for rank in range(8):
        for pair in sorted(grouped, key=lambda p: grouped[p][0][0]):
            if rank < len(grouped[pair]):
                shortlist.append(grouped[pair][rank])
            if len(shortlist) >= 40:
                break
        if len(shortlist) >= 40:
            break
    counts['shortlisted'] = len(shortlist)
    counts['timing_candidates_not_scored'] = len(coarse)-len(shortlist)

    def score(lat, lon, alt, pair):
        obs = ecef(lat, lon, alt)
        curves = [tracks[i].received_curve(obs, c) for i in pair]
        cpa = tracks[pair[0]].cpa(obs, c)
        # All events use this SAME mapping from UTC arrival to audio time.
        anchor = start_time if start_time is not None else cpa['received']-events[0]['cpa_s']
        best = None
        shifts = np.linspace(-shift_limit, shift_limit, 11) if shift_limit else [0]
        for shift in shifts:
            parts, models, f0s = [], [], []
            for event, (arrival, ratios) in zip(events, curves):
                p = np.asarray(event['points'])
                times = p[:, 0]
                query = times+anchor+shift
                if query.min() < arrival[0] or query.max() > arrival[-1]:
                    break
                ratio = np.interp(query, arrival, ratios)
                f0 = float(np.clip(np.dot(p[:, 1], ratio)/np.dot(ratio, ratio),
                                   event['f0']*(1-frequency_tol), event['f0']*(1+frequency_tol)))
                if mode == 'trace':
                    value = -float(np.sqrt(np.mean((f0*ratio-p[:, 1])**2)))
                else:
                    freqs = np.linspace(event['f0']*(1-frequency_tol), event['f0']*(1+frequency_tol), 17)
                    values = [spec.brightness(times, ratio*f, harmonics) for f in freqs]
                    k = int(np.argmax(values))
                    delta = (freqs[1]-freqs[0])
                    fine = np.linspace(max(freqs[0], freqs[k]-delta), min(freqs[-1], freqs[k]+delta), 9)
                    vals = [spec.brightness(times, ratio*f, harmonics) for f in fine]
                    kk = int(np.argmax(vals))
                    f0, value = float(fine[kk]), float(vals[kk])
                parts.append(value)
                f0s.append(f0)
                models.append(np.column_stack((times, ratio*f0)).tolist())
            if len(parts) != len(events):
                continue
            value = float(np.mean(parts))
            if best is None or value > best['score']:
                best = dict(score=value, event_scores=parts, curves=models, f0s=f0s,
                            clock_shift_s=float(shift), recording_start_epoch=float(anchor+shift))
        if best is None:
            return None
        best.update(latitude=lat, longitude=lon, elevation_m=alt, tracks=[tracks[i].id for i in pair])
        return best

    scored = []
    for i, (_, lat, lon, alt, pair) in enumerate(shortlist):
        report('Scoring actual flight geometry', .4+.3*i/max(1, len(shortlist)))
        result = score(lat, lon, alt, pair)
        if result:
            scored.append((result, pair))
    scored.sort(key=lambda x: -x[0]['score'])
    # Refine the top 3 candidates to half-spacing, preserving bounds and elevation.
    fine_results = []
    seen = set()
    for i, (candidate, pair) in enumerate(scored[:3]):
        report('Refining best candidates', .7+.28*i/3)
        for dy, dx in product((-.5, 0, .5), repeat=2):
            lat = candidate['latitude']+dy*lat_step
            lon = candidate['longitude']+dx*lon_step
            key = (round(lat, 8), round(lon, 8), pair)
            if not south <= lat <= north or not west <= lon <= east or key in seen:
                continue
            seen.add(key)
            result = score(lat, lon, elevation(lat, lon), pair)
            if result:
                fine_results.append((result, pair))
    scored.extend(fine_results)
    scored.sort(key=lambda x: -x[0]['score'])
    winners = {}
    for candidate, pair in scored:
        winners.setdefault(pair, candidate)
    warnings = ['Experimental ranking, not a probability or validated accuracy estimate.',
                'Bounded shortlist: geometry pre-ranking can discard the true solution. Inspect counts and broaden/repeat searches.',
                'Assumes constant sound speed, still air, constant source tone and a common altitude datum.']
    if len(events) == 1:
        warnings.append('A single pass can have mirror or elongated solutions; inspect all candidates.')
    if config.get('silence'):
        warnings.append('Silence filtering assumes complete tracks and audibility; missing coverage can invalidate it.')
    report('Complete', 1)
    return dict(candidates=list(winners.values())[:20],
                heatmap=[{k: r[k] for k in ('latitude', 'longitude', 'score', 'tracks')} for r, _ in scored],
                counts=counts, warnings=warnings, score_mode=mode, resolution_m=spacing/2)
