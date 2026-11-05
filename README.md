# Doppler Dox

**Upload a clip. Follow the sound. See a possible location on OpenStreetMap.**

A small acoustic detective experiment inspired by [Colsto's video](https://youtu.be/UytYrhYLOKI). The main interface handles aircraft detection, curve fitting and real flight matching automatically. No spectrogram tracing, flight CSV uploads or physics controls are needed by the person trying it.

## Run it

Requires Python 3.11+, NumPy/SciPy and `ffmpeg` on PATH.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m doppler_dox serve
```

Open **http://127.0.0.1:8765**. The current workspace already has the Python dependencies and ffmpeg installed.

To enable **Try a real recording** with the prepared public challenge dataset:

```bash
python -m doppler_dox serve --case cases/real-challenge.json
```

The current workspace retains those real input files in ignored `data/real-challenge/`. A fresh clone needs to [download the real inputs](docs/REAL_VALIDATION.md) first. The example computes its result from the audio and actual tracks; it does not load a saved location or manual event traces.

## The experience

1. Drop in a video or audio file and choose **Find the location**.
2. The app listens for aircraft flyovers and compares them with real historical flight paths.
3. When needed, it asks for the recording start time and a rough starting area on a map. That is a search clue, not the recording location.
4. A supported match appears as a point on an interactive OpenStreetMap, with coordinates and an **Open in OpenStreetMap** link.
5. Weak signals, missing flight history or ambiguous matches produce a friendly inconclusive result, without a guessed map pin.

The main page has no analysis controls. The [advanced lab](docs/LAB.md) remains available at `/lab` for inspecting the underlying evidence.

## For friends trying it

Record a full plane flyover, ideally **2–3 minutes** from approach until it fades. Note the start time and send the original audio or video. Skip edits, added music and voice-message processing. Audio alone is enough.

No aircraft sound means no result. Missing aircraft history can also prevent a match. A clip with two distinct flyovers can provide more evidence. This is an experimental estimate; compare it with the actual recording location rather than treating it as proof.

## Flight data and maps

The public challenge uses prepared real data. Other recordings need a recording time and approximate area; the app downloads the corresponding official adsb.lol historical archive and filters it automatically. Daily archives can be several GB and are cached under ignored `data/history/`; the first request for a date can take several minutes. Very recent recordings may need to wait for the daily release. Internet access and sufficient disk space are required for new dates.

Normal searches look about 10 km around the chosen starting area. This regional CPU implementation does not perform a blind global search. Aircraft/terrain altitude uncertainty, weather, sparse coverage and similar sources remain limitations.

Leaflet is vendored locally under its included licence. Interactive maps load tiles from OpenStreetMap, display attribution and use normal browser caching. No tile prefetch or location reverse-geocoding runs in the background. Audio stays on this computer. The app binds to loopback and is intended for local use; it has not been deployed as a public multi-user service.

## Verification

```bash
python -m unittest discover -s tests -v
npm ci --ignore-scripts
npm run test:ui
python scripts/validate_simple.py cases/real-challenge.json outputs/real-challenge/simple-validation.json
```

The upload-first flow was checked using the original public recording and real historical ADS-B tracks. It automatically found both expected flights and returned a point about 415 m from the source video's displayed two-flight result. Short real excerpts also checked inconclusive handling and the time/area prompt. See the [real-data report](docs/REAL_VALIDATION.md) for evidence and limits.
