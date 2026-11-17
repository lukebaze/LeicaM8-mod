#!/usr/bin/env python3
"""Patch colour matrices and tone curves in LUTS/GAMMA of Leica M8 firmware 2.014.

GAMMA layout (README): +0x1D0 30 matrices, 3x3 int16 Q13 (8192 = 1.0), index = 10*space + 2*saturation
+ variant, space 1 = sRGB; +0x410 15 curves x 2048 u8, curve = 5*space + contrast, input linear
0..2047 = black..white. Camera JPG = curve(matrix . camera RGB after white balance).

  python3 tools/m8lut.py dump                    # print all 30 matrices
  python3 tools/m8lut.py bw-test                 # #14+#15 -> monochrome (does the Blackfin use them?)
  python3 tools/m8lut.py look Kodak_Portra_160_2 [--out NAME]
      # sRGB colour space: 10 matrices + 5 curves from research/fits (see build_look)
"""
import hashlib, os, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK = os.path.join(ROOT, 'firmware', 'stock', 'm8-2_014.upd')
STOCK_SHA = '99f5254847a92c68086f37b1a4140c359379801b479df12052136abb73f09ed0'
MAT_OFF, N_MAT, CURVE_OFF, CURVE_LEN = 0x1D0, 30, 0x410, 2048
SRGB_MATS, SRGB_CURVES = range(10, 20), range(5, 10)
MID_GREY = 0.18


def wad(b, base=0):
    """PWAD directory -> {name: (absolute offset, size)}."""
    n, off = struct.unpack_from('<II', b, base + 4)
    out = {}
    for i in range(n):
        o, s = struct.unpack_from('<II', b, base + off + 16 * i)
        name = b[base + off + 16 * i + 8: base + off + 16 * i + 16].split(b'\0')[0].decode('latin1')
        out[name] = (base + o, s)
    return out


def load(path=STOCK, check=True):
    """-> (file bytes, absolute offset of GAMMA)."""
    d = open(path, 'rb').read()
    if check and hashlib.sha256(d).hexdigest() != STOCK_SHA:
        sys.exit('not the stock m8-2_014.upd (SHA-256 mismatch)')
    luts, _ = wad(d)['LUTS']
    gamma, size = wad(d, luts)['GAMMA']
    assert size == 31760 and struct.unpack_from('<I', d, gamma + 4)[0] == CURVE_OFF, 'unexpected GAMMA layout'
    return bytearray(d), gamma


def matrix(d, g, i):
    return [[v / 8192 for v in struct.unpack_from('<9h', d, g + MAT_OFF + 18 * i)[r:r + 3]] for r in (0, 3, 6)]


def curve(d, g, k):
    return list(d[g + CURVE_OFF + CURVE_LEN * k: g + CURVE_OFF + CURVE_LEN * (k + 1)])


def q13(rows):
    """Round to Q13 keeping each row's sum exact (a row summing to 1.0 stays 8192: white stays white)."""
    out = []
    for r in rows:
        v = [round(x * 8192) for x in r]
        v[1] += round(sum(r) * 8192) - sum(v)
        assert all(-32768 <= x <= 32767 for x in v), f'coefficient out of Q13 range: {r}'
        out += v
    return struct.pack('<9h', *out)


def write(d, patches, name):
    """patches: {absolute offset: bytes}. Refuses any change outside them."""
    stock = open(STOCK, 'rb').read()
    for o, b in patches.items():
        d[o:o + len(b)] = b
    spans = [(o, o + len(b)) for o, b in patches.items()]
    changed = [i for i in range(len(d)) if d[i] != stock[i]]
    assert len(d) == len(stock) and all(any(lo <= i < hi for lo, hi in spans) for i in changed), \
        'bytes changed outside the patched regions'
    os.makedirs(os.path.join(ROOT, 'build'), exist_ok=True)
    out = os.path.join(ROOT, 'build', name)
    if os.path.exists(out):
        sys.exit(f'{out} exists, not overwriting')
    open(out, 'wb').write(d)
    print(f'{out}\n  {len(changed)} bytes changed, all inside GAMMA\n  SHA-256 {hashlib.sha256(d).hexdigest()}')
    print('  on the card rename it to M8-2_014.UPD; roll back by flashing the stock file')
    return out


def build_look(d, g, fit):
    """Look on the sRGB colour space: matrix_i' = M_look . matrix_i, Contrast steps kept as Leica's maps
    (standard value -> value at step c). Curve, made for the CCD:
      - tone from the film's grey axis (the shared curve that puts each channel of a neutral where the
        CLUT does), so blacks and shadows follow the film, not a fit dominated by saturated colours;
      - mid-grey at Leica's 147, the level the M8's metering is made for;
      - shoulder: above mid-grey the exposure gain rolls off (linear in log2) to 1.0 at sensor clip, so
        the curve reaches 255 only where the CCD clips: no highlight range the sensor kept is thrown away."""
    import numpy as np
    M = fit['M']
    rs = M.sum(1)
    u = np.concatenate([fit['neutral_in'] * r for r in rs]); y = fit['neutral_out'].T.ravel()
    o = np.argsort(u); u, y = u[o], np.maximum.accumulate(y[o])
    look = lambda v: np.interp(np.clip(v, 0, 1), u, y) / y[-1]                 # 0..1 -> 0..1
    stock = {k: np.array(curve(d, g, k), float) for k in SRGB_CURVES}
    x = np.arange(CURVE_LEN) / (CURVE_LEN - 1)
    target = np.interp(MID_GREY, x, stock[7]) / 255
    ks = np.linspace(0.5, 4, 3501)
    gain = ks[np.argmin(np.abs(look(ks * MID_GREY * rs[1]) - target))]
    lx = np.log2(np.maximum(x, 1e-9)); lm = np.log2(MID_GREY)
    xin = np.where(x <= MID_GREY, gain * x, 2 ** (lx + np.log2(gain) * lx / lm))
    std = np.maximum.accumulate(np.round(255 * look(xin)).clip(0, 255))
    patches = {}
    s7 = stock[7] + x * 1e-6                                                 # strictly increasing for inversion
    for k in SRGB_CURVES:
        new = std if k == 7 else np.round(np.interp(np.interp(std, s7, x), x, stock[k]))
        patches[g + CURVE_OFF + CURVE_LEN * k] = bytes(np.maximum.accumulate(new).astype(np.uint8))
    for i in SRGB_MATS:
        patches[g + MAT_OFF + 18 * i] = q13((M @ np.array(matrix(d, g, i))).tolist())
    return patches, gain


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else 'dump'
    d, g = load()
    if cmd == 'dump':
        for i in range(N_MAT):
            print(f'{i:2d} file 0x{g + MAT_OFF + 18 * i:05X}', ' | '.join(' '.join(f'{v:6.3f}' for v in r) for r in matrix(d, g, i)))
    elif cmd == 'bw-test':
        write(d, {g + MAT_OFF + 18 * s: q13([[0.299, 0.587, 0.114]] * 3) for s in (14, 15)}, 'm8-2_014-bwtest.upd')
    elif cmd == 'look' and len(a) > 1:
        import numpy as np
        name = a[a.index('--out') + 1] if '--out' in a else f'm8-2_014-{a[1].lower()}.upd'
        patches, gain = build_look(d, g, np.load(os.path.join(ROOT, 'research', 'fits', f'fit_{a[1]}.npz')))
        print(f'exposure gain {gain:.3f} ({np.log2(gain):+.2f} EV) below mid-grey to match Leica mid-grey')
        write(d, patches, name)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
