"""Check camera JPGs against the firmware they were shot with: predict each JPG from its own 14-bit
RAW through a GAMMA table (matrix + curve of the JPG's colour space, Saturation/Contrast Standard) and
compare. The flashed build should predict its JPGs better than Leica's stock table does.

  /tmp/m8venv/bin/python research/shot_check.py FLASHED.upd tests/shots/L*.JPG     (needs rawpy)

Pipeline (gasdevmco FINDINGS "JPG tone curves"): raw - black, / white, white balance (AsShotNeutral),
clip, 3x3 matrix, curve (input 0..2047 = black..white). One exposure scale per shot is fitted (the
camera's own scale is ~0.99), then the half-size RAW is aligned to the JPG by a small shift search.
"""
import io, os, sys
import numpy as np, rawpy
from PIL import Image, ExifTags
from PIL.ImageCms import ImageCmsProfile, getProfileDescription
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import m8lut
from film_fit import lab, de2000

flashed, jpgs = sys.argv[1], sys.argv[2:]
tables = {'stock': m8lut.load()[0], 'flashed': m8lut.load(flashed, False)[0]}
_, g = m8lut.load()

def space_of(im):
    icc = im.info.get('icc_profile')
    d = getProfileDescription(ImageCmsProfile(io.BytesIO(icc))) if icc else ''
    return 0 if 'Adobe' in d else 2 if 'ECI' in d else 1

def to_srgb(v, space):
    """JPG values of a space -> sRGB-encoded, to compare colours in one space."""
    if space == 1: return v
    T, enc = m8lut.space_tools(space); _, e1 = m8lut.space_tools(1); xs = np.linspace(0, 1, 4096)
    L = np.interp(v, enc(xs), xs) @ np.linalg.inv(T).T
    return e1(np.clip(L, 0, 1))

def raw_rgb(path):
    r = rawpy.imread(path); a = r.raw_image_visible.astype(float); pat = r.raw_pattern
    black = np.mean(r.black_level_per_channel); white = r.white_level
    h, w = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2; a = a[:h, :w]
    ch = [[], [], []]
    for y in range(2):
        for x in range(2):
            ch[[0, 1, 2, 1][pat[y, x]]].append(a[y::2, x::2])
    rgb = np.stack([np.mean(c, 0) for c in ch], -1)
    rgb = (rgb - black) / (white - black)
    wb = np.array(r.camera_whitebalance[:3], float); wb = wb / wb[1]
    return rgb * wb

def bin2(x, k):
    h, w = x.shape[0] // k * k, x.shape[1] // k * k
    return x[:h, :w].reshape(h // k, k, w // k, k, -1).mean((1, 3))

for jp in jpgs:
    im = Image.open(jp); sp = space_of(im)
    J = bin2(np.asarray(im.convert('RGB'), float) / 255, 8)               # ~492 x 328
    R = bin2(raw_rgb(jp[:-4] + '.RAW'), 4)                                 # same scale (raw is half size)
    out = {}
    for name, d in tables.items():
        M = np.array(m8lut.matrix(d, g, 10 * sp + 4)); c = np.array(m8lut.curve(d, g, 5 * sp + 2), float) / 255
        render = lambda s: np.interp(np.clip(np.clip(R * s, 0, 1) @ M.T, 0, 1), np.arange(2048) / 2047, c)
        best = None
        for s in np.linspace(0.6, 1.6, 51):                                  # exposure scale + shift, coarse
            P = render(s)
            for dy in range(-6, 7, 2):
                for dx in range(-6, 7, 2):
                    a = P[max(dy, 0):P.shape[0] + min(dy, 0), max(dx, 0):P.shape[1] + min(dx, 0)]
                    b = J[max(-dy, 0):, max(-dx, 0):][:a.shape[0], :a.shape[1]]; a = a[:b.shape[0], :b.shape[1]]
                    e = np.median(np.abs(a - b))
                    if best is None or e < best[0]: best = (e, s, dy, dx, a, b)
        e, s, dy, dx, a, b = best
        dE = de2000(lab(to_srgb(b.reshape(-1, 3), sp)), lab(to_srgb(a.reshape(-1, 3), sp)))
        out[name] = (np.median(dE), e * 255, s)
    (fe, fl, fs), (se, sl, ss) = out['flashed'], out['stock']
    verdict = 'flashed look' if fe < se else 'STOCK look'
    print(f'{os.path.basename(jp)} space {["Adobe RGB", "sRGB", "ECI RGB"][sp]:9s} | predicted by flashed table: '
          f'dE00 {fe:4.1f} ({fl:4.1f} levels) | by stock table: dE00 {se:4.1f} ({sl:4.1f}) -> {verdict}')
