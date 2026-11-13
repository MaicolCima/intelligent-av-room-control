import csv
import json
import os
import sys
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from av_control.core.events import log


class Metrics:
    def __init__(self, folder: str = "metrics"):
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.path = Path(folder) / f"run_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        self._f = open(self.path, "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._f)
        self._w.writerow(["t_wall", "name", "value", "extra"])
        self._lock = threading.Lock()
        self._marks = {}
        self._vals = defaultdict(list)
        log("METRICS", f"salvo le misure in {self.path}")

    def record(self, name: str, value: float, echo: bool = True, **extra):
        with self._lock:
            self._w.writerow([f"{time.time():.4f}", name, f"{value:.4f}",
                              json.dumps(extra) if extra else ""])
            self._f.flush()
            self._vals[name].append(value)
        if echo:
            ex = " ".join(f"{k}={v}" for k, v in extra.items())
            log("LAT", f"{name} = {value:.1f} {ex}")

    def mark(self, key: str):
        self._marks[key] = time.perf_counter()

    def since(self, key: str, name: str, pop: bool = True, echo: bool = True, **extra):
        t0 = self._marks.pop(key, None) if pop else self._marks.get(key)
        if t0 is not None:
            self.record(name, (time.perf_counter() - t0) * 1e3, echo, **extra)

    @contextmanager
    def timer(self, name: str, echo: bool = True, **extra):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.record(name, (time.perf_counter() - t0) * 1e3, echo, **extra)

    def summary(self):
        log("METRICS", f"{'metrica':28s} {'n':>6s} {'media':>9s} {'mediana':>9s} {'p95':>9s} {'max':>9s}")
        for name, v in sorted(self._vals.items()):
            s = sorted(v)
            log("METRICS", f"{name:28s} {len(s):6d} {sum(s)/len(s):9.1f} {s[len(s)//2]:9.1f} "
                           f"{s[min(len(s)-1, int(0.95*len(s)))]:9.1f} {s[-1]:9.1f}")

    def close(self):
        self.summary()
        self._f.close()


M = Metrics(os.environ.get("PIERO_METRICS_DIR", "metrics"))


def report(csv_path: str):
    import statistics
    data = defaultdict(list)
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            data[r["name"]].append(float(r["value"]))
    out = Path(csv_path).with_suffix("")
    out.mkdir(exist_ok=True)
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        plt = None
        print("matplotlib non installato: solo statistiche")
    print(f"{'metrica':28s} {'n':>6s} {'media':>9s} {'std':>8s} {'p50':>9s} {'p95':>9s} {'p99':>9s} {'max':>9s}")
    for name, v in sorted(data.items()):
        s = sorted(v)
        q = lambda p: s[min(len(s) - 1, int(p * len(s)))]
        sd = statistics.pstdev(s) if len(s) > 1 else 0.0
        print(f"{name:28s} {len(s):6d} {sum(s)/len(s):9.2f} {sd:8.2f} {q(.5):9.2f} {q(.95):9.2f} {q(.99):9.2f} {s[-1]:9.2f}")
        if plt and len(s) >= 5:
            fig, ax = plt.subplots(1, 2, figsize=(10, 3.5))
            ax[0].hist(s, bins=min(40, len(s)), color="#2a6fb0")
            ax[0].set(title=name, xlabel="valore", ylabel="occorrenze")
            ax[1].plot(s, [(i + 1) / len(s) for i in range(len(s))], color="#b04a2a")
            ax[1].axhline(0.95, ls="--", lw=0.8, color="gray")
            ax[1].set(title="CDF", xlabel="valore", ylabel="P(X<=x)")
            ax[0].grid(alpha=.3); ax[1].grid(alpha=.3)
            fig.tight_layout()
            fig.savefig(out / f"{name}.png", dpi=200)
            plt.close(fig)
    print(f"grafici in {out}/")


if __name__ == "__main__":
    report(sys.argv[1])
