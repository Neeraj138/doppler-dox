"""Strict, unit-explicit CSV ingestion; no implicit downloads or datum conversions."""
import csv
import io
from datetime import datetime
import numpy as np
from scipy.spatial import cKDTree
from .physics import Track, ecef


def timestamp(value):
    try:
        result = float(value)
    except ValueError:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('ISO timestamps must include a UTC offset or Z.')
        result = parsed.timestamp()
    if not np.isfinite(result):
        raise ValueError('Invalid timestamp.')
    return result


def load_tracks(text):
    rows = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    required = {'track_id', 'time', 'latitude', 'longitude', 'altitude_m'}
    if not required.issubset(rows.fieldnames or []):
        raise ValueError('Track CSV requires: track_id,time,latitude,longitude,altitude_m (metres, common altitude datum).')
    groups = {}
    count = 0
    for line, row in enumerate(rows, 2):
        count += 1
        if count > 200000:
            raise ValueError('Track file exceeds 200,000 positions. Filter the date and region first.')
        try:
            key = row['track_id'].strip()
            lat, lon, alt = map(float, (row['latitude'], row['longitude'], row['altitude_m']))
            t = timestamp(row['time'])
            if not key or not np.isfinite([lat, lon, alt]).all() or not -90 <= lat <= 90 or not -180 <= lon <= 180 or not -500 <= alt <= 20000:
                raise ValueError('Invalid ID, coordinates or altitude.')
            groups.setdefault(key, []).append((t, lat, lon, alt, row.get('engine', '').strip().upper()))
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Track CSV line {line}: {exc}') from exc
    tracks, excluded = [], 0
    for key, values in groups.items():
        if any(v[4] in ('J', 'R', 'JET', 'ROCKET') for v in values):
            excluded += 1
            continue
        values.sort(key=lambda r: r[0])
        data = np.asarray([r[:4] for r in values])
        if len(data) < 3:
            continue
        if np.any(np.diff(data[:, 0]) == 0):
            raise ValueError(f'Duplicate timestamps in track {key}. Deduplicate before importing.')
        # Never interpolate across large coverage gaps.
        segments = np.split(data, np.flatnonzero(np.diff(data[:, 0]) > 120)+1)
        for i, segment in enumerate(segments):
            if len(segment) < 3:
                continue
            track = Track(key if len(segments) == 1 else f'{key}:{i+1}', segment[:, 0],
                          ecef(segment[:, 1], segment[:, 2], segment[:, 3]))
            max_speed = np.max(np.linalg.norm(np.diff(track.positions, axis=0), axis=1)/np.diff(track.times))
            if max_speed >= 290:
                raise ValueError(f'Track {key} has implausible/subsonic-model-incompatible speeds. Check altitude/time units.')
            track.geographic = segment[:, 1:3].tolist()
            tracks.append(track)
    if not tracks:
        raise ValueError('No usable tracks: need at least three positions per non-jet segment.')
    if len(tracks) > 300:
        raise ValueError('Import at most 300 flight segments; filter your data first.')
    return tracks, dict(tracks=len(tracks), positions=count, excluded_jets=excluded,
                        start=min(t.times[0] for t in tracks), end=max(t.times[-1] for t in tracks))


class Elevations:
    def __init__(self, text):
        rows = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
        if not {'latitude', 'longitude', 'elevation_m'}.issubset(rows.fieldnames or []):
            raise ValueError('Elevation CSV requires latitude,longitude,elevation_m.')
        points = []
        for row in rows:
            points.append([float(row['latitude']), float(row['longitude']), float(row['elevation_m'])])
            if len(points) > 200000:
                raise ValueError('Elevation CSV exceeds 200,000 samples.')
        a = np.asarray(points)
        if a.ndim != 2 or a.shape[1] != 3 or not np.isfinite(a).all():
            raise ValueError('Invalid or empty elevation CSV.')
        if np.any(np.abs(a[:, 0]) > 90) or np.any(np.abs(a[:, 1]) > 180) or np.any(np.abs(a[:, 2]) > 10000):
            raise ValueError('Elevation coordinates or units out of range.')
        self.tree = cKDTree(ecef(a[:, 0], a[:, 1]))
        self.values = a[:, 2]

    def at(self, lat, lon):
        distance, index = self.tree.query(ecef(lat, lon))
        if distance > 2000:
            raise ValueError('No elevation sample within 2 km of a candidate. Add coverage or use explicit flat elevation.')
        return float(self.values[index])
