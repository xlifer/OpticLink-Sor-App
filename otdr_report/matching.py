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
# <όνομα>_<λ>  π.χ. ROUTE7_1550 (χωρίς αριθμό ίνας)
_RE_WL_ONLY = re.compile(rf"^(?P<cable>.+?){_SEP}(?P<wl>{_WL})(?:nm)?$", re.I)
# <καλώδιο>_<ίνα>  (το μήκος κύματος διαβάζεται από το αρχείο)
_RE_FIBER = re.compile(rf"^(?P<cable>.+?){_SEP}(?P<fiber>\d+)$")


@dataclass
class NameInfo:
    cable: str
    fiber: int
    fiber_label: str
    wavelength: int | None


def pair_name(path: str | Path, info: NameInfo | None = None) -> str:
    """Όνομα αρχείου χωρίς το μήκος κύματος: FARM1.R01_SCP31_1310_0117.sor → FARM1.R01_SCP31_0117."""
    info = info or parse_name(path)
    if info.fiber_label:
        return f"{info.cable}_{info.fiber_label}"
    return info.cable if info.wavelength else Path(path).stem


def parse_name(path: str | Path) -> NameInfo:
    stem = Path(path).stem
    for rx in (_RE_WL_FIBER, _RE_FIBER_WL):
        m = rx.match(stem)
        if m:
            return NameInfo(m["cable"], int(m["fiber"]), m["fiber"], int(m["wl"]))
    m = _RE_WL_ONLY.match(stem)
    if m:
        return NameInfo(m["cable"], 0, "", int(m["wl"]))
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
    sub: str = ""          # μέρος του ονόματος που δεν μπήκε στο καλώδιο (π.χ. "dis_101")
    measurements: dict[int, Measurement] = field(default_factory=dict)
    duplicates: list[Path] = field(default_factory=list)
    name: str = ""         # όνομα αρχείου χωρίς μήκος κύματος, π.χ. "scp51_dis_101_0001"

    @property
    def key(self) -> tuple[int, str]:
        return self.number, self.sub

    @property
    def display(self) -> str:
        if self.name:
            return self.name
        label = self.label or str(self.number)
        return f"{label} · {self.sub}" if self.sub else label

    @property
    def wavelengths(self) -> list[int]:
        return sorted(self.measurements)


@dataclass
class Cable:
    name: str
    fibers: dict[tuple[int, str], Fiber] = field(default_factory=dict)

    def sorted_fibers(self) -> list[Fiber]:
        return [self.fibers[k] for k in sorted(self.fibers, key=lambda k: (k[0], _natural_key(k[1])))]

    def fiber(self, number: int, sub: str = "") -> Fiber | None:
        return self.fibers.get((number, sub))

    @property
    def wavelengths(self) -> list[int]:
        s: set[int] = set()
        for f in self.fibers.values():
            s.update(f.measurements)
        return sorted(s)

    def incomplete(self) -> list[Fiber]:
        wls = set(self.wavelengths)
        return [f for f in self.sorted_fibers() if set(f.measurements) != wls]


def _parts(prefix: str) -> list[str]:
    return [x for x in prefix.split("_") if x] or [prefix]


@dataclass
class Project:
    """Όλα τα φορτωμένα αρχεία, ομαδοποιημένα σε καλώδιο → ίνα → μήκος κύματος.

    Το καλώδιο είναι τα πρώτα `group_level` τμήματα (χωρισμένα με "_") του ονόματος
    πριν από το μήκος κύματος. Με `group_level=None` το επίπεδο επιλέγεται αυτόματα:
    το πιο αναλυτικό επίπεδο στο οποίο τα περισσότερα καλώδια έχουν πάνω από μία ίνα.
    """
    cables: dict[str, Cable] = field(default_factory=dict)
    errors: list[tuple[Path, str]] = field(default_factory=list)
    group_level: int | None = None
    _items: list[tuple[Path, SorFile, NameInfo]] = field(default_factory=list)
    _seen: set[Path] = field(default_factory=set)
    _level_used: int = 0

    def sorted_cables(self) -> list[Cable]:
        return [self.cables[k] for k in sorted(self.cables, key=_natural_key)]

    @property
    def file_count(self) -> int:
        return len(self._items)

    @property
    def max_level(self) -> int:
        return max((len(_parts(i.cable)) for _, _, i in self._items), default=1)

    @property
    def level_used(self) -> int:
        return self._level_used

    def level_examples(self) -> list[tuple[int, str]]:
        """[(επίπεδο, παράδειγμα ονόματος καλωδίου)] με βάση το πρώτο αρχείο που έχει τα περισσότερα τμήματα."""
        if not self._items:
            return []
        parts = max((_parts(i.cable) for _, _, i in self._items), key=len)
        return [(k, "_".join(parts[:k])) for k in range(1, len(parts) + 1)]

    def add(self, path: Path, sor: SorFile) -> None:
        self._items.append((path, sor, parse_name(path)))
        self.regroup()

    def _split(self, info: NameInfo, level: int) -> tuple[str, str]:
        parts = _parts(info.cable)
        return "_".join(parts[:level]), "_".join(parts[level:])

    def _auto_level(self, items: list[NameInfo]) -> int:
        top = max(len(_parts(i.cable)) for i in items)
        for level in range(top, 0, -1):
            groups: dict[str, set] = {}
            for info in items:
                cable, sub = self._split(info, level)
                groups.setdefault(cable, set()).add((info.fiber, sub))
            singles = sum(1 for g in groups.values() if len(g) == 1)
            if singles <= len(groups) / 2:
                break
        else:
            return top
        # Μια λέξη χωρίς αριθμούς, ίδια σε όλα τα αρχεία (π.χ. "dis"), δεν είναι όνομα καλωδίου
        while level > 1:
            words = {_parts(i.cable)[level - 1] if len(_parts(i.cable)) >= level else None for i in items}
            word = words.pop() if len(words) == 1 else None
            if not word or any(ch.isdigit() for ch in word):
                break
            level -= 1
        return level

    def regroup(self) -> None:
        # Στην αυτόματη λειτουργία κάθε "οικογένεια" ονομάτων (ίδιο πρώτο τμήμα) αποφασίζεται χωριστά
        levels: dict[str, int] = {}
        if not self.group_level:
            families: dict[str, list[NameInfo]] = {}
            for _, _, info in self._items:
                families.setdefault(_parts(info.cable)[0], []).append(info)
            levels = {fam: self._auto_level(items) for fam, items in families.items()}
        self._level_used = self.group_level or (next(iter(levels.values())) if len(levels) == 1 else 0)
        self.cables = {}
        for path, sor, info in self._items:
            wl = info.wavelength or sor.wavelength
            level = self.group_level or levels[_parts(info.cable)[0]]
            name, sub = self._split(info, level)
            cable = self.cables.setdefault(name, Cable(name))
            fiber = cable.fibers.get((info.fiber, sub))
            if fiber is None:
                fiber = cable.fibers[(info.fiber, sub)] = Fiber(
                    name, info.fiber, info.fiber_label, sub, name=pair_name(path, info))
            if wl in fiber.measurements:
                fiber.duplicates.append(path)
            else:
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
                    self._items.append((p, sor, parse_name(p)))
                if progress and progress(i, total) is False:
                    ex.shutdown(cancel_futures=True)
                    break
        self.regroup()


def find_sor_files(folder: str | Path) -> list[Path]:
    return [p for p in Path(folder).rglob("*") if p.is_file() and p.suffix.lower() == ".sor"]


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
