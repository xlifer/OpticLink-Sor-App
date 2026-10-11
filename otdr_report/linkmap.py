"""Κοινή λογική του Link map (οθόνη και PDF), χωρίς εξάρτηση από Qt."""
from __future__ import annotations

import sys
from pathlib import Path

from .settings import evaluate, event_ok
from .sor import Event, SorFile

KINDS = ("start", "end", "connector", "splice", "splitter")
STATES = ("pass", "fail", "none")


def asset_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    for p in (base / "otdr_report" / "assets", Path(__file__).parent / "assets"):
        if p.is_dir():
            return p
    return Path(__file__).parent / "assets"


def icon_path(name: str) -> Path | None:
    """otdr_report/assets/icons/<name>.png (π.χ. "splice_pass"), αν υπάρχει."""
    p = asset_dir() / "icons" / f"{name}.png"
    return p if p.exists() else None


def node_state(e: Event, sor: SorFile, th) -> str:
    """pass / fail / none: το (E) δείχνει το συνολικό αποτέλεσμα της μέτρησης, τα υπόλοιπα το δικό τους."""
    if th is None or not th.enabled:
        return "none"
    ok = evaluate(sor, th) if e.role == "end" else event_ok(e, th)
    return "none" if ok is None else ("pass" if ok else "fail")


def node_kind(e: Event) -> str:
    if e.role in ("start", "origin"):
        return "start"
    if e.role == "end":
        return "end"
    return "connector" if e.reflective else "splice"


def linkmap_events(sor: SorFile) -> list[tuple[int, Event]]:
    """Τα συμβάντα του Link map: χωρίς το launch cable, από το (S) έως το (E)."""
    return [(i, e) for i, e in enumerate(sor.events) if e.role != "launch"]


def scale_positions(kms: list[float], x0: float, x1: float) -> list[float]:
    """Θέσεις στη μπάρα κλίμακας: αναλογικές με την απόσταση από το (S)."""
    lo = min(kms, default=0.0)
    span = (max(kms, default=0.0) - lo) or 1.0
    return [x0 + (k - lo) / span * (x1 - x0) for k in kms]


def node_positions(kms: list[float], x0: float, x1: float, gap: float) -> list[float]:
    """Θέσεις εικονιδίων όπως στο όργανο: κατά προσέγγιση αναλογικές, με ελάχιστη απόσταση `gap`."""
    n = len(kms)
    if n <= 1:
        return [(x0 + x1) / 2] * n
    if gap * (n - 1) >= x1 - x0:
        return [x0 + k * (x1 - x0) / (n - 1) for k in range(n)]
    xs = scale_positions(kms, x0, x1)
    for k in range(1, n):
        xs[k] = max(xs[k], xs[k - 1] + gap)
    xs[-1] = min(xs[-1], x1)
    for k in range(n - 2, -1, -1):
        xs[k] = min(xs[k], xs[k + 1] - gap)
    return xs
