"""Διορθώσεις τύπου συμβάντος από τον χρήστη (κόλληση ↔ connector) μέσω του Link map.

Το όργανο μπορεί να καταγράψει μια κόλληση ως connector ή το αντίθετο. Ο χρήστης το
διορθώνει στο Link map και η διόρθωση:
  * αποθηκεύεται μόνιμα, με κλειδί το περιεχόμενο του αρχείου (SHA-1) και τη θέση του
    συμβάντος, οπότε ισχύει και αν μετακινηθεί ο φάκελος, όχι όμως σε νέα μέτρηση·
  * δεν αλλάζει ποτέ το ίδιο το .sor.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .jsonstore import load_dict
from .sor import SorFile

KINDS = ("connector", "splice")


class OverrideStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        raw, self.load_error = load_dict(self.path)
        self._data: dict[str, dict[str, str]] = {}
        for d, ev in raw.items():
            if isinstance(d, str) and isinstance(ev, dict):
                ok = {str(k): v for k, v in ev.items() if isinstance(v, str) and v in KINDS}
                if ok:
                    self._data[d] = ok

    @staticmethod
    def _key(distance_km: float) -> str:
        return f"{distance_km * 1000:.1f}"          # θέση σε μέτρα από το OTDR

    def get(self, digest: str, distance_km: float) -> str | None:
        with self._lock:
            return self._data.get(digest, {}).get(self._key(distance_km))

    def set(self, digest: str, distance_km: float, kind: str | None) -> None:
        """kind: "connector", "splice", ή None για επαναφορά στο αρχικό."""
        if kind is not None and kind not in KINDS:
            raise ValueError(kind)
        with self._lock:
            ev = self._data.setdefault(digest, {})
            if kind is None:
                ev.pop(self._key(distance_km), None)
                if not ev:
                    self._data.pop(digest, None)
            else:
                ev[self._key(distance_km)] = kind
            self._save()

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def apply(self, sor: SorFile) -> SorFile:
        """Περνά τις αποθηκευμένες διορθώσεις στα ενδιάμεσα συμβάντα της μέτρησης."""
        for e in sor.events:
            kind = self.get(sor.digest, e.distance_km) if sor.digest else None
            # μόνο ενδιάμεσα συμβάντα· και μόνο αν διαφέρει από αυτό που έγραψε το όργανο
            if kind and e.role == "event" and kind != ("connector" if e.raw_reflective else "splice"):
                e.override = kind
            else:
                e.override = None
        return sor


# Κοινή αποθήκη για όλη την εφαρμογή. Η εφαρμογή ορίζει αρχείο· στα tests μένει στη μνήμη.
STORE = OverrideStore()


def use_store(store: OverrideStore) -> None:
    global STORE
    STORE = store


def toggle_event(sors: list[SorFile], event_distance_km: float, kind: str | None,
                 tolerance_km: float = 0.005) -> int:
    """Ορίζει τον τύπο του συμβάντος σε όλα τα μήκη κύματος της ίδιας ίνας.

    Το ίδιο φυσικό σημείο (π.χ. κόλληση στα 125 m) υπάρχει και στο 1310 και στο 1550,
    με λίγο διαφορετική απόσταση· ταιριάζεται με ανοχή. Επιστρέφει πόσα αρχεία άλλαξαν.
    """
    changed = 0
    for sor in sors:
        candidates = [e for e in sor.events if e.role == "event"
                      and abs(e.distance_km - event_distance_km) <= max(tolerance_km, 3 * sor.resolution_km)]
        if not candidates:
            continue
        e = min(candidates, key=lambda e: abs(e.distance_km - event_distance_km))
        natural = "connector" if e.raw_reflective else "splice"
        STORE.set(sor.digest, e.distance_km, None if kind == natural else kind)
        changed += 1
    return changed
