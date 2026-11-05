"""Official historical data downloader. Data acquisition is explicit and resumable."""
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

API = 'https://api.github.com/repos/adsblol/globe_history_{year}/releases/tags/{tag}'
TYPES = 'https://raw.githubusercontent.com/wiedehopf/tar1090-db/master/db/icao_aircraft_types2.js'


def get(url, headers=None):
    return urlopen(Request(url, headers={'User-Agent':'doppler-dox/0.1', **(headers or {})}), timeout=60)


def fetch_history(day, directory):
    parsed = date.fromisoformat(day)
    tag = f'v{parsed:%Y.%m.%d}-planes-readsb-prod-0'
    with get(API.format(year=parsed.year, tag=tag)) as response:
        manifest = json.load(response)
    assets = sorted([a for a in manifest['assets'] if '.tar.' in a['name']],key=lambda a:a['name'])
    if not assets:
        raise ValueError('No readsb archive assets were published for this day.')
    folder = Path(directory)
    folder.mkdir(parents=True,exist_ok=True)
    print(f'Archive size: {sum(a["size"] for a in assets)/1e9:.2f} GB. Downloading official assets to {folder}',flush=True)
    for asset in assets:
        name = asset['name']
        url = asset['browser_download_url']
        if Path(name).name != name or urlparse(url).hostname != 'github.com' or not url.startswith('https://'):
            raise ValueError('Unexpected asset name or origin in archive manifest.')
        target = folder/name
        offset = target.stat().st_size if target.exists() else 0
        if offset == asset['size']:
            print(f'{name}: already complete',flush=True)
            continue
        if offset > asset['size']:
            raise ValueError(f'{name} is larger than the official asset. Move it aside and retry.')
        with get(url,{'Range':f'bytes={offset}-'} if offset else {}) as response:
            if offset and response.status != 206:
                raise ValueError('Server declined resume. Move the partial file aside before retrying.')
            total = offset
            with target.open('ab' if offset else 'wb') as output:
                last = total
                while chunk := response.read(1024*1024):
                    output.write(chunk)
                    total += len(chunk)
                    if total-last >= 64*1024*1024:
                        print(f'{name}: {total/asset["size"]:.0%}',flush=True)
                        last = total
        if target.stat().st_size != asset['size']:
            raise ValueError(f'Incomplete asset: {name}. Rerun to resume.')
        print(f'{name}: complete',flush=True)
    with get(TYPES) as response:
        (folder/'aircraft-types.json').write_bytes(response.read())
    (folder/'release.json').write_text(json.dumps(manifest,indent=2))
    return [str(folder/a['name']) for a in assets]
