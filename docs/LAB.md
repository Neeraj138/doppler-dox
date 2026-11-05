# Advanced lab

A local workbench for investigating aircraft tones in audio and comparing them with historical ADS-B flight tracks. Built from the method in [Colsto's video](https://youtu.be/UytYrhYLOKI), using the complete transcript supplied by the project owner. Python + NumPy/SciPy backend, dependency-free browser interface. No API key required for the public archive downloader.

## Start

Requirements: Python 3.11+, NumPy, SciPy, and `ffmpeg` on PATH. Install `ffmpeg` with your system package manager.

```bash
git clone git@github.com:Neeraj138/doppler-dox.git
cd doppler-dox
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m doppler_dox serve
```

Open **http://127.0.0.1:8765**. To open the verified real case in the current workspace: `python -m doppler_dox serve --case data/real-challenge/case.json`. In the current development workspace, the Python dependencies and ffmpeg are already installed, so the last command is sufficient. Another port: `python -m doppler_dox serve --port 8766`.

## What to record

**No usable aircraft tone means no geolocation.** Silence alone cannot locate audio. Matching also requires the aircraft to appear in the available flight history.

For friends trying the experiment, record the entire approach and departure of an audible plane: typically **2–3 minutes**, noting the exact recording start time in UTC and the approximate area. Audio is sufficient; video adds no benefit to this pipeline. Unknown recording time requires at least two distinct passes: **15–30 minutes** may catch them near a busy flight path but guarantees nothing. Send the original file without cuts, music, voice-note processing or speed changes. Road traffic can produce similar curves, so the fit is evidence to inspect, not aircraft identification.

The app supports one event with known UTC recording start, or two events with unknown recording start and a known flight-data date. It searches a bounded region. It does **not** locate arbitrary short clips anywhere on Earth or guarantee the video's accuracy.

## Use the advanced lab

Open **http://127.0.0.1:8765/lab**. These controls are for inspecting and tuning the pipeline; the main page automates them.

1. Import a media file (WAV/MP3/FLAC/MP4/WebM; up to 128 MiB and 60 minutes). Processing stays local.
2. Import flight tracks using the CSV schema below. Include all relevant traffic and enough track before/after each pass; unknown aircraft classes are retained, known jets/rockets excluded.
3. Set a time/frequency window containing one complete falling ridge. Click guide points along faint tones, then **Auto trace window**, or place at least eight manual points. Fit the Doppler curve and add it as an event. Repeat for a second flyover if needed.
4. Set geographic bounds, grid spacing and observer elevation. Optionally load terrain samples. Set the UTC recording start when using only one event.
5. Run the search. Inspect ranked candidates, predicted-vs-observed curves, score maps and warnings. **Export report**, **GeoJSON**, or **Save case** before shutting down the server.

A numerical fit alone does not establish a location. Flat, rising, very poor, short-range or ill-conditioned traces are marked inconclusive and blocked from search. A plausible falling tone can still be a different source. Empty results mean no consistent candidate in the supplied data and bounds, not that the recording is safe or contains no aircraft.

## Historical data

Download the official adsb.lol archive and aircraft type table (several GB per day, resumable):

```bash
python -m doppler_dox fetch-history 2026-09-08 --output data/history/2026-09-08
```

Then stream the split tar files into a region/time-filtered CSV. Include a generous buffer around the observer search region so nearby aircraft paths are not clipped:

```bash
python -m doppler_dox ingest data/history/2026-09-08/*.tar.* \
  --types data/history/2026-09-08/aircraft-types.json \
  --bbox -74.1 40.5 -73.1 41.2 \
  --start 2026-09-08T20:30:00Z --end 2026-09-08T21:20:00Z \
  --output data/tracks.csv
```

The converter defaults to geometric altitude (WGS84 ellipsoidal). It drops missing/stale positions, skips known jets and respects new flight legs. Optional `--altitude barometric` requires your own pressure/datum correction. `--altitude-offset METRES` applies an explicit constant correction. **Use observer and aircraft heights in the same datum.** Most DEMs use mean sea level; convert them to the ellipsoid (or convert aircraft heights) before comparing. No automatic weather, pressure, geoid or DEM correction is claimed. A sidecar `.metadata.json` records conversion bounds and counts. Data keeps its provider's licence: adsb.lol history is ODbL; the recording belongs to its creator.

Track CSV:

```csv
track_id,time,latitude,longitude,altitude_m,engine
EXAMPLE,2026-11-01T12:00:00Z,40.0100,-74.9900,1500,T
EXAMPLE,2026-11-01T12:00:05Z,40.0110,-74.9860,1500,T
EXAMPLE,2026-11-01T12:00:10Z,40.0120,-74.9820,1500,T
```

`time` accepts UTC epoch seconds or an ISO timestamp with a timezone. `altitude_m` is metres, not feet. `engine` is optional: `J`/`JET` and `R`/`ROCKET` are excluded; `P`, `T`, and unknowns remain. Three distinct timestamps minimum; gaps over 120 s and physically implausible position jumps split tracks. The archive converter retains the last actual observation when source timestamps repeat and reports the duplicate count. At most 300 segments and 200,000 positions per import.

Optional terrain CSV: `latitude,longitude,elevation_m`. Nearest sample within 2 km is required at every searched location; otherwise the search stops. Without terrain CSV the explicitly entered flat elevation is used.

## Method and practical limits

- High-resolution spectrogram with global and running-median stationary-tone suppression; optional guide-constrained Viterbi tracing.
- Exact emission-time constant-speed flyby fit, estimating frequency, speed, slant range and received closest-approach time.
- WGS84/ECEF 3D track geometry, speed/range filters, delayed-CPA event timing and optional silence filtering.
- Actual trajectory frequency prediction, brightness scoring over harmonics or traced-frequency residual scoring. A **single clock shift is shared across both events**, with independent frequency sweeps.
- Coarse lattice, geometry shortlist, half-spacing local refinement, ranking by flight assignment, report/GeoJSON exports.

This is a CPU research prototype: maximum 12,000 cells and 300,000 cell–track combinations per search; regional bounds up to 2° latitude × 3° longitude. Only a bounded geometry shortlist is scored (default 120 candidates, adjustable up to 2,000), so a real solution can be discarded. It assumes still air, constant sound speed and constant source frequency. Sparse tracks, turning, weather, altitude uncertainty, background tones and audio processing affect results. One flight can produce mirror solutions. Silence filtering is off by default because missing flight data makes silence unreliable. Grid resolution is not positional accuracy, and scores are not probabilities. See [method notes](METHOD.md).

## Repeatable CLI / checks

The browser's saved case records local media/track filenames, event traces and search settings. Place it beside the original files, then run:

```bash
python -m doppler_dox run path/to/case.json
python -m unittest discover -s tests -v
node --check doppler_dox/static/app.js
```

The unit suite uses controlled numerical fixtures to check the mathematics and failure paths; these are not evidence of field accuracy. The browser's explicitly labelled synthetic demo is optional for learning. `export-demo` writes its WAV, CSV and runnable case. The [real-data validation report](REAL_VALIDATION.md) documents the original challenge recording and actual historical ADS-B run, including negative controls and verification limits.

## Privacy and operation

Use owned/consented recordings or public research challenges. The app binds only to loopback, rejects cross-origin mutations and keeps uploaded data in memory. No telemetry or external map tiles. The explicit `fetch-history` command contacts GitHub and downloads public data. Shutting down the server discards the session; exported cases/reports are local files. Do not expose this development server to the internet.
