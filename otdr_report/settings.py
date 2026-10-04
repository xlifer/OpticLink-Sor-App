"""Ρυθμίσεις αναφοράς και κριτήρια Pass/Fail."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .sor import Event, SorFile


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

@dataclass
class ReportSettings:
    language: str = "el"                 # "el" ή "en"
    company: str = ""
    company_info: str = ""
    logo_path: str = ""
    operator: str = ""
    customer: str = ""
    project: str = ""
    chart_mode: str = "overlay"          # "overlay" (μαζί) ή "separate" (ξεχωριστά)
    summary_page: bool = True
    one_pdf_per_cable: bool = True
    thresholds: Thresholds = field(default_factory=Thresholds)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "ReportSettings":
        data = json.loads(text)
        th = Thresholds(**{k: v for k, v in data.pop("thresholds", {}).items()
                           if k in Thresholds.__dataclass_fields__})
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(thresholds=th, **known)


def event_ok(e: Event, th: Thresholds) -> bool | None:
    """True/False για το συμβάν, None αν δεν ελέγχεται (αρχή/τέλος ή κανένα ενεργό κριτήριο)."""
    if not th.enabled or e.type_name in ("Αρχή", "Τέλος"):
        return None
    checked = False
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


def evaluate(sor: SorFile, th: Thresholds) -> bool | None:
    """Συνολικό αποτέλεσμα μέτρησης: True=PASS, False=FAIL, None=χωρίς έλεγχο."""
    if not th.enabled or not any((th.check_splice, th.check_connector, th.check_reflectance,
                                  th.check_attenuation, th.check_total_loss)):
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
