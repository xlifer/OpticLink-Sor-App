"""Αναγνώστης αρχείων OTDR .sor (Telcordia/Bellcore SR-4731, έκδοση 1 και 2).

Οι συντελεστές μετατροπής είναι ίδιοι με την παλιά εφαρμογή Grandway
(SORPC_grandway/SorAssist.cpp):
  * θέση συμβάντος  = time_of_travel * 1e-10 * c / n   (μονής διαδρομής)
  * απόσταση/σημείο = data_spacing   * 1e-14 * c / n
  * τιμή καμπύλης   = raw * scale_factor / 1e6  dB      (scale 1000 == 1.0)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

C_KM_PER_S = 299792.458


class SorError(Exception):
    pass


class _Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.d = data
        self.p = pos

    def _unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        if self.p + size > len(self.d):
            raise SorError("Απρόσμενο τέλος αρχείου")
        val = struct.unpack_from(fmt, self.d, self.p)[0]
        self.p += size
        return val

    def u16(self): return self._unpack("<H")
    def i16(self): return self._unpack("<h")
    def u32(self): return self._unpack("<I")
    def i32(self): return self._unpack("<i")

    def fixed(self, n: int) -> str:
        s = self.d[self.p:self.p + n]
        self.p += n
        return s.replace(b"\0", b"").decode("latin-1")

    def str(self) -> str:
        end = self.d.find(b"\0", self.p)
        if end < 0:
            end = len(self.d)
        raw = self.d[self.p:end]
        self.p = end + 1
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                return raw.decode(enc).strip()
            except UnicodeDecodeError:
                continue
        return ""


@dataclass
class Event:
    number: int
    distance_km: float    # απόσταση από το OTDR
    slope: float          # dB/km του τμήματος ίνας πριν από το συμβάν
    splice_loss: float    # dB
    reflectance: float    # dB
    code: str
    comment: str = ""
    # Υπολογίζονται από το SorFile.apply_launch()
    rel_km: float = 0.0               # απόσταση από την αρχή της ίνας (μετά το launch cable)
    section_km: float = 0.0           # μήκος τμήματος πριν από το συμβάν
    segment_loss: float = 0.0         # απώλεια τμήματος πριν από το συμβάν
    segment_cum: float | None = None  # αθροιστική απώλεια στο τέλος του τμήματος
    cumulative_loss: float | None = None  # αθροιστική απώλεια μετά το συμβάν (None μέσα στο launch)
    role: str = "event"               # origin | launch | start | event | end

    @property
    def reflective(self) -> bool:
        return self.code[:1] in ("1", "2")

    @property
    def is_end(self) -> bool:
        return self.code[1:2] == "E"

    @property
    def type_name(self) -> str:
        if self.role == "launch":
            return "Launch"
        if self.role in ("origin", "start"):
            return "Αρχή"
        if self.role == "end":
            return "Τέλος"
        return "Ανακλαστικό" if self.reflective else "Μη ανακλ."


@dataclass
class SorFile:
    path: Path | None
    version: float
    wavelength: int
    ior: float
    pulse_width_ns: int
    range_km: float
    averages: int
    date: datetime | None
    resolution_km: float
    trace: np.ndarray            # dB, όπως στο όργανο: 0 = θόρυβος, μεγαλύτερο = περισσότερο σήμα
    events: list[Event] = field(default_factory=list)
    file_total_loss: float | None = None
    end_km: float = 0.0          # θέση τέλους ίνας από το OTDR
    orl: float | None = None
    user_offset_km: float = 0.0  # launch cable όπως το έγραψε το όργανο (GenParams user offset)
    launch_km: float = 0.0       # launch cable που εφαρμόζεται τώρα
    cable_id: str = ""
    fiber_id: str = ""
    location_a: str = ""
    location_b: str = ""
    operator: str = ""
    comments: str = ""
    supplier: str = ""
    otdr_model: str = ""
    otdr_sn: str = ""
    software: str = ""

    def __post_init__(self):
        self.apply_launch(0.0)

    def apply_launch(self, km: float) -> None:
        """Ορίζει το launch cable και ξαναϋπολογίζει αποστάσεις και αθροιστικές απώλειες.

        Όπως στο όργανο: το συμβάν στο τέλος του launch cable γίνεται η αρχή (S) στο 0,
        οι αποστάσεις μετρούν από εκεί και η απώλεια του connector (S) μετράει στο σύνολο.
        """
        ev = self.events
        launch = 0.0
        start = 0
        if km and km > 0 and len(ev) > 1:
            tol = max(0.005, 5 * self.resolution_km)
            idx = min(range(1, len(ev)), key=lambda i: abs(ev[i].distance_km - km))
            if abs(ev[idx].distance_km - km) <= tol and not ev[idx].is_end:
                launch, start = ev[idx].distance_km, idx
            else:
                launch, start = km, -1
        self.launch_km = launch
        cum = 0.0
        prev = 0.0
        eps = 1e-9
        for i, e in enumerate(ev):
            e.section_km = e.distance_km - prev if i else 0.0
            e.segment_loss = e.slope * e.section_km if i else 0.0
            overlap = max(0.0, e.distance_km - max(prev, launch)) if i else 0.0
            cum += e.slope * overlap
            e.segment_cum = cum if i and e.distance_km > launch + eps else None
            e.rel_km = e.distance_km - launch
            if e.is_end and i:
                e.role = "end"
            elif i == start:
                e.role = "start" if launch else "origin"
            elif e.distance_km < launch - eps:
                e.role = "launch"
            else:
                e.role = "event"
            if e.distance_km >= launch - eps:
                if e.role != "end":
                    cum += e.splice_loss
                e.cumulative_loss = cum
            else:
                e.cumulative_loss = None
            prev = e.distance_km
        self._computed_total = cum

    @property
    def length_km(self) -> float:
        return max(0.0, self.end_km - self.launch_km)

    @property
    def total_loss(self) -> float | None:
        if not self.events:
            return self.file_total_loss
        if self.launch_km or not self.file_total_loss:
            return self._computed_total
        return self.file_total_loss

    @property
    def distance_axis(self) -> np.ndarray:
        return np.arange(len(self.trace), dtype=np.float64) * self.resolution_km - self.launch_km

    @property
    def attenuation(self) -> float | None:
        """Μέση εξασθένηση ίνας (dB/km) μετά το launch cable, σταθμισμένη με το μήκος.

        Δεν περιλαμβάνει απώλειες connectors/κολλήσεων, όπως και στο OTDR.
        """
        num = den = 0.0
        prev = 0.0
        for e in self.events:
            overlap = max(0.0, e.distance_km - max(prev, self.launch_km))
            if e.slope > 0 and overlap > 0:
                num += e.slope * overlap
                den += overlap
            prev = e.distance_km
        if den:
            return num / den
        total = self.total_loss
        if total is None or not self.length_km:
            return None
        return total / self.length_km


def _read_map(r: _Reader):
    v2 = r.d[:4] == b"Map\0"
    start = r.p
    if v2:
        r.p += 4
    version = r.u16() / 100
    map_bytes = r.u32()
    n_blocks = r.u16()
    blocks = {}
    offset = start + map_bytes
    for _ in range(n_blocks - 1):
        name = r.str()
        r.u16()  # έκδοση block
        size = r.u32()
        blocks.setdefault(name, (offset, size))
        offset += size
    return v2, version, blocks


def parse_sor_bytes(data: bytes, path: Path | None = None, with_trace: bool = True) -> SorFile:
    r = _Reader(data)
    try:
        v2, version, blocks = _read_map(r)
    except (SorError, struct.error) as e:
        raise SorError(f"Μη έγκυρη κεφαλίδα SOR: {e}") from None
    if "FxdParams" not in blocks:
        raise SorError("Λείπει το block FxdParams – δεν είναι αρχείο SOR")
    # Έλεγχος δομής: το FHO5000 γράφει checksum 0, οπότε ένα αλλοιωμένο αρχείο
    # εντοπίζεται μόνο από ασυνέπειες στη δομή του. Ποτέ αποτέλεσμα από χαλασμένο αρχείο.
    for name in ("GenParams", "SupParams", "FxdParams", "KeyEvents", "DataPts"):
        if name in blocks:
            off, size = blocks[name]
            if off + size > len(data):
                raise SorError(f"Κατεστραμμένο αρχείο: το τμήμα {name} ξεπερνά το τέλος του αρχείου")

    def block(name):
        off, _ = blocks[name]
        br = _Reader(data, off)
        if v2:
            found = br.str()
            if found != name:
                raise SorError(f"Κατεστραμμένο αρχείο: αναμενόταν το τμήμα {name}, βρέθηκε {found[:20]!r}")
        return br

    gen = {}
    user_offset = 0
    if "GenParams" in blocks:
        g = block("GenParams")
        g.fixed(2)
        gen["cable_id"] = g.str()
        gen["fiber_id"] = g.str()
        if v2:
            g.u16()
        gen["wavelength"] = g.u16()
        gen["location_a"] = g.str()
        gen["location_b"] = g.str()
        g.str()
        g.fixed(2)
        user_offset = g.i32()            # χρόνος σε 0,1 ns (το FHO5000 γράφει εδώ το launch cable)
        if v2:
            g.i32()
        gen["operator"] = g.str()
        gen["comments"] = g.str()

    sup = {}
    if "SupParams" in blocks:
        s = block("SupParams")
        sup["supplier"] = s.str()
        sup["otdr_model"] = s.str()
        sup["otdr_sn"] = s.str()
        s.str(); s.str()
        sup["software"] = s.str()

    f = block("FxdParams")
    ts = f.u32()
    f.fixed(2)
    wl = f.u16() / 10
    acq_offset = f.i32()
    if v2:
        f.i32()
    n_pw = f.u16()
    pulses = [f.u16() for _ in range(n_pw)]
    spacing = [f.u32() for _ in range(n_pw)]
    [f.u32() for _ in range(n_pw)]
    ior = f.u32() / 100000 or 1.4682
    f.u16()
    averages = f.u32()
    if v2:
        f.u16()
    acq_range = f.u32()

    km_per_tof = 1e-10 * C_KM_PER_S / ior
    resolution = (spacing[0] if spacing else 0) * 1e-14 * C_KM_PER_S / ior

    events: list[Event] = []
    total_loss = orl = None
    length = 0.0
    if "KeyEvents" in blocks:
        k_off, k_size = blocks["KeyEvents"]
        k_end = k_off + k_size
        k = block("KeyEvents")
        n = k.u16()
        prev_tof = 0
        for _ in range(n):
            num = k.u16()
            tof = k.u32()
            slope = k.i16() / 1000
            loss = k.i16() / 1000
            refl = k.i32() / 1000
            code = k.fixed(8)
            if v2:
                for _ in range(5):
                    k.u32()
            comment = k.str()
            if len(code) < 2 or code[0] not in "012" or not code[1].isalpha():
                raise SorError(f"Κατεστραμμένο αρχείο: μη έγκυρος κωδικός συμβάντος {code!r}")
            if tof < prev_tof:
                raise SorError("Κατεστραμμένο αρχείο: τα συμβάντα δεν είναι σε σειρά απόστασης")
            prev_tof = tof
            events.append(Event(num, tof * km_per_tof, slope, loss, refl, code, comment))
        summary_size = 22   # συνολική απώλεια, αρχή, μήκος, ORL, αρχή/τέλος ORL
        if k_end - k.p >= summary_size:
            total_loss = k.i32() / 1000
            k.i32()
            length = k.u32() * km_per_tof
            orl = k.u16() / 1000
            k.i32(); k.u32()
        # Το πλήθος συμβάντων πρέπει να γεμίζει ακριβώς το τμήμα: αλλιώς το πλήθος έχει αλλοιωθεί
        # (π.χ. λιγότερα συμβάντα → θα χανόταν ένα FAIL).
        min_event = 42 if v2 else 22
        if k.p > k_end or k_end - k.p >= min_event:
            raise SorError("Κατεστραμμένο αρχείο: το πλήθος συμβάντων δεν ταιριάζει με το μέγεθος του τμήματος")

    if not length:
        ends = [e for e in events if e.is_end]
        length = ends[0].distance_km if ends else (events[-1].distance_km if events else 0.0)

    trace = np.zeros(0, dtype=np.float32)
    if with_trace and "DataPts" in blocks:
        d = block("DataPts")
        d.u32()
        d.u16()
        npts = d.u32()
        scale = d.u16() / 1000
        end = d.p + npts * 2
        if end > len(data):
            npts = (len(data) - d.p) // 2
        raw = np.frombuffer(data, dtype="<u2", count=npts, offset=d.p)
        # Όπως το δείχνει το όργανο: 0 dB = κάτω όριο, όσο πιο ψηλά τόσο περισσότερο σήμα
        trace = ((65535 - raw.astype(np.float32)) * scale / 1000).astype(np.float32)

    date = None
    if ts:
        try:
            date = datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            date = None

    return SorFile(
        path=path,
        version=version,
        wavelength=int(round(wl or gen.get("wavelength", 0))),
        ior=ior,
        pulse_width_ns=pulses[0] if pulses else 0,
        range_km=acq_range * km_per_tof if acq_range else 0.0,
        averages=averages,
        date=date,
        resolution_km=resolution,
        trace=trace,
        events=events,
        file_total_loss=total_loss,
        end_km=length,
        orl=orl,
        user_offset_km=max(0, user_offset) * km_per_tof,
        **gen_filter(gen),
        **sup,
    )


def gen_filter(gen: dict) -> dict:
    return {k: v for k, v in gen.items() if k != "wavelength"}


def parse_sor(path: str | Path, with_trace: bool = True) -> SorFile:
    p = Path(path)
    return parse_sor_bytes(p.read_bytes(), p, with_trace=with_trace)


def downsample(sor: SorFile, buckets: int = 1000, max_km: float | None = None):
    """Μειώνει την καμπύλη σε ζεύγη min/max ώστε να φαίνονται οι κορυφές.

    Επιστρέφει (x_km, y_dB) ως numpy arrays, με x από την αρχή της ίνας
    (αρνητικό μέσα στο launch cable). Το max_km μετράει επίσης από την αρχή της ίνας.
    """
    y = sor.trace
    n = len(y)
    if max_km is not None and sor.resolution_km > 0:
        n = min(n, int(np.ceil((max_km + sor.launch_km) / sor.resolution_km)) + 1)
    y = y[:n]
    x = np.arange(n) * sor.resolution_km - sor.launch_km
    if n <= buckets * 2:
        return x, y
    edges = np.linspace(0, n, buckets + 1).astype(int)
    xs, ys = [], []
    for s, e in zip(edges[:-1], edges[1:]):
        seg = y[s:e]
        i_min = s + int(np.argmin(seg))
        i_max = s + int(np.argmax(seg))
        for i in sorted((i_min, i_max)):
            xs.append(x[i])
            ys.append(y[i])
    return np.asarray(xs), np.asarray(ys)
