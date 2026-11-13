import json
from pathlib import Path
import yaml

BASE_DIR = Path(__file__).resolve().parents[2]


def load_settings(name: str = "settings.yaml") -> dict:
    p = BASE_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"[CONFIG] {p} non trovato")
    with open(p, "r", encoding="utf-8") as f:
        s = yaml.safe_load(f) or {}
    for k, v in s.get("paths", {}).items():
        pp = Path(v)
        s["paths"][k] = str(pp if pp.is_absolute() else (BASE_DIR / pp).resolve())
    return s


def load_commands(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
