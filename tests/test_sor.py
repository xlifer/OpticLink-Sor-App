from pathlib import Path

import pytest

from otdr_report.sor import SorError, parse_sor, parse_sor_bytes
from otdr_report.synthetic import build_sor

SAMPLE = Path(__file__).parent / "data" / "grandway_sample_1550.sor"


def test_grandway_sample_header():
    s = parse_sor(SAMPLE)
    assert s.version == 2.0
    assert s.wavelength == 1550
    assert s.supplier == "Grandway"
    assert s.ior == pytest.approx(1.468)
    assert len(s.trace) == 39173


def test_grandway_sample_events():
    s = parse_sor(SAMPLE)
    assert len(s.events) == 7
    assert s.events[0].type_name == "Αρχή"
    assert s.events[-1].is_end
    assert s.length_km == pytest.approx(120.031, abs=0.01)
    assert s.events[1].splice_loss == pytest.approx(0.344)
    assert s.events[1].reflectance == pytest.approx(-37.244)
    # Η συνολική απώλεια λείπει από το αρχείο και υπολογίζεται από τα συμβάντα
    assert s.total_loss == pytest.approx(22.92, abs=0.05)
    assert 0.15 < s.attenuation < 0.19


def test_synthetic_roundtrip():
    data = build_sor(1310, 3.0, [(1.0, 0.1, 0), (2.0, 0.4, -45.0)], cable="C1", fiber="0007")
    s = parse_sor_bytes(data)
    assert s.wavelength == 1310
    assert s.cable_id == "C1" and s.fiber_id == "0007"
    assert s.length_km == pytest.approx(3.0, abs=0.001)
    assert [round(e.distance_km, 3) for e in s.events] == [0.0, 1.0, 2.0, 3.0]
    assert s.events[2].reflective and not s.events[1].reflective
    assert s.attenuation == pytest.approx(0.33, abs=0.001)


def test_not_a_sor_file():
    with pytest.raises(SorError):
        parse_sor_bytes(b"hello world, this is not an OTDR file at all")
