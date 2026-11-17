"""How much of a film HaldCLUT can the M8 JPG pipeline reproduce?
M8 pipeline (gasdevmco FINDINGS): linear RGB -> 3x3 matrix -> ONE tone curve shared by R,G,B.
Models fitted per CLUT, error = CIEDE2000 vs the CLUT itself:
  curve   : f(L)            (stock matrix, only GAMMA curves changed: what is proven today)
  curve+M : f(M L)          (if the 0x1D0 block is the matrix)
  3curve+M: f_c(M L)        (per-channel curves: ceiling if the Blackfin allowed it)
"""
import sys, glob, os
import numpy as np
from PIL import Image

N = 144
def load(p):
    a = np.asarray(Image.open(p).convert('RGB'), np.float64).reshape(-1, 3) / 255
    i = np.arange(N ** 3)
    x = np.stack([i % N, i // N % N, i // N // N], 1) / (N - 1)
    return x, a

lin = lambda v: np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
M_XYZ = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
def lab(srgb):
    xyz = lin(np.clip(srgb, 0, 1)) @ M_XYZ.T / np.array([0.95047, 1, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)

def de2000(a, b):
    L1, a1, b1 = a.T; L2, a2, b2 = b.T
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2); Cb = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1, h2 = np.degrees(np.arctan2(b1, a1p)) % 360, np.degrees(np.arctan2(b2, a2p)) % 360
    dL, dC = L2 - L1, C2p - C1p
    dh = h2 - h1; dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0, dh)
    dH = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lb, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    hb = np.where(np.abs(h1 - h2) > 180, (h1 + h2 + 360) / 2, (h1 + h2) / 2)
    hb = np.where(C1p * C2p == 0, h1 + h2, hb)
    T = 1 - .17 * np.cos(np.radians(hb - 30)) + .24 * np.cos(np.radians(2 * hb)) \
        + .32 * np.cos(np.radians(3 * hb + 6)) - .2 * np.cos(np.radians(4 * hb - 63))
    SL = 1 + .015 * (Lb - 50) ** 2 / np.sqrt(20 + (Lb - 50) ** 2)
    SC, SH = 1 + .045 * Cbp, 1 + .015 * Cbp * T
    RT = -2 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7)) * np.sin(np.radians(60 * np.exp(-((hb - 275) / 25) ** 2)))
    return np.sqrt((dL / SL) ** 2 + (dC / SC) ** 2 + (dH / SH) ** 2 + RT * dC / SC * dH / SH)

K = 256  # curve knots in v = u**(1/2.2); M8 curves have 2048 entries, plenty
grid = np.linspace(0, 1, K)
def fit_curve(u, y):
    """monotone LUT y = f(u): bin means in v-space, then running max (cheap isotonic)."""
    v = np.clip(u, 0, 1) ** (1 / 2.2)
    idx = np.minimum((v * (K - 1)).round().astype(int), K - 1)
    s, c = np.bincount(idx, y, K), np.bincount(idx, minlength=K)
    m = c > 0
    f = np.interp(grid, grid[m], s[m] / c[m])
    return np.maximum.accumulate(f)
apply = lambda f, u: np.interp(np.clip(u, 0, 1) ** (1 / 2.2), grid, f)
def inv(f, y):
    return np.interp(y, f + np.arange(K) * 1e-9, grid) ** 2.2
def predict(L, M, fs):
    U = L @ M.T
    return np.stack([apply(fs[c], U[:, c]) for c in range(3)], 1)

def curves(L, Y, M, per_channel):
    U = L @ M.T
    return [fit_curve(U[:, c], Y[:, c]) for c in range(3)] if per_channel else [fit_curve(U.ravel(), Y.ravel())] * 3

def fit(L, Y, per_channel, use_M, iters=30, M0=None, white=False):
    """heuristic init (lstsq in inverse-curve space), then LM on M with Lab residuals, refitting curve(s).
    white: every row of M sums to 1 (as all 30 Leica matrices), so a clipped CCD highlight stays neutral."""
    P = (lambda M: M / M.sum(1, keepdims=True)) if white else (lambda M: M)
    labY = lab(Y)
    cost = lambda M, fs: np.mean((lab(predict(L, M, fs)) - labY) ** 2)
    M = np.eye(3) if M0 is None else M0
    fs = curves(L, Y, M, per_channel); best = cost(M, fs)
    for _ in range(20 if use_M else 0):
        Z = np.stack([inv(fs[c], Y[:, c]) for c in range(3)], 1)
        Mn = P(np.linalg.lstsq(L, Z, rcond=None)[0].T); fn = curves(L, Y, Mn, per_channel); c = cost(Mn, fn)
        if c < best:
            M, fs, best = Mn, fn, c
    lam = 1e-2
    for _ in range(iters if use_M else 0):
        r0 = (lab(predict(L, M, fs)) - labY).ravel()
        J = np.empty((r0.size, 9))
        for k in range(9):
            d = np.zeros(9); d[k] = 1e-4
            J[:, k] = ((lab(predict(L, M + d.reshape(3, 3), fs)) - labY).ravel() - r0) / 1e-4
        A = J.T @ J
        while lam < 1e6:
            step = np.linalg.solve(A + lam * np.diag(np.diag(A)), -J.T @ r0)
            Mn = P(M + step.reshape(3, 3)); fn = curves(L, Y, Mn, per_channel); c = cost(Mn, fn)
            if c < best:
                M, fs, best, lam = Mn, fn, c, lam / 3
                break
            lam *= 4
        else:
            break
    return M, fs, predict(L, M, fs)

def report(p):
    x, y = load(p)
    rng = np.random.default_rng(0)
    s = rng.choice(len(x), 60000, replace=False)
    xs, ys, L = x[s], y[s], lin(x[s])
    labT = lab(ys)
    # region masks on the *input* colour
    labI = lab(xs); C = np.hypot(labI[:, 1], labI[:, 2]); h = np.degrees(np.arctan2(labI[:, 2], labI[:, 1])) % 360
    skin = (C > 10) & (C < 40) & (h > 30) & (h < 70) & (labI[:, 0] > 40) & (labI[:, 0] < 85)
    sat = C > 50
    name = os.path.basename(p)[:-4]
    print(f'\n## {name}')
    ni = np.round(np.linspace(0, 1, 9) * (N - 1)).astype(int)
    print('neutral in -> out RGB:', '  '.join(f'{round(i/(N-1)*255)}->{tuple(int(v*255+.5) for v in y[i + i*N + i*N*N])}' for i in ni))
    M = None; res = {}
    for tag, pc, um, wh in [('curve only', False, False, False), ('curve+M', False, True, False),
                            ('curve+M white', False, True, True), ('3curves+M', True, True, False)]:
        M, fs, pred = fit(L, ys, pc, um, M0=None if not um or tag == 'curve+M' else M / M.sum(1, keepdims=True) if wh else M, white=wh)
        d = de2000(labT, lab(pred)); res[tag] = (M, fs, d)
        print(f'{tag:10s} dE00 median {np.median(d):5.2f}  p95 {np.percentile(d,95):5.2f}  skin {np.median(d[skin]):5.2f}  saturated {np.median(d[sat]):5.2f}')
        if um and not pc:
            print(f'  M = {np.array2string(M, precision=3, suppress_small=True)}  row sums {np.round(M.sum(1), 3)}'.replace('\n', ''))
    base = de2000(labT, labI)
    print(f'{"(no look)":10s} dE00 median {np.median(base):5.2f}  p95 {np.percentile(base,95):5.2f}  skin {np.median(base[skin]):5.2f}  saturated {np.median(base[sat]):5.2f}')
    M, fs, d = res['curve+M']
    bins = ['red 0-45', 'orange/skin 45-90', 'yellow/green 90-150', 'green/cyan 150-210', 'blue 210-270', 'purple/magenta 270-360']
    edges = [0, 45, 90, 150, 210, 270, 360]
    print('  curve+M median dE00 by input hue (C>30):', ', '.join(f'{b}: {np.median(d[(C>30)&(h>=lo)&(h<hi)]):.1f}' for b, lo, hi in zip(bins, edges, edges[1:])))
    Mw, fw, _ = res['curve+M white']
    np.savez(os.path.join(HERE, 'fits', f'fit_{name.replace(" ", "_")}.npz'), M=M, curve=fs[0], curve_only=res['curve only'][1][0],
             M_white=Mw, curve_white=fw[0], grid=grid,
             neutral_in=lin(np.arange(N) / (N - 1)), neutral_out=y[np.arange(N) * (1 + N + N * N)])

HERE = os.path.dirname(os.path.abspath(__file__))
if __name__ == '__main__':
    for p in sys.argv[1:] or sorted(glob.glob(os.path.join(HERE, 'clut', '*.png'))):
        report(p)
