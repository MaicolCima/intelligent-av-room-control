import json
import os
from typing import Optional

from av_control.core.config import BASE_DIR
from av_control.core.events import log

MIN_SPAN_DEG = 10.0       
EXTRAP_DEG = 20.0         


def _unwrap(r: float, ref: float) -> float:
    return ((r - ref + 180.0) % 360.0) - 180.0


class BeamPanMap:
    def __init__(self, path: Optional[str] = None):
        self.path = path or str(BASE_DIR / "beam_calibration.json")
        self.points = []                     
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.points = json.load(f).get("points", [])
                log("CALIB", f"{len(self.points)} punti caricati")
            except Exception as e:
                log("CALIB", f"file calibrazione illeggibile: {e}")

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"points": self.points}, f, indent=2)

    def add_point(self, rotation: float, pan: int, quiet: bool = False):
        for p in self.points:
            if abs(_unwrap(p[0], rotation)) <= 3.0:
                p[0] = round(p[0] + 0.3 * _unwrap(rotation, p[0]), 1)
                p[1] = int(round(0.7 * p[1] + 0.3 * pan))
                self._save()
                return
        self.points.append([round(rotation, 1), int(pan)])
        self.points = self.points[-40:]
        self._save()
        stato = "PRONTA" if self.ready else "servono punti piu distanti tra loro"
        log("CALIB", f"nuovo punto: rot {rotation:.0f} gradi = pan {pan} (totale {len(self.points)}, {stato})")

    def _fit(self):
        ref = self.points[0][0]
        xs = [_unwrap(p[0], ref) for p in self.points]
        ys = [p[1] for p in self.points]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        return ref, xs, mx, my, a

    def residual_deg(self, rotation: float, pan: int) -> float:
        ref, xs, mx, my, a = self._fit()
        pred = my + a * (_unwrap(rotation, ref) - mx)
        return abs(pan - pred) / max(abs(a), 1e-6)

    def clear(self):
        self.points = []
        self._save()
        log("CALIB", "calibrazione cancellata")

    @property
    def ready(self) -> bool:
        if len(self.points) < 2:
            return False
        ref = self.points[0][0]
        xs = [_unwrap(p[0], ref) for p in self.points]
        return max(xs) - min(xs) >= MIN_SPAN_DEG

    def pan_for(self, rotation: float) -> Optional[int]:
        if not self.ready:
            return None
        ref, xs, mx, my, a = self._fit()
        x = max(min(xs) - EXTRAP_DEG, min(max(xs) + EXTRAP_DEG, _unwrap(rotation, ref)))
        return int(round(my + a * (x - mx)))