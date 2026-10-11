"""Διορθώσεις χρήστη για τα στοιχεία της μέτρησης: Start/End Location, Cable ID, Fiber ID.

* Αρχικά οι τιμές είναι αυτές του .sor (GenParams: location A/B, cable ID, fiber ID).
* Ο χρήστης τις διορθώνει στην εφαρμογή, ατομικά ή μαζικά. Η διόρθωση ισχύει για όλη τη μέτρηση
  (και τα δύο μήκη κύματος), αποθηκεύεται μόνιμα και δεν αλλάζει ποτέ το ίδιο το .sor.
* Όλες οι τιμές είναι κείμενο: το "001" μένει "001" και το "301.1" μένει "301.1".
* Κλειδί είναι το περιεχόμενο κάθε αρχείου (SHA-1), όπως στις διορθώσεις τύπου συμβάντος.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .sor import SorFile

# πεδίο διόρθωσης → πεδίο του SorFile
FIELDS = {
    "start_location": "location_a",
    "end_location": "location_b",
    "cable_id": "cable_id",
    "fiber_id": "fiber_id",
}


class InfoStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, str]] = {}
        if self.path and self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._data = {d: {k: str(v) for k, v in vals.items() if k in FIELDS}
                              for d, vals in raw.items() if isinstance(vals, dict)}
            except (OSError, ValueError):
                self._data = {}

    def get(self, digest: str) -> dict[str, str]:
        with self._lock:
            return dict(self._data.get(digest, {}))

    def update(self, digests: list[str], values: dict[str, str]) -> None:
        """Ορίζει μόνο τα πεδία του `values` (τα υπόλοιπα μένουν όπως είναι) σε όλα τα αρχεία."""
        bad = set(values) - set(FIELDS)
        if bad:
            raise ValueError(bad)
        with self._lock:
            for d in digests:
                if d:
                    self._data.setdefault(d, {}).update({k: str(v) for k, v in values.items()})
            self._save()

    def clear(self, digests: list[str], fields: list[str] | None = None) -> None:
        """Επαναφορά στις τιμές του .sor (όλα τα πεδία ή μόνο τα `fields`)."""
        with self._lock:
            for d in digests:
                vals = self._data.get(d)
                if vals is None:
                    continue
                for k in (fields or list(vals)):
                    vals.pop(k, None)
                if not vals:
                    self._data.pop(d, None)
            self._save()

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def apply(self, sor: SorFile) -> SorFile:
        """Περνά τις διορθώσεις στη μέτρηση· χωρίς διόρθωση μένει η τιμή του .sor."""
        orig = getattr(sor, "_info_from_sor", None)
        if orig is None:
            orig = {f: getattr(sor, attr) for f, attr in FIELDS.items()}
            sor._info_from_sor = orig
        vals = self.get(sor.digest) if sor.digest else {}
        for f, attr in FIELDS.items():
            setattr(sor, attr, vals.get(f, orig[f]))
        return sor

    def edited(self, sor: SorFile) -> set[str]:
        """Ποια πεδία της μέτρησης έχουν διόρθωση του χρήστη."""
        return set(self.get(sor.digest)) if sor.digest else set()


# Κοινή αποθήκη για όλη την εφαρμογή. Η εφαρμογή ορίζει αρχείο· στα tests μένει στη μνήμη.
STORE = InfoStore()


def use_store(store: InfoStore) -> None:
    global STORE
    STORE = store


def info_of(sors: list[SorFile]) -> dict[str, str]:
    """Τρέχουσες τιμές μιας μέτρησης (από το πρώτο μήκος κύματος που έχει τιμή)."""
    out = {}
    for f, attr in FIELDS.items():
        out[f] = next((getattr(s, attr) for s in sors if getattr(s, attr)), "")
    return out


def set_info(sors: list[SorFile], values: dict[str, str]) -> None:
    """Διόρθωση για όλη τη μέτρηση: ίδιες τιμές σε όλα τα μήκη κύματος της."""
    STORE.update([s.digest for s in sors], values)
    for s in sors:
        STORE.apply(s)
