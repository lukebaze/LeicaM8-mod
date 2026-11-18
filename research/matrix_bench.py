"""Recover the colour matrix the camera actually used, from RAW+JPG pairs, and compare with the built ones.

  /tmp/m8venv/bin/python research/matrix_bench.py FLASHED.upd PROFILES_DIR      (needs rawpy)

JPG = curve(M . raw). The tone curve is known (curve_bench.py shows it matches within 1-3 levels), so
each JPG channel is inverted through it, giving M . raw per pixel; M is then a least-squares fit over
well-exposed pixels (all JPG channels 20..235, RAW unclipped). The recovered M is scored against every
candidate matrix of that slot -- Leica stock, the flashed look, and card looks -- and both variants A/B
(Saturation Standard has two matrices, #4/#5 of the space: which one the Blackfin picks is unknown).

Also checks clipped highlights: pixels clipped in the RAW (any channel >= 0.98) should come out neutral.
"""
import glob, io, os, sys
import numpy as np
from PIL import Image
from PIL.ImageCms import ImageCmsProfile, getProfileDescription
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'tools'))
import m8lut
from shot_check_lib import raw_rgb, bin2

flashed, pdir = sys.argv[1], sys.argv[2]
SHOTS = os.path.join(ROOT, 'tests', 'shots')
stock, g = m8lut.load(); fl, _ = m8lut.load(flashed, False)
TABLES = {'stock': (stock, g), 'flashed': (fl, g)}
for f in sorted(glob.glob(os.path.join(pdir, '*.LUT'))):
    TABLES[os.path.basename(f)[:-4]] = (open(f, 'rb').read(), 0)
GROUPS = [  # label, shots, space, table the curve comes from (shots identified by look_id/curve_bench)
    ('Kodachrome 64 (sRGB)', [371, 374, 375, 376, 378, 379, 381], 1, 'flashed'),
    ('Provia 100F from card (sRGB)', [369, 370], 1, 'PROVIA'),
    ('Portra 160 (Adobe RGB)', [365, 366, 383], 0, 'flashed'),
    ('Leica stock (ECI RGB)', [364], 2, 'stock'),
]

def space_of(jp):
    icc = Image.open(jp).info.get('icc_profile')
    d = getProfileDescription(ImageCmsProfile(io.BytesIO(icc))) if icc else ''
    return 0 if 'Adobe' in d else 2 if 'ECI' in d else 1

def pairs(n, curve):
    jp = os.path.join(SHOTS, f'L9998{n}.JPG')
    J = bin2(np.asarray(Image.open(jp).convert('RGB'), float) / 255, 8); R = bin2(raw_rgb(jp[:-4] + '.RAW'), 4)
    cx = np.arange(2048) / 2047
    best = None
    for dy in range(-6, 7, 2):
        for dx in range(-6, 7, 2):
            a = R[max(dy, 0):R.shape[0] + min(dy, 0), max(dx, 0):R.shape[1] + min(dx, 0)]
            b = J[max(-dy, 0):, max(-dx, 0):][:a.shape[0], :a.shape[1]]; a = a[:b.shape[0], :b.shape[1]]
            e = np.median(np.abs(np.interp(np.clip(a.mean(-1), 0, 1), cx, curve) - b.mean(-1)))
            if best is None or e < best[0]: best = (e, a.reshape(-1, 3), b.reshape(-1, 3))
    return best[1], best[2]

def inv(curve, y):
    c = curve + np.arange(2048) * 1e-7
    return np.interp(y, c, np.arange(2048) / 2047)

print('Recovered matrix vs candidates (Frobenius distance; lower = the one the camera used)\n')
for label, shots, sp, src in GROUPS:
    d, o = TABLES[src]; curve = np.array(m8lut.curve(d, o, 5 * sp + 2), float) / 255
    A, B, clipped = [], [], []
    for n in shots:
        if not os.path.exists(os.path.join(SHOTS, f'L9998{n}.RAW')): continue
        a, b = pairs(n, curve)
        ok = (b.min(1) > 20 / 255) & (b.max(1) < 235 / 255) & (a.max(1) < 0.95) & (a.min(1) > 0.003)
        ok &= (a.max(1) - a.min(1)) / a.mean(1) > 0.15     # coloured pixels only: greys carry no matrix info
        A.append(a[ok]); B.append(inv(curve, b[ok]))
        clip = a.max(1) >= 0.98
        if clip.any(): clipped.append(b[clip])
    A, B = np.concatenate(A), np.concatenate(B)
    # rows sum to 1 in every Leica matrix: fit row r = (x, y, 1-x-y), well-conditioned once greys drop out
    D = np.stack([A[:, 0] - A[:, 2], A[:, 1] - A[:, 2]], 1)
    M = np.array([[*xy, 1 - xy.sum()] for xy in (np.linalg.lstsq(D, B[:, c] - A[:, 2], rcond=None)[0] for c in range(3))])
    resid = np.median(np.abs(A @ M.T - B)) * 2047
    print(f'## {label}: {len(A)} coloured px, fit residual {resid:.1f} curve-input steps (of 2048)')
    print('   recovered M =', np.array2string(M, precision=3, suppress_small=True).replace('\n', ''))
    scores = sorted({(np.linalg.norm(M - np.array(m8lut.matrix(td, to, 10 * sp + k))), f'{name} {v}')
                     for name, (td, to) in TABLES.items() for v, k in (('A', 4), ('B', 5))})
    own = {v: np.linalg.norm(M - np.array(m8lut.matrix(d, o, 10 * sp + k))) for v, k in (('A', 4), ('B', 5))}
    print(f'   own table ({src}): variant A {own["A"]:.3f}, variant B {own["B"]:.3f}')
    print('   closest:', ', '.join(f'{n} {s:.3f}' for s, n in scores[:4]))
    if clipped:
        c = np.concatenate(clipped) * 255
        print(f'   clipped highlights: {len(c)} px, JPG chroma (max-min) median {np.median(c.max(1) - c.min(1)):.1f}, '
              f'p95 {np.percentile(c.max(1) - c.min(1), 95):.1f} levels, mean RGB {np.round(c.mean(0)).astype(int).tolist()}')
    print()
