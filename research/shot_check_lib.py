"""Shared by shot_check.py and look_id.py: a camera .RAW (14-bit DNG) as white-balanced linear RGB."""
import numpy as np, rawpy


def raw_rgb(path):
    """Half-size linear camera RGB, black subtracted, 0..1 = black..white, white-balanced (AsShotNeutral)."""
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
