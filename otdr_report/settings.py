"""Ρυθμίσεις αναφοράς και κριτήρια Pass/Fail."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .sor import Event, SorFile


# Τυπικές μέγιστες απώλειες PLC splitter 1:N (dB), από datasheets που ακολουθούν Telcordia GR-1209/GR-1221
SPLITTER_DEFAULTS = {"2": 4.0, "4": 7.4, "8": 10.5, "16": 13.8, "32": 17.1, "64": 21.0, "128": 24.0}


@dataclass
class Thresholds:
    """Κριτήρια Pass/Fail. Κάθε κριτήριο ενεργοποιείται ξεχωριστά.

    Από προεπιλογή μετράνε μόνο η απώλεια κόλλησης και η απώλεια connector.
    """
    enabled: bool = True                 # γενικός διακόπτης: off = καθόλου PASS/FAIL
    check_splice: bool = True
    max_splice_loss: float = 0.30        # dB, μη ανακλαστικό συμβάν (κόλληση)
    check_connector: bool = True
    max_connector_loss: float = 0.75     # dB, ανακλαστικό συμβάν (connector)
    check_reflectance: bool = False
    max_reflectance: float = -35.0       # dB, χειρότερη επιτρεπτή (πιο κοντά στο 0 = χειρότερη)
    check_attenuation: bool = False
    max_attenuation: dict[str, float] = field(default_factory=lambda: {
        "1310": 0.40, "1550": 0.30, "1625": 0.35, "1490": 0.35,
    })                                   # dB/km, μέση εξασθένηση ίνας
    check_total_loss: bool = False
    max_total_loss: float = 2.0          # dB
    # Splitters (μόνο σε live μετρήσεις 1625/1650): μέγιστη απώλεια ανά λόγο διαίρεσης, dB.
    # Τυπικά μέγιστα PLC splitter (Telcordia GR-1209/1221, datasheets κατασκευαστών).
    check_splitter: bool = True
    max_splitter_loss: dict[str, float] = field(default_factory=lambda: dict(SPLITTER_DEFAULTS))

@dataclass
class ReportSettings:
    language: str = "en"                 # "en" (προεπιλογή) ή "el"
    settings_version: int = 2
    company: str = ""
    company_info: str = ""
    logo_path: str = ""
    operator: str = ""
    customer: str = ""
    project: str = ""
    chart_mode: str = "overlay"          # "overlay" (μαζί) ή "separate" (ξεχωριστά)
    summary_page: bool = True
    one_pdf_per_cable: bool = True
    signatures: bool = True              # γραμμές "Συντάχθηκε / Ελέγχθηκε / Εγκρίθηκε"
    launch_mode: str = "file"            # "file" (από το όργανο), "manual" ή "none"
    launch_m: float = 0.0                # για launch_mode == "manual"
    # Μέτρηση χωρίς 1310 ΚΑΙ 1550 δεν είναι έγκυρη και δεν μπαίνει στο PDF.
    # Μόνο ο χρήστης μπορεί να το επιτρέψει, με δική του ευθύνη.
    allow_incomplete: bool = False
    thresholds: Thresholds = field(default_factory=Thresholds)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "ReportSettings":
        data = json.loads(text)
        th = Thresholds(**{k: v for k, v in data.pop("thresholds", {}).items()
                           if k in Thresholds.__dataclass_fields__})
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        if known.get("settings_version", 1) < 2:
            # Από την 1.2.0 το PDF βγαίνει στα αγγλικά εκτός αν ο χρήστης διαλέξει ελληνικά.
            known["language"] = "en"
            known["settings_version"] = 2
        return cls(thresholds=th, **known)


def launch_km_for(sor: SorFile, rs: ReportSettings) -> float:
    if rs.launch_mode == "manual":
        return max(0.0, rs.launch_m) / 1000
    if rs.launch_mode == "none":
        return 0.0
    return sor.user_offset_km


def prepare(sor: SorFile, rs: ReportSettings) -> SorFile:
    """Εφαρμόζει το launch cable των ρυθμίσεων και τις διορθώσεις του χρήστη (τύπος συμβάντος, στοιχεία μέτρησης)."""
    from . import fiber_info, overrides
    sor.apply_launch(launch_km_for(sor, rs))
    overrides.STORE.apply(sor)
    fiber_info.STORE.apply(sor)          # Start/End Location, Cable ID, Fiber ID του χρήστη
    return sor


def event_ok(e: Event, th: Thresholds) -> bool | None:
    """True/False για το συμβάν, None αν δεν ελέγχεται.

    Δεν ελέγχονται: η αρχή του OTDR, ό,τι είναι μέσα στο launch cable και το τέλος.
    Ο connector στο τέλος του launch cable (S) ελέγχεται κανονικά.
    """
    if not th.enabled or e.role in ("origin", "launch", "end"):
        return None
    checked = False
    if e.splitter_ratio:
        if not th.check_splitter:
            return None
        lim = th.max_splitter_loss.get(str(e.splitter_ratio), SPLITTER_DEFAULTS.get(str(e.splitter_ratio)))
        return e.splice_loss <= lim if lim is not None else None
    if e.reflective:
        if th.check_connector:
            checked = True
            if e.splice_loss > th.max_connector_loss:
                return False
        if th.check_reflectance and e.reflectance:
            checked = True
            if e.reflectance > th.max_reflectance:
                return False
    elif th.check_splice:
        checked = True
        if e.splice_loss > th.max_splice_loss:
            return False
    return True if checked else None


# Κάτω από αυτό το μήκος (μετά το launch cable) η ίνα θεωρείται νεκρή / κομμένη.
DEAD_FIBER_KM = 0.002


def is_dead_fiber(sor: SorFile) -> bool:
    """Δεν υπάρχει ίνα μετά το launch cable: χωρίς συμβάντα ή μήκος ≈ 0."""
    return not sor.events or sor.length_km < DEAD_FIBER_KM


def evaluate(sor: SorFile, th: Thresholds) -> bool | None:
    """Συνολικό αποτέλεσμα μέτρησης: True=PASS, False=FAIL, None=χωρίς έλεγχο.

    Νεκρή ίνα (δεν βρέθηκε ίνα μετά το launch cable) είναι πάντα FAIL όταν υπάρχει έλεγχος.
    """
    if not th.enabled:
        return None
    if is_dead_fiber(sor):
        return False
    if not any((th.check_splice, th.check_connector, th.check_reflectance,
                th.check_attenuation, th.check_total_loss, th.check_splitter and sor.is_live)):
        return None
    for e in sor.events:
        if event_ok(e, th) is False:
            return False
    if th.check_attenuation:
        lim = th.max_attenuation.get(str(sor.wavelength))
        att = sor.attenuation
        if lim and att is not None and att > lim:
            return False
    if th.check_total_loss and sor.total_loss is not None and sor.total_loss > th.max_total_loss:
        return False
    return True
