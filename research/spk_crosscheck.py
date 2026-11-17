"""Cross-check the Spectral Film LUT looks against an independent datasheet simulator, spektrafilm
(github.com/andreavolpato/spektrafilm, GPL-3; run from its own venv, Python 3.13):

  research/.venv-spk/bin/python research/spk_crosscheck.py

Renders the 24 ColorChecker patches (scene-linear, sRGB) through spektrafilm and prints them next to
research/clut/SFL *.npz at the same inputs, with CIEDE2000 between the two simulators.
"""
import os
import numpy as np
from spektrafilm import simulate
from spektrafilm.runtime.api import init_params

HERE = os.path.dirname(os.path.abspath(__file__))
N = 144
CC = [(115,82,68),(194,150,130),(98,122,157),(87,108,67),(133,128,177),(103,189,170),(214,126,44),(80,91,166),
      (193,90,99),(94,60,108),(157,188,64),(224,163,46),(56,61,150),(70,148,73),(175,54,60),(231,199,31),
      (187,86,149),(8,133,161),(243,243,242),(200,200,200),(160,160,160),(122,122,121),(85,85,85),(52,52,52)]
NAMES = ['dark skin', 'light skin', 'blue sky', 'foliage', 'blue flower', 'bluish green', 'orange', 'purplish blue',
         'moderate red', 'purple', 'yellow green', 'orange yellow', 'blue', 'green', 'red', 'yellow', 'magenta',
         'cyan', 'white', 'n8', 'n6.5', 'n5', 'n3.5', 'black']
PAIRS = {'SFL Kodachrome 64': ('kodak_kodachrome_64', 'kodak_portra_endura'),   # positive: print unused
         'SFL Portra 160 Endura': ('kodak_portra_160', 'kodak_portra_endura')}

lin = lambda v: np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
M_XYZ = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
def lab(srgb):
    xyz = lin(np.clip(srgb, 0, 1)) @ M_XYZ.T / np.array([0.95047, 1, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)
def de76(a, b):  # simple and enough to tell agreement from disagreement
    return np.linalg.norm(lab(a) - lab(b), axis=1)

x = np.array(CC) / 255
for sfl, (film, paper) in PAIRS.items():
    p = init_params(film, paper)
    p.io.input_color_space, p.io.input_cctf_decoding = 'sRGB', True
    p.io.output_color_space, p.io.output_cctf_encoding = 'sRGB', True
    p.debug.lut_mode = True
    p.camera.auto_exposure = False
    p.io.scan_film = 'kodachrome' in film    # a slide is viewed itself, not printed
    spk = np.clip(np.asarray(simulate(x[None].astype(np.float32), p))[0, :, :3], 0, 1)
    z = np.load(os.path.join(HERE, 'clut', sfl + '.npz'))
    idx = [round(r / 255 * (N - 1)) + round(g / 255 * (N - 1)) * N + round(b / 255 * (N - 1)) * N * N for r, g, b in CC]
    sf = z['y'][idx].astype(float)
    d = de76(sf, spk)
    print(f'\n## {sfl} vs spektrafilm {film}{"" if "kodachrome" in film else " + " + paper}  (n5 L* {lab(sf[21:22])[0,0]:.0f} vs {lab(spk[21:22])[0,0]:.0f})')
    for i, n in enumerate(NAMES):
        print(f'{n:14s} SFL {tuple(np.round(sf[i]*255).astype(int))}  spk {tuple(np.round(spk[i]*255).astype(int))}  dE76 {d[i]:5.1f}')
    print(f'median dE76 {np.median(d):.1f} (colour patches {np.median(d[:18]):.1f})')
