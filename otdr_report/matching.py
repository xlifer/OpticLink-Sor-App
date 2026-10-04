"""Ομαδοποίηση αρχείων .sor ανά καλώδιο και ίνα, με αντιστοίχιση μηκών κύματος.

Παράδειγμα: FARM1.R01_SCP31_1310_0117.sor και FARM1.R01_SCP31_1550_0117.sor
γίνονται η ίνα 117 του καλωδίου "FARM1.R01_SCP31", με μετρήσεις 1310 και 1550 nm.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .sor import SorError, SorFile, parse_sor

KNOWN_WAVELENGTHS = (850, 1300, 1310, 1383, 1490, 1550, 1625, 1650)
_WL = "|".join(str(w) for w in KNOWN_WAVELENGTHS)
_SEP = r"[_\-. ]"

# <καλώδιο>_<λ>_<ίνα>  π.χ. FARM1.R01_SCP31_1310_0117
_RE_WL_FIBER = re.compile(rf"^(?P<cable>.+?){_SEP}(?P<wl>{_WL})(?:nm)?{_SEP}(?P<fiber>\d+)$", re.I)
# <καλώδιο>_<ίνα>_<λ>  π.χ. FARM1.R01_SCP31_0117_1310
_RE_FIBER_WL = re.compile(rf"^(?P<cable>.+?){_SEP}(?P<fiber>\d+){_SEP}(?P<wl>{_WL})(?:nm)?$", re.I)
# <καλώδιο>_<ίνα>  (το μήκος κύματος διαβάζεται από το αρχείο)
_RE_FIBER = re.compile(rf"^(?P<cable>.+?){_SEP}(?P<fiber>\d+)$")


@dataclass
class NameInfo:
    cable: str
    fiber: int
    fiber_label: str
    wavelength: int | None


def parse_name(path: str | Path) -> NameInfo:
    stem = Path(path).stem
    for rx in (_RE_WL_FIBER, _RE_FIBER_WL):
        m = rx.match(stem)
        if m:
            return NameInfo(m["cable"], int(m["fiber"]), m["fiber"], int(m["wl"]))
    m = _RE_FIBER.match(stem)
    if m:
        return NameInfo(m["cable"], int(m["fiber"]), m["fiber"], None)
    return NameInfo(stem, 0, "", None)


@dataclass
class Measurement:
    path: Path
    wavelength: int
    sor: SorFile           # χωρίς καμπύλη (μόνο κεφαλίδες/συμβάντα) για να μένει ελαφρύ


@dataclass
class Fiber:
    cable: str
    number: int
    label: str
    measurements: dict[int, Measurement] = field(default_factory=dict)
    duplicates: list[Path] = field(default_factory=list)

    @property
    def wavelengths(self) -> list[int]:
        return sorted(self.measurements)


@dataclass
class Cable:
    name: str
    fibers: dict[int, Fiber] = field(default_factory=dict)

    def sorted_fibers(self) -> list[Fiber]:
        return [self.fibers[k] for k in sorted(self.fibers)]

    @property
    def wavelengths(self) -> list[int]:
        s: set[int] = set()
        for f in self.fibers.values():
            s.update(f.measurements)
        return sorted(s)

    def incomplete(self) -> list[Fiber]:
        wls = set(self.wavelengths)
        return [f for f in self.sorted_fibers() if set(f.measurements) != wls]


@dataclass
class Project:
    cables: dict[str, Cable] = field(default_factory=dict)
    errors: list[tuple[Path, str]] = field(default_factory=list)
    _seen: set[Path] = field(default_factory=set)

    def sorted_cables(self) -> list[Cable]:
        return [self.cables[k] for k in sorted(self.cables, key=_natural_key)]

    @property
    def file_count(self) -> int:
        return sum(len(f.measurements) + len(f.duplicates)
                   for c in self.cables.values() for f in c.fibers.values())

    def add(self, path: Path, sor: SorFile) -> None:
        info = parse_name(path)
        wl = info.wavelength or sor.wavelength
        cable = self.cables.setdefault(info.cable, Cable(info.cable))
        fiber = cable.fibers.setdefault(info.fiber, Fiber(info.cable, info.fiber, info.fiber_label))
        if wl in fiber.measurements:
            fiber.duplicates.append(path)
            return
        fiber.measurements[wl] = Measurement(path, wl, sor)

    def load(self, paths: Iterable[Path], progress: Callable[[int, int], bool] | None = None,
             workers: int = 8) -> None:
        new = []
        for p in paths:
            p = Path(p).resolve()
            if p not in self._seen:
                self._seen.add(p)
                new.append(p)
        new.sort(key=lambda p: _natural_key(p.name))

        def work(p: Path):
            try:
                return p, parse_sor(p, with_trace=False), None
            except (SorError, OSError, ValueError) as e:
                return p, None, str(e)

        total = len(new)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, (p, sor, err) in enumerate(ex.map(work, new), 1):
                if err:
                    self.errors.append((p, err))
                else:
                    self.add(p, sor)
                if progress and progress(i, total) is False:
                    ex.shutdown(cancel_futures=True)
                    break


def find_sor_files(folder: str | Path) -> list[Path]:
    return [p for p in Path(folder).rglob("*") if p.is_file() and p.suffix.lower() == ".sor"]


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
