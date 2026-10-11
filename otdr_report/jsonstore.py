"""Ασφαλής ανάγνωση των αρχείων αποθήκευσης (διορθώσεις χρήστη).

Ένα αλλοιωμένο αρχείο (μη έγκυρο JSON, λάθος δομή) δεν εμποδίζει ποτέ την εκκίνηση: κρατιέται
αντίγραφο δίπλα του (<όνομα>.corrupt-<ημερομηνία>.json) για ανάκτηση και η εφαρμογή ξεκινά με κενό.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def load_dict(path: Path | None) -> tuple[dict, str | None]:
    """(περιεχόμενο ως dict, μήνυμα προβλήματος ή None)."""
    if not path or not path.exists():
        return {}, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw, None
        problem = f"μη αναμενόμενη δομή ({type(raw).__name__})"
    except (OSError, ValueError) as e:
        problem = f"δεν διαβάζεται ({e})"
    backup = path.with_name(f"{path.stem}.corrupt-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
    try:
        backup.write_bytes(path.read_bytes())
        where = f" Αντίγραφο: {backup}"
    except OSError:
        where = ""
    return {}, f"Το αρχείο {path.name} {problem} και αγνοήθηκε.{where}"
