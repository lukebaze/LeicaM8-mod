"""Which GAMMA table made a camera JPG? Predict the JPG from its own 14-bit RAW through every candidate
table (and, per card look, its curve with the flashed matrix = "curves only" re-send) and rank them.

  /tmp/m8venv/bin/python research/look_id.py FLASHED.upd PROFILES_DIR tests/shots/L*.JPG   (needs rawpy)

Candidates for an sRGB JPG: the flashed table (Kodachrome) and every PROFILES/*.LUT, each as sent
(matrix + curve) and as "curve only" (the LUT's curve, flashed matrix). Shift is found once with the
flashed table; exposure scale is fitted per candidate. Score: median |predicted - JPG| in 8-bit levels.
"""
import glob, io, os, sys
import numpy as np
from PIL import Image
from PIL.ImageCms import ImageCmsProfile, getProfileDescription
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import m8lut
from shot_check_lib import raw_rgb, bin2

flashed, pdir, jpgs = sys.argv[1], sys.argv[2], sys.argv[3:]
fd, g = m8lut.load(flashed, False)
tables = {'FLASHED': (fd, g)}
for f in sorted(glob.glob(os.path.join(pdir, '*.LUT'))):
    tables[os.path.basename(f)[:-4]] = (open(f, 'rb').read(), 0)

def mc(t, sp):
    d, o = t
    return np.array(m8lut.matrix(d, o, 10 * sp + 4)), np.array(m8lut.curve(d, o, 5 * sp + 2), float) / 255

def render(R, M, c, s):
    return np.interp(np.clip(np.clip(R * s, 0, 1) @ M.T, 0, 1), np.arange(2048) / 2047, c)

def crop(P, J, dy, dx):
    a = P[max(dy, 0):P.shape[0] + min(dy, 0), max(dx, 0):P.shape[1] + min(dx, 0)]
    b = J[max(-dy, 0):, max(-dx, 0):][:a.shape[0], :a.shape[1]]
    return a[:b.shape[0], :b.shape[1]], b

for jp in jpgs:
    im = Image.open(jp); icc = im.info.get('icc_profile')
    d = getProfileDescription(ImageCmsProfile(io.BytesIO(icc))) if icc else ''
    sp = 0 if 'Adobe' in d else 2 if 'ECI' in d else 1
    J = bin2(np.asarray(im.convert('RGB'), float) / 255, 8); R = bin2(raw_rgb(jp[:-4] + '.RAW'), 4)
    M0, c0 = mc(tables['FLASHED'], sp)
    best = min(((np.median(np.abs(np.subtract(*crop(render(R, M0, c0, s), J, dy, dx)))), dy, dx)
                for s in np.linspace(0.5, 2.0, 31) for dy in range(-6, 7, 2) for dx in range(-6, 7, 2)))
    _, dy, dx = best
    res = []
    cands = [('FLASHED', mc(tables['FLASHED'], sp))]
    if sp == 1:
        for n, t in tables.items():
            if n == 'FLASHED': continue
            M, c = mc(t, sp); cands += [(n, (M, c)), (n + ' (curve only)', (M0, c))]
    for n, (M, c) in cands:
        e = min(np.median(np.abs(np.subtract(*crop(render(R, M, c, s), J, dy, dx)))) for s in np.linspace(0.5, 2.0, 61))
        res.append((e * 255, n))
    res.sort()
    top = ', '.join(f'{n} {e:.1f}' for e, n in res[:3])
    print(f'{os.path.basename(jp)} [{["Adobe RGB", "sRGB", "ECI RGB"][sp]}] best: {top}')
