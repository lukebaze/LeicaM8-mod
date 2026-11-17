"""Render the README images from the built firmware itself (matrices + curves read from the .upd).

  python3 docs/make_images.py      # needs firmware/stock + build/m8-2_014-dng14-kodachrome-portra.upd

Every colour is the simulated in-camera JPG (Saturation + Contrast Standard) of an X-Rite ColorChecker
with its neutral 5 patch at 18 % grey, decoded to sRGB for display. Nothing is painted by hand.
Writes docs/banner.png, docs/compare.png, docs/curves.png, docs/social-preview.png.
"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools')); sys.path.insert(0, os.path.join(ROOT, 'research'))
import m8lut
from film_fit import lin, lab, de2000

COMBO = os.path.join(ROOT, 'build', 'm8-2_014-dng14-kodachrome-portra.upd')
CC = [(115,82,68),(194,150,130),(98,122,157),(87,108,67),(133,128,177),(103,189,170),(214,126,44),(80,91,166),
      (193,90,99),(94,60,108),(157,188,64),(224,163,46),(56,61,150),(70,148,73),(175,54,60),(231,199,31),
      (187,86,149),(8,133,161),(243,243,242),(200,200,200),(160,160,160),(122,122,121),(85,85,85),(52,52,52)]
FONT = '/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf'
FONT_ALT = '/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf'
EDGE = (232, 160, 58)            # the amber of Kodak edge printing
BASE = (22, 17, 14)              # processed film rebate, warm black
S = 2                            # supersampling for clean edges

stock, g = m8lut.load()
combo, _ = m8lut.load(COMBO, False)
M14 = np.array(m8lut.matrix(stock, g, 14))
CAM = lin(np.array(CC) / 255) * (0.18 / lin(122 / 255)) @ np.linalg.inv(M14).T
_, enc_srgb = m8lut.space_tools(1)

def render(d, space, cam=CAM):
    M = np.array(m8lut.matrix(d, g, 10 * space + 4)); c = np.array(m8lut.curve(d, g, 5 * space + 2), float) / 255
    v = np.interp(np.clip(cam @ M.T, 0, 1), np.arange(2048) / 2047, c)
    T, enc = m8lut.space_tools(space); xs = np.linspace(0, 1, 4096)
    return np.clip(enc_srgb(np.clip(np.interp(v, enc(xs), xs) @ np.linalg.inv(T).T, 0, 1)), 0, 1)

def tone(d, space):
    """sRGB output of a grey ramp, -7 .. +2.5 EV around mid-grey (camera clip = +2.47 EV)."""
    ev = np.linspace(-7, np.log2(1 / 0.18), 400)
    return ev, render(d, space, np.repeat((0.18 * 2.0 ** ev)[:, None], 3, 1))[:, 1]

LOOKS = [('LEICA M8 STOCK', 'sRGB slot, firmware 2.014', render(stock, 1)),
         ('KODACHROME 64', 'Colour space sRGB', render(combo, 1)),
         ('PORTRA 160', 'Colour space Adobe RGB', render(combo, 0))]
rgb = lambda v: tuple(int(round(t * 255)) for t in v)
font = lambda size, alt=False: ImageFont.truetype(FONT_ALT if alt else FONT, size * S)

def chart(dr, x, y, w, colours, gap):
    """6x4 ColorChecker inside a w-wide 3:2 frame."""
    p = (w - 7 * gap) / 6
    for i, c in enumerate(colours):
        cx, cy = x + gap + i % 6 * (p + gap), y + gap + i // 6 * (p + gap)
        dr.rectangle([cx, cy, cx + p, cy + p], fill=rgb(c))

def filmstrip(width, frame_w):
    """Transparent canvas with one 35 mm strip: KS perforations, three frames, edge printing."""
    gap = frame_w * 0.022
    fh = 4 * (frame_w - 7 * gap) / 6 + 5 * gap        # frame fits the 6x4 chart exactly
    rebate = fh * 0.30; H = fh + 2 * rebate
    im = Image.new('RGBA', (width * S, int(H * S)), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, width * S, H * S], fill=BASE)
    pitch = frame_w / 8                                # 8 perforations per frame, as on 135 film
    ph, pw = rebate * 0.34, pitch * 0.42               # perforation row sits inside, edge print outside it
    for k in range(int(width / pitch) + 1):
        px = (k + 0.3) * pitch
        for py in (rebate * 0.40, H - rebate * 0.40 - ph):
            dr.rounded_rectangle([px * S, py * S, (px + pw) * S, (py + ph) * S], radius=pw * 0.18 * S, fill=(0, 0, 0, 0))
    gap_f = (width - 3 * frame_w) / 4
    for j, (name, note, cols) in enumerate(LOOKS):
        fx = gap_f + j * (frame_w + gap_f)
        dr.rectangle([fx * S, rebate * S, (fx + frame_w) * S, (rebate + fh) * S], fill=(10, 8, 7))
        chart(dr, fx * S, rebate * S, frame_w * S, cols, gap * S)
        f = font(int(rebate * 0.24)); yb, yt = (H - rebate * 0.20) * S, rebate * 0.20 * S
        dr.text(((fx + 2) * S, yb), name, font=f, fill=EDGE, anchor='lm')
        dr.text(((fx + frame_w) * S, yb), f'{2 * j + 12}    {2 * j + 12}A', font=f, fill=EDGE, anchor='rm')
        dr.text(((fx + 2) * S, yt), note.upper(), font=f, fill=EDGE + (170,), anchor='lm')
    return im.resize((width, int(H)), Image.LANCZOS)

def banner():
    im = filmstrip(1600, 470)
    im.save(os.path.join(HERE, 'banner.png')); return im

def social():
    W, H = 1280, 640
    im = Image.new('RGB', (W * S, H * S), (238, 233, 224)); dr = ImageDraw.Draw(im)
    dr.text((72 * S, 92 * S), 'LeicaM8', font=font(92), fill=BASE, anchor='ls')
    dr.text((74 * S, 140 * S), 'Kodachrome 64 and Portra 160 for the M8 JPG pipeline, from Kodak datasheets',
            font=font(30, True), fill=(92, 80, 70), anchor='ls')
    strip = filmstrip(1280, 380)
    im = im.resize((W, H), Image.LANCZOS)
    im.paste(strip, (0, H - strip.height - 70), strip)
    im.save(os.path.join(HERE, 'social-preview.png'))

def compare():
    """Split patches: left half Leica stock, right half the look; CIEDE2000 between them."""
    P, pad, top = 92, 36, 70
    W = 2 * (6 * P) + 3 * pad
    im = Image.new('RGB', (W * S, (top + 4 * P + 64) * S), (238, 233, 224)); dr = ImageDraw.Draw(im)
    base = LOOKS[0][2]
    for j, (name, note, cols) in enumerate(LOOKS[1:]):
        x0 = pad + j * (6 * P + pad)
        dE = de2000(lab(base), lab(cols))
        dr.text((x0 * S, 34 * S), name, font=font(30), fill=BASE, anchor='ls')
        dr.text((x0 * S, 58 * S), f'{note}  /  median \u0394E00 vs stock {np.median(dE):.1f}', font=font(17, True), fill=(92, 80, 70), anchor='ls')
        for i in range(24):
            x, y = (x0 + i % 6 * P) * S, (top + i // 6 * P) * S; q = (P - 6) * S
            dr.rectangle([x, y, x + q // 2, y + q], fill=rgb(base[i]))
            dr.rectangle([x + q // 2, y, x + q, y + q], fill=rgb(cols[i]))
            L = lab(np.array([cols[i]]))[0, 0]
            dr.text((x + q - 6 * S, y + q - 6 * S), f'{dE[i]:.0f}', font=font(16, True),
                    fill=(20, 16, 13) if L > 55 else (245, 240, 232), anchor='rs')
    dr.text((pad * S, (top + 4 * P + 30) * S), 'Each patch: left half Leica stock, right half the look. Number: CIEDE2000 between the halves.',
            font=font(17, True), fill=(92, 80, 70), anchor='ls')
    im.resize((W, top + 4 * P + 64), Image.LANCZOS).save(os.path.join(HERE, 'compare.png'))

def curves():
    W, H, l, r, t, b = 1000, 520, 70, 30, 60, 60
    im = Image.new('RGB', (W * S, H * S), (238, 233, 224)); dr = ImageDraw.Draw(im)
    X = lambda ev: (l + (ev + 7) / (2.47 + 7) * (W - l - r)) * S
    Y = lambda v: (H - b - v * (H - t - b)) * S
    for ev in range(-7, 3):
        dr.line([X(ev), Y(0), X(ev), Y(1)], fill=(222, 215, 204), width=S)
        dr.text((X(ev), Y(0) + 22 * S), f'{ev:+d}' if ev else '0', font=font(16, True), fill=(92, 80, 70), anchor='mm')
    for v in (0, 0.25, 0.5, 0.75, 1):
        dr.line([X(-7), Y(v), X(2.47), Y(v)], fill=(222, 215, 204), width=S)
        dr.text((X(-7) - 12 * S, Y(v)), f'{int(v * 255)}', font=font(16, True), fill=(92, 80, 70), anchor='rm')
    dr.text((X(2.47), Y(0) + 44 * S), 'EV from mid-grey  (sensor clip at +2.5)', font=font(16, True), fill=(92, 80, 70), anchor='rm')
    dr.text((l * S, 36 * S), 'TONE: GREY RAMP THROUGH THE BUILT CURVES', font=font(26), fill=BASE, anchor='ls')
    for j, ((name, _, _), d, sp, col) in enumerate(zip(LOOKS, (stock, combo, combo), (1, 1, 0), ((120, 112, 104), (176, 46, 32), (205, 128, 40)))):
        ev, v = tone(d, sp)
        dr.line([(X(e), Y(t_)) for e, t_ in zip(ev, v)], fill=col, width=3 * S, joint='curve')
        ly = (t + 30 + 30 * j) * S                    # legend, top left: the lines cross near mid-grey
        dr.line([X(-6.7), ly, X(-6.7) + 34 * S, ly], fill=col, width=4 * S)
        dr.text((X(-6.7) + 46 * S, ly), name, font=font(18), fill=col, anchor='lm')
    im.resize((W, H), Image.LANCZOS).save(os.path.join(HERE, 'curves.png'))

banner(); social(); compare(); curves()
print('wrote docs/banner.png docs/social-preview.png docs/compare.png docs/curves.png')
