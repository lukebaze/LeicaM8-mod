"""Film looks from Kodak datasheets, via Spectral Film LUT (github.com/JanLohse/spectral_film_lut, MIT).

Each stock's digitised datasheet (spectral sensitivity, characteristic curves, dye densities) drives a
spectral simulation: scene -> film (-> print) -> viewed. Writes research/clut/<name>.npz with the same
sample layout as a level-12 HaldCLUT (144^3, red fastest; x = sRGB-encoded scene, y = sRGB output), so
film_fit.py treats it like a CLUT. Unlike the RawTherapee CLUTs, the input is scene-referred: x is
decoded to scene-linear sRGB, mid-grey 0.18.

  research/.venv/bin/python research/spectral_gen.py
"""
import os, time
import numpy as np
import colour
from spectral_film_lut import FILM_STOCKS
from spectral_film_lut.film_spectral import FilmSpectral
from spectral_film_lut.utils import film_conversion

HERE = os.path.dirname(os.path.abspath(__file__))
N = 144
LOOKS = {  # name: (camera stock, print stock or None, extra film_conversion args)
    # slide viewed at D65; white_balance=2 balances on the slide's peak white -> mid-grey neutral (124,124,122)
    # at 6500 K, highlights slightly warm. (mode 1, mid-grey, leaves a blue cast: 124,129,136)
    'SFL Kodachrome 64': ('Kodachrome 64', None, dict(white_balance=2, projector_kelvin=6500)),
    # negative printed on Kodak's own Portra Endura paper (print path does its own balance)
    'SFL Portra 160 Endura': ('Kodak Portra 160', 'Kodak Portra Endura Paper', {}),
}
SLIDE = dict(white_balance=2, projector_kelvin=6500)
LOOKS.update({  # extra looks for the card (PROFILES/*.LUT), same settings as their families above
    'SFL Ektachrome 100D': ('Kodak Ektachrome 100D', None, SLIDE),
    'SFL Velvia 50': ('Fuji Velvia 50', None, SLIDE),
    'SFL Provia 100F': ('Fuji Provia 100F', None, SLIDE),
    'SFL Portra 400 Endura': ('Kodak Portra 400', 'Kodak Portra Endura Paper', {}),
    'SFL Gold 200 Supra': ('Kodak Gold 200', 'Kodak Supra Endura Paper', {}),
    'SFL Tri-X 400 Polymax': ('Kodak Tri-X 400', 'Kodak Polymax Fine-Art Paper Grade 2', {}),
    'SFL Pro 400H Maxima': ('Fuji Pro 400H', 'Fuji Crystal Archive Maxima', {}),
    'SFL Ektar 100 Endura': ('Kodak Ektar 100', 'Kodak Endura Premier Paper', {}),
})
stocks = {s.name: s for s in FILM_STOCKS}

def film(name, negative=None):
    f = FilmSpectral(stocks[name])
    f.set_color_checker(negative=negative) if negative is not None else f.set_color_checker()
    return f

i = np.arange(N ** 3)
x = np.stack([i % N, i // N % N, i // N // N], 1) / (N - 1)
xyz = colour.RGB_to_XYZ(x, 'sRGB', apply_cctf_decoding=True)          # scene-linear, D65
for out, (cam, prn, kw) in LOOKS.items():
    t = time.time()
    neg = film(cam)
    pr = film(prn, neg) if prn else None
    y = np.empty_like(x)
    for s in range(0, len(x), 1 << 18):
        y[s:s + (1 << 18)] = film_conversion(xyz[s:s + (1 << 18)], neg, pr, input_colorspace=None,
                                             output_gamut='Rec. 709', gamma_func='sRGB', **kw)
    np.savez_compressed(os.path.join(HERE, 'clut', out + '.npz'), x=x.astype(np.float32), y=np.clip(y, 0, 1).astype(np.float32))
    g = int(round(0.46 * (N - 1))); k = g + g * N + g * N * N
    print(f'{out}: {time.time() - t:.0f}s, mid-grey in {x[k].round(3)} -> {y[k].round(3)}')
