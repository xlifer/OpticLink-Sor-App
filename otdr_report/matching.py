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
# Έγκυρη μέτρηση = και τα δύο μήκη κύματος (απόφαση χρήστη). Όποια λείπει → ΕΛΛΙΠΗΣ.
REQUIRED_WAVELENGTHS = frozenset({1310, 1550})
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

    @property
    def paths(self) -> list[Path]:
        """Όλα τα αρχεία της μέτρησης, μαζί με τα διπλότυπα."""
        return [m.path for m in self.measurements.values()] + list(self.duplicates)


@dataclass
class Cable:
    name: str
    fibers: dict[tuple[int, str], Fiber] = field(default_factory=dict)
    required: frozenset[int] = REQUIRED_WAVELENGTHS

    def sorted_fibers(self) -> list[Fiber]:
        return [self.fibers[k] for k in sorted(self.fibers, key=lambda k: (k[0], _natural_key(k[1])))]

    def fiber(self, number: int, sub: str = "") -> Fiber | None:
        return self.fibers.get((number, sub))

    @property
    def wavelengths(self) -> list[int]:
        """Τα υποχρεωτικά μήκη κύματος (1310, 1550) και όσα άλλα υπάρχουν στο καλώδιο."""
        s: set[int] = set(self.required)
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
    required: frozenset[int] = REQUIRED_WAVELENGTHS
    _items: list[tuple[Path, SorFile, NameInfo]] = field(default_factory=list)
    _seen: set[Path] = field(default_factory=set)
    _stat: dict[Path, tuple[float, int]] = field(default_factory=dict)
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

    def remove_paths(self, paths: Iterable[Path]) -> list[Path]:
        """Αφαιρεί αρχεία από το έργο και επιστρέφει όσα αφαιρέθηκαν.

        Τα αρχεία ξεχνιούνται εντελώς, ώστε να μπορούν να ξαναπροστεθούν με load().
        Αν μια μέτρηση είχε διπλότυπο για το ίδιο μήκος κύματος, το διπλότυπο παίρνει τη θέση της.
        """
        targets = {Path(p).resolve() for p in paths}
        removed = [p for p, _, _ in self._items if p in targets]
        if removed:
            self._items = [it for it in self._items if it[0] not in targets]
            self._seen.difference_update(removed)
            for p in removed:
                self._stat.pop(p, None)
            self.regroup()
        return removed

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
            cable = self.cables.setdefault(name, Cable(name, required=self.required))
            fiber = cable.fibers.get((info.fiber, sub))
            if fiber is None:
                fiber = cable.fibers[(info.fiber, sub)] = Fiber(
                    name, info.fiber, info.fiber_label, sub, name=pair_name(path, info))
            if wl in fiber.measurements:
                fiber.duplicates.append(path)
            else:
                fiber.measurements[wl] = Measurement(path, wl, sor)

    def load(self, paths: Iterable[Path], progress: Callable[[int, int], bool] | None = None,
             workers: int = 8) -> "LoadResult":
        """Φορτώνει αρχεία .sor. Αρχεία που έχουν ήδη φορτωθεί ξαναδιαβάζονται μόνο αν άλλαξαν.

        Ένα αρχείο σημειώνεται ως φορτωμένο μόνο αφού διαβαστεί επιτυχώς: μετά από ακύρωση ή
        σφάλμα ανάγνωσης, η επόμενη φόρτωση το ξαναδοκιμάζει.
        """
        res = LoadResult()
        todo, queued = [], set()
        for p in paths:
            p = Path(p).resolve()
            if p in queued:
                continue
            queued.add(p)
            res.found += 1
            if p in self._seen and self._stat.get(p) == _file_stat(p):
                res.unchanged += 1
                continue
            todo.append(p)
        todo.sort(key=lambda p: (_natural_key(p.name), str(p)))

        def work(p: Path):
            try:
                return p, _file_stat(p), parse_sor(p, with_trace=False), None
            except (SorError, OSError, ValueError) as e:
                return p, None, None, str(e)

        index = {it[0]: i for i, it in enumerate(self._items)}
        total = len(todo)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, (p, st, sor, err) in enumerate(ex.map(work, todo), 1):
                if err:
                    self.errors.append((p, err))
                    res.failed.append((p, err))
                    if p in index:                       # ήταν φορτωμένο αλλά τώρα δεν διαβάζεται
                        self._items[index.pop(p)] = None  # type: ignore[call-overload]
                        self._seen.discard(p)
                        self._stat.pop(p, None)
                else:
                    item = (p, sor, parse_name(p))
                    if p in index:
                        self._items[index[p]] = item
                        res.updated += 1
                    else:
                        index[p] = len(self._items)
                        self._items.append(item)
                        res.loaded += 1
                    self._seen.add(p)
                    self._stat[p] = st
                if progress and progress(i, total) is False:
                    res.cancelled = True
                    res.not_processed = total - i
                    ex.shutdown(cancel_futures=True)
                    break
        self._items = [it for it in self._items if it is not None]
        self.regroup()
        return res


@dataclass
class LoadResult:
    found: int = 0              # αρχεία που ζητήθηκαν
    loaded: int = 0             # νέα
    updated: int = 0            # ήδη φορτωμένα που άλλαξαν στον δίσκο και ξαναδιαβάστηκαν
    unchanged: int = 0          # ήδη φορτωμένα, χωρίς αλλαγή
    failed: list[tuple[Path, str]] = field(default_factory=list)
    cancelled: bool = False
    not_processed: int = 0      # δεν πρόλαβαν να διαβαστούν λόγω ακύρωσης


def _file_stat(p: Path) -> tuple[float, int] | None:
    try:
        st = p.stat()
        return st.st_mtime, st.st_size
    except OSError:
        return None


def find_sor_files(folder: str | Path) -> list[Path]:
    return [p for p in Path(folder).rglob("*") if p.is_file() and p.suffix.lower() == ".sor"]


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
