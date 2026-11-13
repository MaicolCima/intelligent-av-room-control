import re
import difflib
from typing import Optional, Tuple


def normalize(text: str) -> str:
    t = text.lower().replace("'", " ").replace("’", " ")
    t = re.sub(r"[^a-zà-ú0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _score(a: str, b: str) -> float:
    best = difflib.SequenceMatcher(None, a, b).ratio() * 100
    wa, wb = a.split(), b.split()
    n = len(wb)
    if n and len(wa) > n:  
        for i in range(len(wa) - n + 1):
            best = max(best, difflib.SequenceMatcher(None, " ".join(wa[i:i + n]), b).ratio() * 100)
    return best


class CommandMatcher:
    def __init__(self, commands: list, default_threshold: float = 80):
        self.entries = []
        for c in commands:
            th = c.get("fuzzy_threshold", default_threshold)
            for p in c.get("phrases", []):
                self.entries.append((normalize(p), th, c))

    def match(self, text: str) -> Optional[Tuple[dict, float]]:
        t = normalize(text)
        if not t:
            return None
        best, best_score = None, 0.0
        for phrase, th, cmd in self.entries:
            s = _score(t, phrase)
            if s >= th and s > best_score:
                best, best_score = cmd, s
        return (best, best_score) if best else None
