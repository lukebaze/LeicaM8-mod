"""Bench the in-camera tone curves from real shots: neutral pixels of each JPG vs its own 14-bit RAW.

  /tmp/m8venv/bin/python research/curve_bench.py FLASHED.upd PROFILES_DIR      (needs rawpy)

Every GAMMA matrix row sums to 1, so a pixel that is neutral after white balance (R = G = B in the RAW)
reaches the tone curve unchanged: its JPG value IS curve(raw level), whatever the look's matrix. So the
neutral pixels of a RAW+JPG pair trace the curve the camera actually used. Pixels: 8x8-binned JPG, 4x4
binned half-size RAW, aligned by a small shift search, neutral = channel spread < 3 %, not clipped.
Exposure: raw (level - black) / (white - black) goes straight into the curve (gasdevmco measured scale
0.993); a per-shot scale is fitted only as a check. Adobe/ECI values are converted to sRGB encoding so all
curves share one axis. Writes docs/curves_measured.png and prints the median gap to the built curve.
"""
import glob, io, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PIL.ImageCms import ImageCmsProfile, getProfileDescription
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'tools'))
import m8lut
from shot_check_lib import raw_rgb, bin2

flashed, pdir = sys.argv[1], sys.argv[2]
SHOTS = os.path.join(ROOT, 'tests', 'shots')
stock, g = m8lut.load(); fl, _ = m8lut.load(flashed, False)
LOOKS = [  # (label, shots, table bytes, offset, space, colour) -- shots identified by research/look_id.py
    ('KODACHROME 64', [371, 374, 375, 376, 378, 379, 381], fl, g, 1, (176, 46, 32)),
    ('PORTRA 160', [365, 366, 383], fl, g, 0, (205, 128, 40)),
    ('PROVIA 100F (card)', [369, 370], open(os.path.join(pdir, 'PROVIA.LUT'), 'rb').read(), 0, 1, (40, 110, 170)),
    ('LEICA M8 STOCK (ECI)', [364, 367], stock, g, 2, (120, 112, 104)),
]
_, e1 = m8lut.space_tools(1)
dec = lambda v: np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)

def to_srgb_enc(v, sp):
    """A neutral value encoded in space sp -> the same light, sRGB-encoded (neutral stays neutral)."""
    if sp == 1: return v
    _, enc = m8lut.space_tools(sp); xs = np.linspace(0, 1, 4096)
    return e1(np.interp(v, enc(xs), xs))

def curve_of(d, o, sp):
    c = np.array(m8lut.curve(d, o, 5 * sp + 2), float) / 255
    return lambda u: to_srgb_enc(np.interp(np.clip(u, 0, 1), np.arange(2048) / 2047, c), sp)

def neutral_points(n, sp, curve):
    jp = os.path.join(SHOTS, f'L9998{n}.JPG')
    J = bin2(np.asarray(Image.open(jp).convert('RGB'), float) / 255, 8)
    R = bin2(raw_rgb(jp[:-4] + '.RAW'), 4)
    best = None
    for dy in range(-6, 7, 2):
        for dx in range(-6, 7, 2):
            a = R[max(dy, 0):R.shape[0] + min(dy, 0), max(dx, 0):R.shape[1] + min(dx, 0)]
            b = J[max(-dy, 0):, max(-dx, 0):][:a.shape[0], :a.shape[1]]; a = a[:b.shape[0], :b.shape[1]]
            e = np.median(np.abs(to_srgb_enc(np.clip(b.mean(-1), 0, 1), sp) - curve(a.mean(-1))))
            if best is None or e < best[0]: best = (e, a.reshape(-1, 3), b.reshape(-1, 3))
    _, a, b = best
    u = a.mean(1); spread = (a.max(1) - a.min(1)) / np.maximum(u, 1e-6)
    ok = (spread < 0.03) & (u > 1e-4) & (a.max(1) < 0.98) & (b.max(1) < 0.995)
    return u[ok], to_srgb_enc(b[ok, 1], sp)

X = lambda ev: (70 + (ev + 7) / 9.47 * 860) * 2
Y = lambda v: (460 - v * 400) * 2
W, H = 1000, 520
im = Image.new('RGB', (W * 2, H * 2), (238, 233, 224)); dr = ImageDraw.Draw(im)
F = lambda s, alt=False: ImageFont.truetype('/System/Library/Fonts/Supplemental/' + ('DIN Alternate Bold.ttf' if alt else 'DIN Condensed Bold.ttf'), s * 2)
for ev in range(-7, 3):
    dr.line([X(ev), Y(0), X(ev), Y(1)], fill=(222, 215, 204), width=2)
    dr.text((X(ev), Y(0) + 44), f'{ev:+d}' if ev else '0', font=F(16, True), fill=(92, 80, 70), anchor='mm')
for v in (0, .25, .5, .75, 1):
    dr.line([X(-7), Y(v), X(2.47), Y(v)], fill=(222, 215, 204), width=2)
    dr.text((X(-7) - 24, Y(v)), f'{int(v * 255)}', font=F(16, True), fill=(92, 80, 70), anchor='rm')
dr.text((140, 72), 'TONE: MEASURED FROM CAMERA RAW + JPG PAIRS (DOTS) VS BUILT CURVES (LINES)', font=F(26), fill=(22, 17, 14), anchor='ls')
dr.text((X(2.47), Y(0) + 88), 'EV from mid-grey, sRGB-encoded output (8-bit)', font=F(16, True), fill=(92, 80, 70), anchor='rm')
ev = np.linspace(-7, np.log2(1 / 0.18), 400)
for j, (label, shots, d, o, sp, col) in enumerate(LOOKS):
    curve = curve_of(d, o, sp)
    us, ys = [], []
    for n in shots:
        if not os.path.exists(os.path.join(SHOTS, f'L9998{n}.RAW')): continue
        u, y = neutral_points(n, sp, curve); us.append(u); ys.append(y)
    u, y = np.concatenate(us), np.concatenate(ys)
    # exposure check: scale that best maps raw onto the built curve (1.0 = raw goes straight in)
    ss = np.linspace(0.7, 1.4, 141); s = ss[np.argmin([np.median(np.abs(curve(u * k) - y)) for k in ss])]
    gap = np.median(np.abs(curve(u) - y)) * 255
    e_pts = np.log2(np.maximum(u, 1e-9) / 0.18)
    # binned medians, 1/3 EV
    bins = np.arange(-7, 2.6, 1 / 3); mids, meds = [], []
    for lo in bins:
        m = (e_pts >= lo) & (e_pts < lo + 1 / 3)
        if m.sum() >= 15: mids.append(lo + 1 / 6); meds.append(np.median(y[m]))
    dr.line([(X(e), Y(v)) for e, v in zip(ev, curve(0.18 * 2 ** ev))], fill=col, width=5, joint='curve')
    for e, v in zip(mids, meds):
        dr.ellipse([X(e) - 9, Y(v) - 9, X(e) + 9, Y(v) + 9], fill=col, outline=(22, 17, 14), width=2)
    ly = 130 + 56 * j
    dr.line([X(-6.7), ly, X(-6.7) + 60, ly], fill=col, width=8)
    dr.text((X(-6.7) + 84, ly), f'{label}  {len(u)} px, gap {gap:.1f}', font=F(18), fill=col, anchor='lm')
    print(f'{label:22s} shots {shots}: {len(u):5d} neutral px, EV {e_pts.min():+.1f}..{e_pts.max():+.1f}, '
          f'median gap to built curve {gap:.1f} levels, best exposure scale {s:.3f}')
im.resize((W, H), Image.LANCZOS).save(os.path.join(ROOT, 'docs', 'curves_measured.png'))
print('wrote docs/curves_measured.png')
