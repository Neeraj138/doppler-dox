# Real-data validation — 5 November 2026

The final application check used real media and real historical aircraft tracks, not generated recordings or generated trajectories.

## Evidence and procedure

- Recording: Colsto's public [Unknown location — raw audio](https://youtu.be/4CxVxuMVkMc), 3,600 s of decoded audio. The source WebM has approximately 0.2 s of codec padding, which is tolerated and trimmed at the one-hour boundary.
- Flights: official [adsb.lol September 8, 2026 release](https://github.com/adsblol/globe_history_2026/releases/tag/v2026.09.08-planes-readsb-prod-0), approximately 3.87 GB of split tar assets. Aircraft engine classifications use the [tar1090 type table](https://github.com/wiedehopf/tar1090-db).
- The converter scanned 79,049 airframes and excluded 30,184 known jet/rocket airframes. Region/time filtering retained 26,971 actual positions from 123 airframes. It retained the final actual observation for 152 duplicate timestamps; it did not synthesize or average positions. 195 positions lacked usable geometric altitude and were omitted.
- Import produced 184 usable flight segments after splitting coverage gaps and 19 implausible position jumps. Data window: 20:30–21:20 UTC. Track ingestion bounds: 40.5–41.2° N, 74.1–73.1° W.
- The two real ridges were traced with manually placed guide points on the observed spectrogram, then fitted by the app. The guide points constrain tracing; they do not substitute modeled frequencies for measurements.
- Observer search: 40.84–40.91° N, 73.57–73.48° W, 200 m initial lattice, 100 m local refinement. Observer ellipsoidal elevation was approximated as −30 m for the waterfront; no measured DEM, weather or pressure correction was applied. Sound speed was 343 m/s, and silence filtering was off.
- All 74 timing candidates from 1,482 lattice cells were scored. No timing candidate was discarded by the configured shortlist limit of 1,000.

This is a **bounded known-site consistency check**. The area was chosen using the published answer. It is not a blind national search or an independent survey of the camera position.

## Observations

| Measurement | Event 1 | Event 2 |
|---|---:|---:|
| Audio received CPA | 2156.672 s | 3076.472 s |
| Fitted fundamental | 111.800 Hz | 129.412 Hz |
| Fitted speed | 148.15 m/s | 106.66 m/s |
| Fitted slant range | 7703 m | 3165 m |
| Constant-speed fit RMS | 0.989 Hz | 1.158 Hz |
| Matched real track | `a1dfeb:3` | `ace391:3` |
| Selected brightness score | 9.720 | 2.136 |

The selected point was **40.873238, −73.522479**, with combined score **5.928**. The source video at approximately [23:59](https://youtu.be/UytYrhYLOKI?t=1439) displays a best two-flight model point of **40.876466, −73.524951**. Our result is approximately **415 m from that displayed model point**. That reference is not a surveyed camera position; this comparison must not be reported as a measured camera error or as reproduction of the video's claimed 100 m accuracy.

Only one flight assignment survived timing and geometry filters in these bounds. This test checks agreement for that pair, not discrimination between thousands of competing flight pairs nationwide. Event 2 has visibly weaker agreement than Event 1; still-air assumptions, altitude uncertainty and ridge selection remain limitations. No confidence probability is assigned.

## Checks performed through the app's HTTP API

1. Served the actual HTML, JavaScript and CSS assets.
2. Uploaded and decoded the original recording using ffmpeg.
3. Uploaded the historical track CSV.
4. Retrieved populated spectrogram pixels for the real recording.
5. Fitted and saved both measured real events.
6. Traced a background control window at 900–960 s; its curve was marked **inconclusive**. This does not prove the window contains no aircraft; it shows the automatic trace did not support a usable fit.
7. Submitted the asynchronous trajectory search, polled completion and exported ranked results plus GeoJSON.
8. Deliberately shifted Event 2's measured times by 300 s; with a 0.5 s timing tolerance the real tracks yielded **no candidates**.
9. Verified installation of the Python package, checked JavaScript syntax, and passed the 15-test regression suite. Numerical unit fixtures remain separate from this real-data evidence.

A browser provider was unavailable in the environment. Browser clicking, visual layout and mobile interaction have **not** been verified. API/workflow validation is complete; visual QA remains outstanding.

## Reproduce locally

The current workspace retains the real media, tracks and case under ignored `data/real-challenge/`. Reports and observed-versus-predicted frequency plots are under ignored `outputs/real-challenge/`. These are not pushed to GitHub. The public recording remains its creator's work; flight data retains ODbL attribution.

```bash
python -m doppler_dox serve --case data/real-challenge/case.json
python scripts/validate_real.py data/real-challenge/case.json --output outputs/real-challenge/report.json
python -m doppler_dox run data/real-challenge/case.json
```

On a new checkout, download the recording with yt-dlp, acquire the official archive using `fetch-history`, then convert it using `ingest` as described in the README. The actual measured trace points and source settings are committed in `cases/real-challenge.json`; it refers to the ignored real media/track inputs.

SHA-256 of the validation inputs:

- Original WebM: `6884324b4fb9babbc89b10de71f283dd338766a15d2fbd1aeedb52216276692d`
- Converted track CSV: `11b27feab4cdb71e8466b78f602b8498c2be83cea5f22daaf6a837beed471b3c`


Fresh-checkout input preparation (yt-dlp is needed only for this public recording download):

```bash
python -m pip install yt-dlp
mkdir -p data/real-challenge
yt-dlp -f 'bestaudio[ext=webm]' -o data/real-challenge/challenge.webm https://youtu.be/4CxVxuMVkMc
python -m doppler_dox fetch-history 2026-09-08 --output data/history/2026-09-08
python -m doppler_dox ingest data/history/2026-09-08/*.tar.* \
  --types data/history/2026-09-08/aircraft-types.json \
  --bbox -74.1 40.5 -73.1 41.2 \
  --start 2026-09-08T20:30:00Z --end 2026-09-08T21:20:00Z \
  --output data/real-challenge/tracks.csv
python scripts/validate_real.py cases/real-challenge.json --output outputs/real-challenge/report.json
```
