"""Convert official readsb trace archives to an explicitly bounded track CSV.

Readsb trace format: https://github.com/wiedehopf/readsb/blob/dev/README-json.md
Archives are streamed; paths inside archives are never extracted onto the filesystem.
"""
import csv
import gzip
import io
import json
import tarfile
from pathlib import Path
from .tracks import timestamp


class JoinedParts(io.RawIOBase):
    def __init__(self, paths):
        self.paths = iter(paths)
        self.current = None

    def readable(self):
        return True

    def readinto(self, buffer):
        while True:
            if self.current is None:
                try:
                    self.current = open(next(self.paths), 'rb')
                except StopIteration:
                    return 0
            count = self.current.readinto(buffer)
            if count:
                return count
            self.current.close()
            self.current = None

    def close(self):
        if self.current:
            self.current.close()
        super().close()


def convert_traces(parts, output, bbox, start, end, types_path=None, altitude='geometric', altitude_offset=0):
    """bbox is west,south,east,north. Geometric heights are WGS84 ellipsoidal."""
    types = {}
    if types_path:
        raw = Path(types_path).read_bytes()
        types = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    west, south, east, north = bbox
    start, end = timestamp(str(start)), timestamp(str(end))
    if not -180 <= west < east <= 180 or not -90 <= south < north <= 90 or start >= end:
        raise ValueError('Invalid geographic or time bounds.')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = dict(airframes=0, output_tracks=0, output_positions=0, excluded_jets=0, missing_altitude=0)
    with output.open('w', newline='') as target, io.BufferedReader(JoinedParts(parts), 2**20) as stream:
        writer = csv.writer(target)
        writer.writerow(['track_id','time','latitude','longitude','altitude_m','engine'])
        with tarfile.open(fileobj=stream, mode='r|') as archive:
            for member in archive:
                if not member.isfile() or '/trace_full_' not in member.name:
                    continue
                if member.size > 32*1024*1024:
                    raise ValueError('Oversized trace entry in archive.')
                raw = archive.extractfile(member).read()
                if raw[:2] == b'\x1f\x8b':
                    raw = gzip.decompress(raw)
                document = json.loads(raw)
                counts['airframes'] += 1
                classification = types.get(document.get('t', ''), ['', ''])
                code = classification[1] if len(classification) > 1 else ''
                engine = code[2] if len(code) >= 3 else ''
                if engine in ('J','R'):
                    counts['excluded_jets'] += 1
                    continue
                rows, leg = [], 0
                for row in document.get('trace', []):
                    if len(row) < 8:
                        continue
                    flags = int(row[6] or 0)
                    if flags & 2:
                        leg += 1
                    t = float(document['timestamp'])+float(row[0])
                    if not start <= t <= end or row[1] is None or row[2] is None or row[3] == 'ground' or flags & 1:
                        continue
                    lat, lon = float(row[1]), float(row[2])
                    if not west <= lon <= east or not south <= lat <= north:
                        continue
                    if altitude == 'geometric':
                        alt = row[3] if flags & 8 else row[10] if len(row) > 10 else None
                    else:
                        alt = None if flags & 8 else row[3]
                    if alt is None:
                        counts['missing_altitude'] += 1
                        continue
                    rows.append([f'{document.get("icao", "unknown")}:{leg}',t,lat,lon,float(alt)*.3048+altitude_offset,engine])
                if rows:
                    writer.writerows(rows)
                    counts['output_tracks'] += 1
                    counts['output_positions'] += len(rows)
                if counts['airframes'] % 10000 == 0:
                    print(f'Parsed {counts["airframes"]:,} airframes; retained {counts["output_positions"]:,} positions', flush=True)
    metadata = dict(source='readsb / adsb.lol historical archive', altitude=altitude,
                    altitude_offset_m=altitude_offset, bbox=bbox, start=start, end=end, counts=counts)
    output.with_suffix('.metadata.json').write_text(json.dumps(metadata, indent=2))
    return counts
