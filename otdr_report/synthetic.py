"""Δημιουργεί συνθετικά αρχεία .sor (SR-4731 v2) για δοκιμές.

    python -m otdr_report.synthetic <φάκελος> [--cable FARM1.R01_SCP31] [--fibers 300]
"""
from __future__ import annotations

import argparse
import random
import struct
import time
from pathlib import Path

C = 299792.458


def _s(text: str) -> bytes:
    return text.encode("latin-1") + b"\0"


def build_sor(wavelength: int, length_km: float, events: list[tuple[float, float, float]],
              ior: float = 1.4682, seed: int = 0, cable: str = "", fiber: str = "") -> bytes:
    """events: (km, loss dB, reflectance dB ή 0 για μη ανακλαστικό)."""
    rnd = random.Random(seed)
    att = 0.33 if wavelength < 1400 else 0.19
    res_km = 0.002 if length_km < 20 else 0.008
    n = int(length_km * 1.3 / res_km)
    spacing = round(res_km / (1e-14 * C / ior))
    km_per_tof = 1e-10 * C / ior

    # Καμπύλη σε dB (θετικές τιμές = απώλεια), με θόρυβο μετά το τέλος
    y = []
    level = 3.0
    ev = sorted(events)
    j = 0
    for i in range(n):
        x = i * res_km
        while j < len(ev) and x >= ev[j][0]:
            level += ev[j][1]
            j += 1
        if x > length_km:
            v = 28 + rnd.random() * 3
        else:
            v = level + att * x + rnd.gauss(0, 0.01 + x / length_km * 0.02)
        for (ex, _l, refl) in ev + [(length_km, 0, -14)]:
            if refl and 0 <= x - ex < res_km * 3:
                v -= 8
        y.append(max(0, min(65.0, v)))

    gen = b"GenParams\0" + b"EN" + _s(cable) + _s(fiber) + struct.pack("<HH", 652, wavelength)
    gen += _s("A") + _s("B") + _s("") + b"BC" + struct.pack("<ii", 0, 0) + _s("tester") + _s("")
    sup = b"SupParams\0" + b"".join(_s(x) for x in ("Grandway", "FHO5000", "SN123", "", "", "2.2.8", ""))
    fxd = b"FxdParams\0" + struct.pack("<I", int(time.time())) + b"km" + struct.pack("<H", wavelength * 10)
    fxd += struct.pack("<ii", 0, 0) + struct.pack("<H", 1) + struct.pack("<H", 100)
    fxd += struct.pack("<I", spacing) + struct.pack("<I", n) + struct.pack("<I", int(ior * 100000))
    fxd += struct.pack("<H", 800) + struct.pack("<I", 1000) + struct.pack("<H", 15)
    fxd += struct.pack("<I", int(length_km * 1.3 / km_per_tof)) + struct.pack("<i", 0)
    fxd += struct.pack("<i", 0) + struct.pack("<Hh", 0, 1000) + struct.pack("<H", 0)
    fxd += struct.pack("<HHH", 50, 65000, 3000) + b"ST" + struct.pack("<4i", 0, 0, 0, 0)

    all_ev = [(0.0, 0.0, -45.0, "1S9999LS")]
    all_ev += [(km, loss, refl, ("1F" if refl else "0F") + "9999LS") for km, loss, refl in ev]
    all_ev += [(length_km, 0.0, -14.0, "1E9999LS")]
    kev = b"KeyEvents\0" + struct.pack("<H", len(all_ev))
    prev = 0.0
    total = 0.0
    for i, (km, loss, refl, code) in enumerate(all_ev):
        slope = att if i else 0.0
        kev += struct.pack("<HIhhi", i + 1, int(km / km_per_tof), int(slope * 1000),
                           int(loss * 1000), int(refl * 1000))
        kev += code.encode() + struct.pack("<5I", 0, 0, 0, 0, 0) + _s("")
        total += loss + slope * (km - prev)
        prev = km
    kev += struct.pack("<iiIHiI", int(total * 1000), 0, int(length_km / km_per_tof), 32000, 0, 0)

    dat = b"DataPts\0" + struct.pack("<IHIH", n, 1, n, 1000)
    dat += struct.pack(f"<{n}H", *(int(v * 1000) for v in y))
    ck = b"Cksum\0" + struct.pack("<H", 0)

    blocks = [("GenParams", gen), ("SupParams", sup), ("FxdParams", fxd),
              ("KeyEvents", kev), ("DataPts", dat), ("Cksum", ck)]
    body = b"".join(_s(name) + struct.pack("<HI", 200, len(data))
                    for name, data in blocks)
    map_len = 4 + 2 + 4 + 2 + len(body)
    head = b"Map\0" + struct.pack("<HIH", 200, map_len, len(blocks) + 1) + body
    return head + b"".join(d for _, d in blocks)


def make_cable(folder: Path, cable: str, fibers: int, wavelengths=(1310, 1550),
               skip: set[int] = frozenset(), seed: int = 1) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(seed)
    length = round(rnd.uniform(1.5, 6.0), 3)
    out = []
    for f in range(1, fibers + 1):
        evs = [(round(length * k / 4 + rnd.uniform(-0.05, 0.05), 3), round(rnd.uniform(0.02, 0.25), 3), 0)
               for k in (1, 2, 3)]
        evs.insert(0, (0.25, round(rnd.uniform(0.2, 0.5), 3), -48.0))  # connector
        if f % 37 == 0:
            evs[2] = (evs[2][0], 0.55, 0)  # κακή κόλληση → FAIL
        for wl in wavelengths:
            if (f, wl) in skip:
                continue
            scale = 1.0 if wl < 1400 else 1.15
            data = build_sor(wl, length, [(km, round(l * scale, 3), r) for km, l, r in evs],
                             seed=f * 10 + wl, cable=cable, fiber=f"{f:04d}")
            p = folder / f"{cable}_{wl}_{f:04d}.sor"
            p.write_bytes(data)
            out.append(p)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--cable", default="FARM1.R01_SCP31")
    ap.add_argument("--fibers", type=int, default=300)
    a = ap.parse_args()
    files = make_cable(a.folder, a.cable, a.fibers)
    print(f"{len(files)} αρχεία στο {a.folder}")
