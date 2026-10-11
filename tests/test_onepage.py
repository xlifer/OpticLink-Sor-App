"""Μετρήσεις με έως 8 συμβάντα ανά λ: ΠΑΝΤΑ ολόκληρες σε μία σελίδα, χωρίς χαμένα/κομμένα/επικαλυπτόμενα δεδομένα."""
import itertools
import re

import pytest

from onepage_util import LONG, make_project, settings_combo
from otdr_report.pdf_report import ReportBuilder, Units, event_count, event_rows
from otdr_report.settings import prepare
from otdr_report.sor import parse_sor

pdfplumber = pytest.importorskip("pdfplumber")
MARGIN = 12 * 72 / 25.4
COMBOS = list(itertools.product(["el", "en"], ["overlay", "separate"], [True, False], [True, False], [True, False]))


def _build(tmp_path, lang, chart, sig, company, long_fields):
    p = make_project(tmp_path, name=LONG if long_fields else "C1_SCP31", fibers=1, long_fields=long_fields)
    c = p.sorted_cables()[0]
    s = settings_combo(lang, chart, sig, company)
    f = c.sorted_fibers()[0]
    read = {f.key: {w: prepare(parse_sor(m.path), s) for w, m in f.measurements.items()}}
    b = ReportBuilder(s)
    out = tmp_path / "x.pdf"
    assert b.build(out, [(c, [f], read)])
    return out, b, read[f.key], s, f


def _visible(value: str, words) -> bool:
    """Η τιμή φαίνεται ολόκληρη: σε μία λέξη ή σε κομμάτια το ένα κάτω από το άλλο (αναδίπλωση στο κελί)."""
    target = value.replace(" ", "")
    for w in words:
        if target.startswith(w["text"]):
            rest, cur = target[len(w["text"]):], w
            while rest:
                # επόμενο κομμάτι: στην αμέσως επόμενη γραμμή (κελί ή αναδιπλωμένη παράγραφος)
                nxt = [x for x in words if 0 < x["top"] - cur["top"] < 14 and rest.startswith(x["text"])]
                if not nxt:
                    break
                cur = min(nxt, key=lambda x: x["top"])
                rest = rest[len(cur["text"]):]
            if not rest:
                return True
    return False


@pytest.mark.parametrize("lang,chart,sig,company,long_fields", COMBOS)
def test_eight_events_always_one_page(tmp_path, lang, chart, sig, company, long_fields):
    out, b, sors, s, f = _build(tmp_path, lang, chart, sig, company, long_fields)
    assert [event_count(x) for x in sors.values()] == [8, 8]               # ακριβώς 8 ανά λ
    with pdfplumber.open(out) as pdf:
        assert len(pdf.pages) == 1                                           # 1310 + 1550 μαζί
        page = pdf.pages[0]
        words = page.extract_words()
        text = page.extract_text()
    assert b.last_level <= 2                                                 # χωρίς σμίκρυνση όλης της σελίδας

    # μέσα στα περιθώρια
    assert min(w["x0"] for w in words) >= MARGIN - 0.5
    assert max(w["x1"] for w in words) <= page.width - MARGIN + 0.5
    # καμία λέξη πάνω σε άλλη (π.χ. κείμενο που ξεχειλίζει από κελί)
    for i, a in enumerate(words):
        for c in words[i + 1:]:
            ix = min(a["x1"], c["x1"]) - max(a["x0"], c["x0"])
            iy = min(a["bottom"], c["bottom"]) - max(a["top"], c["top"])
            assert not (ix > 0.5 and iy > 0.5), f"επικάλυψη: {a['text']!r} / {c['text']!r}"

    # όλα τα δεδομένα ορατά: κάθε γραμμή συμβάντος/τμήματος, ονόματα αρχείων, Location, ID
    flat = re.sub(r"\s+", "", text)
    tokens = [w["text"] for w in words]
    t = b.t
    units = Units(max(x.length_km for x in sors.values()))
    for x in sors.values():
        assert f"{t['events']} – {x.wavelength} nm".replace(" ", "") in flat
        for cells, _ok, _seg in event_rows(x, s.thresholds, t, units):
            for v in cells[2:7]:                                             # απόσταση, απώλειες, κλίση, ανάκλαση
                if v not in ("", "–"):
                    assert v in tokens, f"λείπει {v!r} ({x.wavelength} nm)"
        assert _visible(x.path.name, words), x.path.name
    first = next(iter(sors.values()))
    for v in (first.location_a, first.location_b, first.cable_id, first.fiber_id, f.display):
        assert _visible(v, words) or v.replace(" ", "") in flat, v
