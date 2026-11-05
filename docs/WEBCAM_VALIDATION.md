# Independent public webcam tests — 5 November 2026

**No independently verified location match was obtained.** These runs do not establish that the app can reliably locate general uploads. The original Oyster Bay example remains the only successful known-site check.

The independent recordings came from three different public webcam operators/sites, outside the original challenge. About 7.3 hours of archived audio plus a two-minute fresh live sample were examined. No generated audio or generated aircraft trajectories were used.

## Results

| Public source | Recording and test windows | Automatic candidates | Matching outcome |
|---|---|---:|---|
| [Lorain Lighthouse, Ohio](https://www.youtube.com/watch?v=my6GvU6lG0U), Lorain Port and Finance Authority | June 15, 2026; 2.56 hours, split chronologically into three app-sized windows | 0 accepted curves | No pin; inconclusive at detection stage |
| [Moosehead Lake seaplane fly-in, Maine](https://www.youtube.com/watch?v=Lm8qv-wFEHc), Boston and Maine Live | September 12, 2026; 4.77 hours, split into five chronological windows | 18 candidate curves across the five windows | All five windows were inconclusive; zero flight-timing matches using the current selection rules |
| [Lake Hood Seaplane Base, Alaska](https://www.youtube.com/watch?v=61pi8UjLOlo), StreamTime LIVE / Alaska Aviation Museum | Two-minute live sample captured November 5, 2026 | 0 accepted curves | No pin; inconclusive at detection stage |

The 18 Moosehead detections are **candidate tonal curves**, not 18 confirmed aircraft. The current app selects the strongest one or two distinct events per window; it does not search every combination of all candidates. There were no accepted location pins in this benchmark, so no independent metre-error or accuracy result can be reported.

The [machine-readable results](webcam-results.json) include per-window durations, audio hashes, recording clocks, candidate counts and matcher filter counts.

## How the tests were run

1. Downloaded the original public webcam audio with yt-dlp. Long archives were remuxed into chronological, nonoverlapping windows under the app's one-hour limit. Remuxing copies the real audio; it does not generate or synthesize content.
2. Ran the existing automatic detector and its existing acceptance thresholds. No hand-selected event windows, ridge guide points, saved answer coordinates or relaxed thresholds were used for localization. Optional diagnostics were added to log rejected proposals without changing inference.
3. Downloaded the official adsb.lol daily flight archives for June 15 and September 12, 2026, about 7.36 GB combined, then converted real region/time-filtered tracks using the application's readsb importer.
4. Ran the existing matcher with the same normal-user settings: a rough town-centre starting hint, 10 km search radius, automatically budgeted grid spacing, still air, 343 m/s sound speed, flat 0 m observer elevation, shared ±8 s clock sweep and the existing evidence gate.
5. Used any reference camera position only after inference for evaluation or explicitly labelled coverage diagnostics. It was not supplied as a location candidate or used to narrow the observer lattice to the camera site.
6. Uploaded a real clip from each source through the app's HTTP API. Lorain and Lake Hood returned inconclusive. Moosehead detected candidates and requested recording time and rough area. The independent historical-data matching runs used the same production detector/matcher modules and configuration. Moosehead’s first window also completed the full normal API flow: upload, time/area submission, official-archive cache lookup, regional ingestion and matching. It returned inconclusive with no pin; no manual traces were supplied.

The camera benchmark was selected for practicality, not randomly sampled. Lorain was chosen partly because another independent implementation reported aircraft tones in this archive. Moosehead was chosen because the operator published a seaplane event. Lake Hood was a short live sample, with no assertion that an aircraft passed during that interval. These tests do not estimate a population success rate, false-negative rate or false-location rate.

## Timestamp evidence

- Lorain: YouTube `release_timestamp` gives **2026-06-15 19:27:55 UTC**. The inspected video has no clock overlay. Broadcast/audio latency was not independently calibrated, so this clock is approximate.
- Moosehead: the first source frame visibly reads **2026-09-12 09:54:52**. Interpreting the local Maine clock as Eastern daylight time gives **13:54:52 UTC**, six seconds earlier than YouTube's `release_timestamp`. The visible-frame clock, rather than a fitted camera-position clock correction, was used for matching.
- Lake Hood: local UTC request start/end times were saved. HLS buffering and broadcast latency were unmeasured. Since no usable event was detected, no precise absolute-time localization was attempted. The exact two-minute sample is retained locally; it may not be recoverable from the long-running live stream on a fresh checkout.

## What the failures tell us

**Lorain:** weak template proposals failed the physical curve-fit acceptance checks. Real flight data was available: the converted dataset contains 1,288 positions, imported as 24 usable segments. A coverage-only diagnostic at the published lighthouse landmark found, among others, a flight at roughly 193 m/s and 7.8 km slant distance. That does not establish that its tone is recoverable from this audio, but it shows that missing flight history alone does not explain the detector's outcome. A known-site spectrum diagnostic is retained separately and is not counted as localization.

**Moosehead:** the converter retained 1,654 positions across the broader five-hour region, imported as 64 segments. The usable geometric-altitude dataset contained **zero positions below 915 m ellipsoidal height within 5 km of the Greenville starting-area centre**. That is a statement about the imported data, not proof that no low-flying planes were there. Barometric-only/missing-altitude positions can be omitted by the importer, and low-level ADS-B coverage can be incomplete. None of the selected detected event sequences matched the available tracks under the app's constraints.

**Lake Hood:** the fresh sample contained ambient audio (nonzero RMS), so this was not an empty-file check. It produced no accepted aircraft-like curve. Without independently confirming a flyover during that short interval, it is an inconclusive sample rather than a measured detector false negative.

There are additional unresolved limitations: broadcast timing, automatic event selection, weak-tone extraction, terrain/altitude datum handling and weather. The app's simple UI hides those implementation details; it cannot remove the physical/data requirements. More independent positive localization cases are needed before claiming the friends experiment works reliably.

## Reproduce

The manifest is [cases/webcam-benchmark.json](../cases/webcam-benchmark.json). Original media, full source metadata, clock frames, real tracks and detailed reports remain under ignored `data/webcam-validation/`, `data/history/` and `outputs/webcam-validation/` in the current workspace. Raw recordings are not republished in the repository. Recording copyright remains with the operators; adsb.lol flight data retains its ODbL attribution.

```bash
python scripts/benchmark_webcams.py cases/webcam-benchmark.json --detect-only
python scripts/benchmark_webcams.py cases/webcam-benchmark.json
python scripts/validate_webcam_uploads.py
python scripts/validate_webcam_uploads.py --with-history
python scripts/summarize_webcams.py
```

A fresh checkout requires downloading the listed real sources and official histories first. The daily archives are available at:

- [June 15, 2026](https://github.com/adsblol/globe_history_2026/releases/tag/v2026.06.15-planes-readsb-prod-0)
- [September 12, 2026](https://github.com/adsblol/globe_history_2026/releases/tag/v2026.09.12-planes-readsb-prod-0)

The manifest specifies the recording clock and starting-area hint for each case. The two archived videos remain the primary evidence; the fresh live sample is a local capture. Browser pixel-level visual QA remains unavailable in this environment; the HTTP and numerical runs above were executed.
