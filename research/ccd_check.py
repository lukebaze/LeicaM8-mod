"""Check built look firmware against the film CLUT and the M8's CCD behaviour, from the built bytes.

  python3 research/ccd_check.py build/X.upd "research/clut/Kodak Portra 160 2.png" [more pairs...]

Simulated camera JPG (sRGB, Saturation + Contrast Standard): out = curve7[matrix14 . cam], cam = camera
RGB after white balance, 0..1 = black..clip. Reports:
  fit      median CIEDE2000 vs the CLUT, through the quantised Q13 matrix + u8 curve
  clip     JPG value of a fully clipped CCD highlight (cam 1,1,1): should stay neutral
  shadow   noise gain vs Leica stock at 1 % and 18 % grey (|d out / d cam|, all channels)
  IR       chroma of a dark grey + near-IR leak, vs stock. ASSUMPTION: NIR leaks into the M8's
           R and B dyes more than G (the known magenta cast), modelled as cam += 0.02 * (1, .4, 1)
Writes build/preview.png: ColorChecker + grey ramp, Leica stock vs each build, same exposure.
"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools')); sys.path.insert(0, HERE)
import m8lut
from film_fit import load as load_clut, lin, lab, de2000

def pipeline(path, check):
    d, g = m8lut.load(path, check)
    M = np.array(m8lut.matrix(d, g, 14)); c = np.array(m8lut.curve(d, g, 7), float)
    return lambda cam: np.interp(np.clip(cam @ M.T, 0, 1), np.arange(2048) / 2047, c) / 255, M

stock, M14 = pipeline(m8lut.STOCK, True)
enc = lambda v: np.where(v <= 0.0031308, 12.92 * v, 1.055 * np.clip(v, 0, None) ** (1 / 2.4) - 0.055)

def noise_gain(f, grey):
    cam = np.full((1, 3), grey); J = np.empty((3, 3))
    for k in range(3):
        e = np.zeros((1, 3)); e[0, k] = 2e-3
        J[:, k] = ((f(cam + e) - f(cam - e)) / 4e-3)[0]
    return np.linalg.norm(J)

def ir_chroma(f):
    L = lab(f(np.array([[0.02, 0.02, 0.02]]) + 0.02 * np.array([[1, .4, 1]])))[0]
    return np.hypot(L[1], L[2]), np.degrees(np.arctan2(L[2], L[1])) % 360

CC = [(115,82,68),(194,150,130),(98,122,157),(87,108,67),(133,128,177),(103,189,170),(214,126,44),(80,91,166),
      (193,90,99),(94,60,108),(157,188,64),(224,163,46),(56,61,150),(70,148,73),(175,54,60),(231,199,31),
      (187,86,149),(8,133,161),(243,243,242),(200,200,200),(160,160,160),(122,122,121),(85,85,85),(52,52,52)]
def chart(f):
    """ColorChecker (scene: n5 patch at 18 %) + 1/3-stop grey ramp from -6 to +3 EV, rendered by f."""
    scene = lin(np.array(CC) / 255) * (0.18 / lin(122 / 255))
    cam = scene @ np.linalg.inv(M14).T                  # what the CCD would record, after WB
    ramp = np.repeat((0.18 * 2.0 ** np.linspace(-6, 3, 28))[:, None], 3, 1)
    return np.clip(f(cam), 0, 1), np.clip(f(ramp), 0, 1)

rows = [('Leica stock', stock)]
a = sys.argv[1:]
print(f'{"build":44s} {"fit":>5s} {"clip RGB":>15s} {"shadow 1%":>9s} {"18%":>5s} {"IR C (hue)":>12s}')
c0, h0 = ir_chroma(stock)
print(f'{"Leica stock":44s} {"":>5s} {str(tuple(np.round(stock(np.ones((1, 3)))[0] * 255).astype(int))):>15s} {1:9.2f} {1:5.2f} {c0:6.1f} ({h0:3.0f})')
for upd, clut in zip(a[::2], a[1::2]):
    f, Mn = pipeline(upd, False)
    # through the camera: cam chosen so the stock matrix gives the CLUT's input; the build's curve
    # carries the mid-grey gain, so undo it to compare with the CLUT at its own exposure
    x, y = load_clut(clut); s = np.random.default_rng(0).choice(len(x), 60000, replace=False)
    fit = np.load(os.path.join(HERE, 'fits', 'fit_' + os.path.basename(clut)[:-4].replace(' ', '_') + '.npz'))
    _, gain = m8lut.build_look(*m8lut.load(), fit)       # gain below mid-grey; above it the shoulder departs on purpose
    cam = lin(x[s]) @ np.linalg.inv(M14).T / gain
    dE = np.median(de2000(lab(y[s]), lab(f(cam))))
    clip = tuple(np.round(f(np.ones((1, 3)))[0] * 255).astype(int))
    c, h = ir_chroma(f)
    print(f'{os.path.basename(upd):44s} {dE:5.2f} {str(clip):>15s} {noise_gain(f, .01) / noise_gain(stock, .01):9.2f} '
          f'{noise_gain(f, .18) / noise_gain(stock, .18):5.2f} {c:6.1f} ({h:3.0f})')
    rows.append((os.path.basename(upd)[9:-4], f))

P, W = 36, 6 * 36
img = Image.new('RGB', (len(rows) * (W + 24) + 24, 4 * P + 70), (40, 40, 40)); dr = ImageDraw.Draw(img)
for j, (name, f) in enumerate(rows):
    cc, ramp = chart(f); x0 = 24 + j * (W + 24)
    dr.text((x0, 6), name, fill=(230, 230, 230))
    for i, v in enumerate(cc):
        dr.rectangle([x0 + i % 6 * P, 24 + i // 6 * P, x0 + i % 6 * P + P - 2, 24 + i // 6 * P + P - 2], fill=tuple(int(t * 255 + .5) for t in v))
    for i, v in enumerate(ramp):
        dr.rectangle([x0 + i * W / 28, 30 + 4 * P, x0 + (i + 1) * W / 28, 60 + 4 * P], fill=tuple(int(t * 255 + .5) for t in v))
img = img.resize((img.width * 2, img.height * 2), Image.NEAREST)
img.save(os.path.join(ROOT, 'build', 'preview.png')); print('wrote build/preview.png')
