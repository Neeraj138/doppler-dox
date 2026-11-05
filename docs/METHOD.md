# Method and scope

Independent implementation based on the complete transcript supplied by the user for Colsto's video: https://youtu.be/UytYrhYLOKI.

1. Decode audio locally; compute a high-resolution, stationary-tone-suppressed spectrogram.
2. Trace separate flyovers and fit constant-speed Doppler curves to estimate frequency, speed, slant range and received CPA time.
3. Import timestamped flight tracks and observer elevations. Reject known jet/rocket engine classes while keeping unknown types.
4. Search a bounded geographic lattice. Calculate 3D CPA and sound-delayed CPA; filter by fitted speed/range and pair timing.
5. Optionally reject locations with intervening, nearer flyovers (silence is only meaningful with complete coverage).
6. Generate frequency curves from the actual flight geometry, evaluating source velocity at emission time. Score spectrogram brightness across harmonics, sweeping frequency independently per event and sharing ONE clock shift across all events.
7. Refine best coarse candidates; group results by flight pair; export ranked results and GeoJSON for inspection.
8. A single traced event can be compared to flight geometry with a known recording start time.

This release is a bounded-area CPU implementation. It does not fetch an entire country's historical data or DEM, correct pressure altitude, retrieve weather, prove an aircraft was audible, or guarantee geographic accuracy. Altitudes must share a datum. Uncertainty in wind, temperature, flight data, editing and source frequency can dominate the grid spacing. Synthetic recovery tests implementation consistency, not field performance. One straight pass has mirror solutions; parallel passes or sparse coverage can remain ambiguous. Scores are ranking values, not probabilities. The original video's 100 m result is not a promised accuracy.

Numerical references: SciPy signal spectrogram / optimize least_squares documentation; WGS84 ellipsoid coordinates; source-observer Doppler relation f = f0 / (1 + radial_velocity / sound_speed) with radial velocity positive away. Solve t_receive = t_emit + range(t_emit)/c before evaluating frequency. Straight-line fit uses the analytic emission-time solution; trajectory scoring interpolates positions in ECEF and evaluates the derivative of a cubic Hermite spline.

Use recordings you own, consented recordings or public research challenges. Audio and tracks stay on the local machine. The simple UI displays OpenStreetMap tiles for the requested map view. There is no telemetry. New-date flight history is downloaded explicitly as part of the submitted search.
