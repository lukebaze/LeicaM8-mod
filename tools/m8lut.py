#!/usr/bin/env python3
"""Patch the colour matrices in LUTS/GAMMA of Leica M8 firmware 2.014.

GAMMA+0x1D0: 30 matrices, 3x3 int16 Q13 (8192 = 1.0), rows sum to 1.0 (docs/FINDINGS.md).
Index = 10*space + 2*saturation + variant; space 1 = sRGB, saturation 2 = Standard -> 14/15.

  python3 tools/m8lut.py bw-test            # slots 14+15 -> monochrome (does the Blackfin use them?)
  python3 tools/m8lut.py dump               # print all 30 matrices
"""
import hashlib, os, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK = os.path.join(ROOT, 'firmware', 'stock', 'm8-2_014.upd')
STOCK_SHA = '99f5254847a92c68086f37b1a4140c359379801b479df12052136abb73f09ed0'
MAT_OFF, N_MAT = 0x1D0, 30


def wad(b, base=0):
    """PWAD directory -> {name: (absolute offset, size)}."""
    n, off = struct.unpack_from('<II', b, base + 4)
    out = {}
    for i in range(n):
        o, s = struct.unpack_from('<II', b, base + off + 16 * i)
        name = b[base + off + 16 * i + 8: base + off + 16 * i + 16].split(b'\0')[0].decode('latin1')
        out[name] = (base + o, s)
    return out


def load():
    d = open(STOCK, 'rb').read()
    if hashlib.sha256(d).hexdigest() != STOCK_SHA:
        sys.exit('not the stock m8-2_014.upd (SHA-256 mismatch)')
    luts, _ = wad(d)['LUTS']
    gamma, size = wad(d, luts)['GAMMA']
    assert size == 31760, size
    return bytearray(d), gamma + MAT_OFF


def q13(rows):
    vals = [round(x * 8192) for r in rows for x in r]
    for i in range(3):  # keep each row summing to exactly 8192 (white stays white)
        vals[3 * i + 1] += 8192 - sum(vals[3 * i: 3 * i + 3])
    return struct.pack('<9h', *vals)


def write(d, base, slots, rows, name):
    stock = open(STOCK, 'rb').read()
    for s in slots:
        d[base + 18 * s: base + 18 * s + 18] = q13(rows)
    changed = [i for i in range(len(d)) if d[i] != stock[i]]
    lo, hi = base + 18 * min(slots), base + 18 * max(slots) + 18
    assert len(d) == len(stock) and all(lo <= i < hi for i in changed), 'bytes changed outside the matrix slots'
    os.makedirs(os.path.join(ROOT, 'build'), exist_ok=True)
    out = os.path.join(ROOT, 'build', name)
    if os.path.exists(out):
        sys.exit(f'{out} exists, not overwriting')
    open(out, 'wb').write(d)
    print(f'{out}\n  {len(changed)} bytes changed in file 0x{lo:X}-0x{hi - 1:X}\n  SHA-256 {hashlib.sha256(d).hexdigest()}')
    print('  on the card rename it to M8-2_014.UPD; roll back by flashing the stock file')


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'dump'
    d, base = load()
    if cmd == 'dump':
        for i in range(N_MAT):
            m = struct.unpack_from('<9h', d, base + 18 * i)
            print(f'{i:2d} file 0x{base + 18 * i:05X}', ' | '.join(' '.join(f'{v / 8192:6.3f}' for v in m[r:r + 3]) for r in (0, 3, 6)))
    elif cmd == 'bw-test':
        write(d, base, [14, 15], [[0.299, 0.587, 0.114]] * 3, 'm8-2_014-bwtest.upd')
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
