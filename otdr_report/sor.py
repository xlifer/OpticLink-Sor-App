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
    distance_km: float
    slope: float          # dB/km
    splice_loss: float    # dB
    reflectance: float    # dB
    code: str
    comment: str = ""
    cumulative_loss: float = 0.0
    section_km: float = 0.0

    @property
    def reflective(self) -> bool:
        return self.code[:1] in ("1", "2")

    @property
    def is_end(self) -> bool:
        return self.code[1:2] == "E"

    @property
    def type_name(self) -> str:
        if self.code[1:2] == "S" or (self.number <= 1 and self.distance_km < 1e-6):
            return "Αρχή"
        if self.is_end:
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
    trace: np.ndarray            # dB, ήδη αρνητικό πρόσημο (όσο πιο χαμηλά τόσο περισσότερη απώλεια)
    events: list[Event] = field(default_factory=list)
    total_loss: float | None = None
    length_km: float = 0.0
    orl: float | None = None
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

    @property
    def distance_axis(self) -> np.ndarray:
        return np.arange(len(self.trace), dtype=np.float64) * self.resolution_km

    @property
    def attenuation(self) -> float | None:
        """Μέση εξασθένηση ίνας (dB/km), σταθμισμένη με το μήκος κάθε τμήματος.

        Δεν περιλαμβάνει απώλειες connectors/κολλήσεων, όπως και στο OTDR.
        """
        num = den = 0.0
        for e in self.events[1:]:
            if e.slope > 0 and e.section_km > 0:
                num += e.slope * e.section_km
                den += e.section_km
        if den:
            return num / den
        if self.total_loss is None or not self.length_km:
            return None
        return self.total_loss / self.length_km


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

    def block(name):
        off, _ = blocks[name]
        br = _Reader(data, off)
        if v2:
            br.str()
        return br

    gen = {}
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
        g.i32()
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
        k = block("KeyEvents")
        n = k.u16()
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
            events.append(Event(num, tof * km_per_tof, slope, loss, refl, code, comment))
        try:
            total_loss = k.i32() / 1000
            k.i32()
            length = k.u32() * km_per_tof
            orl = k.u16() / 1000
        except SorError:
            pass

    if not length:
        ends = [e for e in events if e.is_end]
        length = ends[0].distance_km if ends else (events[-1].distance_km if events else 0.0)

    # Αθροιστική απώλεια και μήκος τμήματος για τον πίνακα συμβάντων (όπως στην παλιά λίστα)
    # Το slope ενός συμβάντος αφορά το τμήμα ίνας που προηγείται.
    cum = 0.0
    prev = 0.0
    for i, e in enumerate(events):
        e.section_km = e.distance_km - prev
        if i > 0:
            cum += events[i - 1].splice_loss + e.slope * e.section_km
        e.cumulative_loss = cum
        prev = e.distance_km
    if not total_loss and events:
        total_loss = events[-1].cumulative_loss

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
        trace = (-raw.astype(np.float32) * scale / 1000).astype(np.float32)

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
        total_loss=total_loss,
        length_km=length,
        orl=orl,
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

    Επιστρέφει (x_km, y_dB) ως numpy arrays.
    """
    y = sor.trace
    n = len(y)
    if max_km is not None and sor.resolution_km > 0:
        n = min(n, int(np.ceil(max_km / sor.resolution_km)) + 1)
    y = y[:n]
    x = np.arange(n) * sor.resolution_km
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
