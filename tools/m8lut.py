#!/usr/bin/env python3
"""Patch colour matrices and tone curves in LUTS/GAMMA of Leica M8 firmware 2.014.

GAMMA layout (README): +0x1D0 30 matrices, 3x3 int16 Q13 (8192 = 1.0), index = 10*space + 2*saturation
+ variant; +0x410 15 curves x 2048 u8, curve = 5*space + contrast, input linear 0..2047 = black..white.
Space 0 = Adobe RGB, 1 = sRGB, 2 = ECI RGB (the Colour space menu). JPG = curve(matrix . camera RGB).

  python3 tools/m8lut.py dump                     # print all 30 matrices
  python3 tools/m8lut.py bw-test [--all]          # monochrome matrices + darker control curve (see README Test 1)
  python3 tools/m8lut.py build [--base FILE] [--srgb LOOK] [--adobe LOOK] [--eci LOOK] [--bw SPACE] [--out NAME]
      LOOK = research/fits/fit_<LOOK>.npz, e.g. SFL_Portra_160_Endura. A space without a look keeps Leica's.
      --bw SPACE: that space's Saturation Low becomes black & white (Leica tone).
      --base: start from a gasdevmco/leica-m8-firmware 2.014 build (14-bit DNG, PXA only) instead of stock;
              accepted only if its SHA-256 is one of that project's published builds and GAMMA is stock.
  python3 tools/m8lut.py lut --from FLASHED.upd --name NAME [--srgb LOOK] ... [--bw-test]
      -> build/PROFILES/NAME.LUT for the picture-profile picker (base 4359b04b), see `lut` below.
"""
import hashlib, os, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK = os.path.join(ROOT, 'firmware', 'stock', 'm8-2_014.upd')
STOCK_SHA = '99f5254847a92c68086f37b1a4140c359379801b479df12052136abb73f09ed0'
BASES = {  # gasdevmco/leica-m8-firmware v0.10.0 m8patch.py builds (README "Builds"); all change PXA only
    '9b9a489a0decff5bc1a52ba8ff2b4574a608ae7a8fa1bc41fc6bfa9a49c02c04': '14-bit DNG',
    '624448c6190de500028e4c583993cf9047c791504e5f9bc4c45a31b79af42af8': '14-bit DNG + INFO',
    '89fbcc00674f69524b9460fa0e47659c4ff5f422767d3f9d1f4dff3436368f21': '14-bit DNG + dial EV/ISO',
    '4cefacf137a8013c69d0400a1393d3667f369fdfa4e601ecb38dd3a55286376b': '14-bit DNG + INFO + dial EV/ISO',
    # v0.7.0 `m8_dngpatch.py dng --meta --profiles --dial-ev`: withdrawn from m8patch.py, but flashed and
    # camera-tested as this exact file (2026-11-05) and the author's fallback build. Dial = EV only.
    '4359b04b41dd81761730e79fde3b46a09044e908c55cdc56cd8d8add3288e905': '14-bit DNG + picture-profile picker + dial EV (amber, no ISO)',
    # `m8_dngpatch.py dng --meta --profiles --dial-ev --iso`: never published or flashed as a file; made of
    # camera-tested pieces (picker as in 4359b04b, dial EV+ISO amber as in 796ecbc6), regions disjoint
    'cf965505725f1f82077772bcd09d23c517d0293cfdd64290cae2e4da003986b1': '14-bit DNG + picture-profile picker + dial EV/ISO (amber; pieces)',
}
MAT_OFF, N_MAT, CURVE_OFF, CURVE_LEN = 0x1D0, 30, 0x410, 2048
SPACES = {'adobe': 0, 'srgb': 1, 'eci': 2}
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
    """-> (file bytes, absolute offset of GAMMA). check: stock, or a known DNG base with stock GAMMA."""
    d = open(path, 'rb').read()
    luts, _ = wad(d)['LUTS']
    gamma, size = wad(d, luts)['GAMMA']
    assert size == 31760 and struct.unpack_from('<I', d, gamma + 4)[0] == CURVE_OFF, 'unexpected GAMMA layout'
    if check:
        sha = hashlib.sha256(d).hexdigest()
        if sha != STOCK_SHA and sha not in BASES:
            sys.exit(f'{path}: neither stock m8-2_014.upd nor a known 14-bit DNG build (SHA-256 {sha})')
        if sha != STOCK_SHA:
            s, sg = load(STOCK)
            assert sg == gamma and s[gamma:gamma + size] == d[gamma:gamma + size], 'base GAMMA is not stock'
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


def write(d, patches, name, base):
    """patches: {absolute offset: bytes}. Refuses any change from `base` outside them."""
    ref = open(base, 'rb').read()
    for o, b in patches.items():
        d[o:o + len(b)] = b
    spans = [(o, o + len(b)) for o, b in patches.items()]
    changed = [i for i in range(len(d)) if d[i] != ref[i]]
    assert len(d) == len(ref) and all(any(lo <= i < hi for lo, hi in spans) for i in changed), \
        'bytes changed outside the patched regions'
    os.makedirs(os.path.join(ROOT, 'build'), exist_ok=True)
    out = os.path.join(ROOT, 'build', name)
    if os.path.exists(out):
        sys.exit(f'{out} exists, not overwriting')
    open(out, 'wb').write(d)
    pxa_o, pxa_n = wad(ref)['PXA']
    in_pxa = sum(pxa_o <= i < pxa_o + pxa_n for i in changed)
    print(f'{out}\n  {len(changed)} bytes changed from {os.path.basename(base)}: {len(changed) - in_pxa} in GAMMA, {in_pxa} in PXA'
          f'\n  SHA-256 {hashlib.sha256(d).hexdigest()}')
    print('  on the card rename it to M8-2_014.UPD; roll back by flashing the stock file')
    return out


def space_tools(space):
    """(T, encode) for a colour space: T = linear sRGB (D65) -> that space's linear RGB (Bradford to D50
    for ECI), encode = its transfer function. Leica's own curve rows follow these encodings (FINDINGS)."""
    import numpy as np
    xyz = lambda p: np.array([p[0] / p[1], 1, (1 - p[0] - p[1]) / p[1]])
    def to_xyz(prims, white):
        P = np.stack([xyz(p) for p in prims], 1)
        return P * np.linalg.solve(P, xyz(white))
    D50, D65 = (0.3457, 0.3585), (0.3127, 0.3290)
    srgb = to_xyz([(0.64, 0.33), (0.30, 0.60), (0.15, 0.06)], D65)
    if space == 1:
        return np.eye(3), lambda v: np.where(v <= 0.0031308, 12.92 * v, 1.055 * np.maximum(v, 0) ** (1 / 2.4) - 0.055)
    if space == 0:
        return np.linalg.inv(to_xyz([(0.64, 0.33), (0.21, 0.71), (0.15, 0.06)], D65)) @ srgb, lambda v: np.maximum(v, 0) ** (256 / 563)
    bradford = np.array([[1.0478112, 0.0228866, -0.0501270], [0.0295424, 0.9904844, -0.0170491],
                         [-0.0092345, 0.0150436, 0.7521316]])
    return np.linalg.inv(to_xyz([(0.67, 0.33), (0.21, 0.71), (0.14, 0.08)], D50)) @ bradford @ srgb, lambda v: np.maximum(v, 0) ** (1 / 1.8)


def build_look(d, g, fit, space=1):
    """Look for one colour space. The look is defined in linear sRGB, so it is applied there on top of the
    space's own Leica rendering: matrix_i' = T . M_look . T^-1 . matrix_i (T = I for sRGB). Contrast steps
    kept as Leica's maps (standard value -> value at step c). Curve, made for the CCD:
      - tone from the film's grey axis (channel mean), black-point compensated as in ICC perceptual
        rendering (film/paper Dmax -> 0, paper white -> 255);
      - mid-grey at Leica's 147, the level the M8's metering is made for;
      - shoulder: above mid-grey the exposure gain rolls off (linear in log2) to 1.0 at sensor clip, so
        the curve reaches 255 only where the CCD clips: no highlight range the sensor kept is thrown away;
      - built as an sRGB curve, then re-encoded for the space (Leica's rows are the same tone encoded 3 ways).
    Matrix rows sum to 1, as in all 30 Leica matrices: greys stay grey (the camera's AWB keeps working) and
    a clipped CCD highlight stays neutral. The unconstrained fit tints every grey to average out the film's
    shadow/highlight crossover, which a single shared curve cannot reproduce anyway."""
    import numpy as np
    M = fit['M_white']
    u = fit['neutral_in']; y = np.maximum.accumulate(fit['neutral_out'].mean(1))
    look = lambda v: (np.interp(np.clip(v, 0, 1), u, y) - y[0]) / (y[-1] - y[0])   # 0..1 -> 0..1
    stock = {k: np.array(curve(d, g, k), float) for k in range(5, 10)}             # Leica's sRGB row
    x = np.arange(CURVE_LEN) / (CURVE_LEN - 1)
    target = np.interp(MID_GREY, x, stock[7]) / 255
    ks = np.linspace(0.5, 4, 3501)
    gain = ks[np.argmin(np.abs(look(ks * MID_GREY) - target))]
    lx = np.log2(np.maximum(x, 1e-9)); lm = np.log2(MID_GREY)
    xin = np.where(x <= MID_GREY, gain * x, 2 ** (lx + np.log2(gain) * lx / lm))
    std = np.maximum.accumulate(np.round(255 * look(xin)).clip(0, 255))
    T, enc = space_tools(space)
    dec_srgb = lambda v: np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    patches = {}
    s7 = stock[7] + x * 1e-6                                                 # strictly increasing for inversion
    for c in range(5):
        new = std if c == 2 else np.round(np.interp(np.interp(std, s7, x), x, stock[5 + c]))
        if space != 1:
            new = np.round(255 * enc(dec_srgb(new / 255)))
        patches[g + CURVE_OFF + CURVE_LEN * (5 * space + c)] = bytes(np.maximum.accumulate(new).clip(0, 255).astype(np.uint8))
    Ms = T @ M @ np.linalg.inv(T)
    for i in range(10 * space, 10 * space + 10):
        patches[g + MAT_OFF + 18 * i] = q13((Ms @ np.array(matrix(d, g, i))).tolist())
    return patches, gain


def gamma_patches(d, g, looks, bw=None, say=print):
    """{absolute offset: bytes} for looks {space: LOOK} and an optional B&W Saturation Low in space `bw`.
    d must hold Leica's stock GAMMA: looks are composed on Leica's own matrices and curves."""
    import numpy as np
    patches = {}
    for s, name in looks.items():
        p, gain = build_look(d, g, np.load(os.path.join(ROOT, 'research', 'fits', f'fit_{name}.npz')), SPACES[s])
        patches.update(p)
        say(f'{s:5s} <- {name}  (exposure gain {gain:.3f}, {np.log2(gain):+.2f} EV below mid-grey)')
    if bw:
        # Saturation Low of that space -> monochrome: each row = the space's luminance of Leica's own
        # rendering (Y row of the space's RGB->XYZ, applied after its stock matrix), so tone and white
        # stay Leica's and only colour goes. The space's other saturation steps are untouched.
        sp = SPACES[bw]; T, _ = space_tools(sp)
        yw = np.array([0.2126, 0.7152, 0.0722]) @ np.linalg.inv(T)      # luminance in that space's RGB
        for i in (10 * sp, 10 * sp + 1):
            patches[g + MAT_OFF + 18 * i] = q13([(yw @ np.array(matrix(d, g, i))).tolist()] * 3)
        say(f'{bw:5s} Saturation Low <- black & white')
    return patches


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else 'dump'
    opt = lambda k: a[a.index(k) + 1] if k in a else None
    base = opt('--base') or STOCK
    d, g = load(base)
    looks = {s: opt('--' + s) for s in SPACES if opt('--' + s)}
    if cmd == 'dump':
        for i in range(N_MAT):
            print(f'{i:2d} file 0x{g + MAT_OFF + 18 * i:05X}', ' | '.join(' '.join(f'{v:6.3f}' for v in r) for r in matrix(d, g, i)))
    elif cmd == 'bw-test':
        # matrices -> monochrome; curve -> 0.6x output as a control on the path proven on hardware (curves):
        # dark + B&W = matrices used; dark + colour = curves used, these matrices not; neither = not loaded.
        # --all: every matrix and curve, to tell "matrices unused" from "wrong slot guess".
        al = '--all' in a
        mats, curves = (range(N_MAT), range(15)) if al else ((14, 15), (7,))
        p = {g + MAT_OFF + 18 * s: q13([[0.299, 0.587, 0.114]] * 3) for s in mats}
        p.update({g + CURVE_OFF + CURVE_LEN * k: bytes(round(v * 0.6) for v in curve(d, g, k)) for k in curves})
        write(d, p, f'm8-2_014-bwtest{"-all" if al else ""}.upd', base)
    elif cmd == 'build':
        if not looks and not opt('--bw'):
            sys.exit(__doc__)
        print(f'base: {BASES.get(hashlib.sha256(open(base, "rb").read()).hexdigest(), "Leica stock 2.014")}')
        patches = gamma_patches(d, g, looks, opt('--bw'))
        if '--raw-default' in a:
            # Factory profile template 0x20F9C: `strh lr, [r0, #0x2c]` (compression = 1, JPG fine) becomes
            # `strh r7, [r0, #0x2c]` (r7 = 5 there: JPG fine+RAW). One register field in one instruction,
            # no new code; runs when the camera resets its settings (after a firmware update, bad CRC) and
            # for profile 0 at every boot. Needs the base's persistent-RAW patch (P1 at 0x2191C = nop),
            # else the loader turns 5 back into 1. Emulator check: research/settings_emutest.py.
            po, _ = wad(d)['PXA']
            assert d[po + 0x191C:po + 0x1920] == bytes.fromhex('0000a0e1'), 'base lacks the persistent-RAW patch'
            assert d[po + 0xFF4:po + 0xFF8] == bytes.fromhex('bce2c0e1'), 'unexpected instruction at 0x20FF4'
            patches[po + 0xFF4] = bytes.fromhex('bc72c0e1')
            print('PXA   0x20FF4: factory default Compression = JPG fine+RAW')
        dng = '-dng' if base != STOCK else ''
        write(d, patches, opt('--out') or f'm8-2_014{dng}-' + '-'.join(f'{s}_{n.lower()}' for s, n in looks.items()) + '.upd', base)
    elif cmd == 'lut':
        # A card file for gasdevmco's picture-profile picker (base 4359b04b): the picker sends a whole
        # 31,760-byte GAMMA to the Blackfin until power-off, so every .LUT starts from the GAMMA of the
        # firmware actually flashed (--from) and changes only the spaces named here; loading one never
        # wipes the flashed looks of the other spaces. The picker checks only size + the first 24 header
        # bytes, which looks never touch. Contains Leica data: keep the files private.
        name, src = opt('--name'), opt('--from')
        if not (name and src) or not (1 <= len(name) <= 8 and name.isalnum()):
            sys.exit('lut --from FLASHED.upd --name NAME(1-8 letters/digits) [--srgb|--adobe|--eci LOOK] [--bw SPACE] [--bw-test]')
        f, fg = load(src, False)
        assert f[fg:fg + 24] == d[g:g + 24], 'source GAMMA header is not stock'
        lut = bytearray(f[fg:fg + 31760])
        patches = gamma_patches(d, g, looks, opt('--bw'))
        if '--bw-test' in a:      # the bw-test changes, to prove the Blackfin takes matrices from a re-sent GAMMA
            patches.update({g + MAT_OFF + 18 * s: q13([[0.299, 0.587, 0.114]] * 3) for s in (14, 15)})
            patches[g + CURVE_OFF + CURVE_LEN * 7] = bytes(round(v * 0.6) for v in curve(d, g, 7))
        for o, b in patches.items():
            lut[o - g:o - g + len(b)] = b
        out = os.path.join(ROOT, 'build', 'PROFILES', name.upper() + '.LUT')
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, 'wb').write(lut)
        print(f'{out}  ({sum(x != y for x, y in zip(lut, f[fg:fg + 31760]))} bytes differ from {os.path.basename(src)})')
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
