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
    if e.splitter_ratio:
        return "splitter"
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


# Τα εικονίδια είναι 52×52 px με το καλώδιο στις γραμμές 23–28· το line.png είναι 51 px ύψος
# με το καλώδιο στις γραμμές 22–27. Για να είναι στην ίδια ευθεία, η γραμμή σχεδιάζεται στην
# κλίμακα του εικονιδίου και 1 px (του εικονιδίου) πιο κάτω.
ICON_PX = 52
LINE_PX = 51
LINE_SHIFT_PX = 1


def line_band(size: float) -> tuple[float, float]:
    """(απόσταση από την πάνω πλευρά του εικονιδίου, ύψος) για το line.png, σε μονάδες σχεδίασης."""
    k = size / ICON_PX
    return LINE_SHIFT_PX * k, LINE_PX * k


def fit_labels(lefts: list[float], widths: list[float], pad: float = 2.0) -> list[bool]:
    """Ποιες ετικέτες χωράνε χωρίς να πέφτουν η μία πάνω στην άλλη (από αριστερά, με προτίμηση στην τελευταία).

    Με πολλά κοντινά συμβάντα δείχνονται όσες χωράνε· όλα τα συμβάντα μένουν στον πίνακα.
    """
    n = len(lefts)
    show = [False] * n
    last_right = None
    for k in range(n):
        if last_right is None or lefts[k] >= last_right + pad:
            show[k] = True
            last_right = lefts[k] + widths[k]
    if n and not show[-1]:
        for k in range(n - 2, -1, -1):          # η τελευταία (το τέλος) φαίνεται πάντα
            if show[k] and lefts[k] + widths[k] + pad > lefts[-1]:
                show[k] = False
            elif show[k]:
                break
        show[-1] = True
    return show
