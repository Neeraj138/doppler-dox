"""Doppler models with explicit emission/arrival time separation."""
from dataclasses import dataclass
import numpy as np
from scipy.interpolate import CubicHermiteSpline
from scipy.optimize import least_squares

SOUND_SPEED = 343.0


def ecef(lat, lon, altitude=0.0):
    """WGS84 geodetic coordinates (degrees, metres) to ECEF metres."""
    lat, lon = np.radians(lat), np.radians(lon)
    n = 6378137.0 / np.sqrt(1 - 6.69437999014e-3 * np.sin(lat)**2)
    return np.stack(((n + altitude) * np.cos(lat) * np.cos(lon),
                     (n + altitude) * np.cos(lat) * np.sin(lon),
                     (n * (1 - 6.69437999014e-3) + altitude) * np.sin(lat)), axis=-1)


def flyby(times, f0, speed, distance, cpa_received, c=SOUND_SPEED):
    """Exact constant-speed curve, parameterized by *received* CPA."""
    tau = np.asarray(times) - cpa_received + distance / c
    beta2 = (speed / c)**2
    emission = (tau - np.sqrt(beta2 * tau**2 + (1-beta2)*(distance/c)**2)) / (1-beta2)
    radial = speed**2 * emission / np.sqrt(distance**2 + (speed*emission)**2)
    return f0 / (1 + radial / c)


def fit_flyby(points, c=SOUND_SPEED):
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 8 or not np.isfinite(p).all():
        raise ValueError('Trace at least 8 finite time/frequency points.')
    p = p[np.argsort(p[:, 0])]
    t, f = p.T
    if np.ptp(t) < 8 or np.any(f <= 0) or len(np.unique(t)) < 8:
        raise ValueError('Trace must span at least 8 seconds with distinct times and positive frequencies.')
    if not 300 <= c <= 370:
        raise ValueError('Sound speed must be between 300 and 370 m/s.')
    bounds = ([5, 15, 50, t.min()-120], [2000, min(260, c*.85), 30000, t.max()+120])
    best = None
    for velocity in (60, 130, 210):
        result = least_squares(lambda x: flyby(t, *x, c=c)-f,
                               [np.median(f), velocity, 2500, np.median(t)],
                               bounds=bounds, x_scale='jac', loss='soft_l1', f_scale=.5,
                               max_nfev=500)
        rms = float(np.sqrt(np.mean(result.fun**2)))
        if best is None or rms < best[0]:
            best = (rms, result)
    rms, result = best
    f0, speed, distance, cpa = map(float, result.x)
    warnings = []
    if np.ptp(f) / np.mean(f) < .03:
        warnings.append('Small frequency sweep: speed and range are weakly constrained.')
    if cpa < t.min() or cpa > t.max():
        warnings.append('CPA lies outside the trace; trace both sides of the pass.')
    if rms / f0 > .015:
        warnings.append('Poor constant-speed fit; use generous bounds and inspect the trace.')
    if np.linalg.cond(result.jac) > 1e7:
        warnings.append('Fit is ill-conditioned; fitted parameters are not uniquely constrained.')
    if np.any(np.isclose(result.x, bounds[0], rtol=.01)) or np.any(np.isclose(result.x, bounds[1], rtol=.01)):
        warnings.append('Fit reaches a parameter bound.')
    n = max(2, len(f)//5)
    falling = float(np.median(f[:n])-np.median(f[-n:]))
    searchable = bool(falling > .015*f0 and rms < .025*f0 and speed > 30 and distance > 150
                      and t.min() <= cpa <= t.max() and np.linalg.cond(result.jac) < 1e7)
    if not searchable:
        warnings.append('Inconclusive: no well-constrained aircraft-like falling curve. Do not infer a location from this trace.')
    return dict(searchable=searchable, f0=f0, speed_mps=speed, distance_m=distance, cpa_s=cpa, rms_hz=rms,
                warnings=warnings, points=p.tolist(),
                model=np.column_stack((t, flyby(t, *result.x, c=c))).tolist())


@dataclass
class Track:
    id: str
    times: np.ndarray
    positions: np.ndarray
    engine: str = ''

    def __post_init__(self):
        self.origin = float(self.times[0])
        self.local_times = self.times - self.origin
        velocity = np.gradient(self.positions, self.local_times, axis=0)
        self.spline = CubicHermiteSpline(self.local_times, self.positions, velocity, extrapolate=False)
        self.derivative = self.spline.derivative()

    def cpa(self, observer, c=SOUND_SPEED):
        """Closest point on sampled trajectory, refined around its best segment."""
        a, v = self.positions[:-1], np.diff(self.positions, axis=0)
        u = np.clip(np.sum((observer-a)*v, axis=1)/np.maximum(np.sum(v*v, axis=1), 1e-12), 0, 1)
        distances = np.linalg.norm(a + u[:, None]*v-observer, axis=1)
        j = int(np.argmin(distances))
        t = self.local_times[j] + u[j]*np.diff(self.local_times)[j]
        # Refine on the smooth trajectory without using time-of-arrival as time-of-emission.
        from scipy.optimize import minimize_scalar
        result = minimize_scalar(lambda s: np.sum((self.spline(s)-observer)**2),
                                 bounds=(self.local_times[j], self.local_times[j+1]), method='bounded')
        t = float(result.x)
        r = float(np.linalg.norm(self.spline(t)-observer))
        speed = float(np.linalg.norm(self.derivative(t)))
        return dict(emission=self.origin+t, received=self.origin+t+r/c, distance=r, speed=speed,
                    edge=t < 1 or t > self.local_times[-1]-1)

    def received_curve(self, observer, c=SOUND_SPEED, step=.4):
        """Sample emission times, then map each sample to its arrival time."""
        te = np.linspace(0, self.local_times[-1], max(2, int(self.local_times[-1]/step)+1))
        rel = self.spline(te)-observer
        ranges = np.linalg.norm(rel, axis=1)
        radial = np.sum(self.derivative(te)*rel, axis=1)/np.maximum(ranges, 1)
        arrival = self.origin+te+ranges/c
        if np.any(np.diff(arrival) <= 0) or np.any(1+radial/c <= .1):
            raise ValueError('Non-subsonic or invalid flight geometry.')
        return arrival, 1/(1+radial/c)
