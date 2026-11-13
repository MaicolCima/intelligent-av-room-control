import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class BeamSample:
    ts: float
    status: int
    channel: Optional[int]
    elevation: Optional[float]
    rotation: Optional[float]
    area: Optional[int]


_RE = re.compile(r"camera_control_notice\s+\d+\s+\d+\s+NC\s+([-0-9.,]+)")


def parse_notice(message: str) -> Optional[BeamSample]:
    m = _RE.search(message)
    if not m:
        return None
    v = m.group(1).split(",")
    if len(v) < 5:
        return None

    def num(s, cast=float):
        try:
            return cast(s) if s != "" else None
        except ValueError:
            return None
    status = num(v[0], int)
    if status is None:
        return None
    return BeamSample(time.time(), status, num(v[1], int), num(v[2]), num(v[3]), num(v[4], int))


def _in_range(x: float, lo: float, hi: float, margin: float = 0.0) -> bool:
    x, lo, hi = x % 360, (lo - margin) % 360, (hi + margin) % 360
    return lo <= x <= hi if lo <= hi else (x >= lo or x <= hi)


class Zone:
    def __init__(self, d: dict):
        self.name = d["name"]
        self.rot = d["rotation"]
        self.elev = d.get("elevation")
        self.preset = d.get("preset")
        self.priority = bool(d.get("priority", False))

    def contains(self, rot: float, elev: Optional[float], margin: float = 0.0) -> bool:
        if not _in_range(rot, self.rot[0], self.rot[1], margin):
            return False
        if self.elev and elev is not None and not (self.elev[0] <= elev <= self.elev[1]):
            return False
        return True


class BeamZoneFilter:
    def __init__(self, cfg: dict):
        self.zones = [Zone(z) for z in cfg.get("zones", [])]
        self.priority_only = bool(cfg.get("priority_only", True))
        self.areas = set(cfg.get("accept_mic_areas") or [])
        self.window = float(cfg.get("window_s", 1.0))
        self.ratio = float(cfg.get("dwell_ratio", 0.7))
        self.min_samples = int(cfg.get("min_samples", 5))
        self.hyst = float(cfg.get("hysteresis_deg", 10))
        self._votes: deque = deque()           # (ts, zone_name, rotazione)
        self.rotation: Optional[float] = None  # rotazione STABILE (mediana) di chi parla
        self.current: Optional[Zone] = None    # ultima zona CONFERMATA

    def _classify(self, s: BeamSample) -> Optional[Zone]:
        if self.current and self.current.contains(s.rotation, s.elevation, self.hyst):
            return self.current
        for z in self.zones:
            if z.contains(s.rotation, s.elevation):
                return z
        return None

    def feed(self, s: BeamSample) -> Optional[Zone]:
        if s.status == 0 or s.rotation is None:
            return None
        if self.areas and s.area not in self.areas:
            return None
        z = self._classify(s)
        if z is None or (self.priority_only and not z.priority):
            return None                        # fuori dalle zone di priorita': ignorato
        now = s.ts
        self._votes.append((now, z.name, s.rotation))
        while self._votes and now - self._votes[0][0] > self.window:
            self._votes.popleft()
        if len(self._votes) < self.min_samples:
            return None
        names = [n for _, n, _ in self._votes]
        winner = max(set(names), key=names.count)
        if names.count(winner) / len(names) < self.ratio:
            return None
        self.current = next(zz for zz in self.zones if zz.name == winner)
        rots = [r for _, n, r in self._votes if n == winner]
        ref = rots[0]
        un = sorted(((r - ref + 180.0) % 360.0) - 180.0 for r in rots)
        self.rotation = (ref + un[len(un) // 2]) % 360.0
        return self.current