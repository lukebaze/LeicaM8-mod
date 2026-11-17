# LeicaM8

[Tiếng Việt](README.md)

Custom JPG colour (Portra, Kodachrome…) for the Leica M8, firmware 2.014, by editing `LUTS/GAMMA`
(tone curves + colour matrices). `PXA` is never touched, so the bootloader and the SD-card updater
stay stock.

Builds on [gasdevmco/leica-m8-firmware](https://github.com/gasdevmco/leica-m8-firmware) (MIT):
the `.upd` format, and GAMMA tone curves proven on a camera.

**Never commit Leica firmware.** `firmware/stock/m8-2_014.upd` (SHA-256 `99f52548…09ed0`, source:
`fichiers.touslesdrivers.com/38007/m8-2_014.zip`) and `build/` are git-ignored.

## Colour matrices (GAMMA + 0x1D0): static analysis, not yet camera-tested

- 30 3×3 matrices, int16 Q13 (8192 = 1.0); every row sums to 1.0, i.e. post-white-balance
  matrices. Two trailing int16 (`1742, 5858`) of unknown purpose.
- Index = 10·colour space + 2·saturation + variant. Space 1 = sRGB (largest determinants; 0/2 assumed
  Adobe/ECI, matching the tone-curve row order). Saturation 0..4 = Low..High (determinant rises
  monotonically).
- Variant B = variant A with the G and B coefficients of the **red row** swapped (e.g. #14/#15).
  Meaning unknown.
- #14 (sRGB Standard) is the closest to the camera→sRGB matrix derived from dcraw/Adobe's M8
  coefficients.

## Look research (`research/film_fit.py`)

Fits the RawTherapee HaldCLUTs (CC BY-SA 4.0) with the M8's model `curve(M · linear)`. Median ΔE00:

| Film | curve only | curve + matrix |
|---|---|---|
| Portra 160 | 5.6 | 3.2 |
| Portra 400 NC | 7.0 | 3.8 |
| Kodachrome 64 | 9.2 | 4.0 |
| Kodachrome 200 | 8.3 | 2.6 |
| Kodachrome 25 | 9.5 | 7.7 (dropped) |

A curve alone barely produces the looks; the matrix carries most of them. Per-channel curves add
nothing. Fit results: `research/fits/*.npz` (`M`, `curve` on the grid v = u^(1/2.2)).

## Test 1: does the Blackfin use the matrices?

```sh
python3 tools/m8lut.py bw-test     # build/m8-2_014-bwtest.upd: #14 and #15 -> monochrome, 36 bytes
python3 tools/m8lut.py dump        # print all 30 matrices
```

1. Full battery; a second card holding only the stock `m8-2_014.upd` for rollback.
2. Copy the build to a card, **rename it on the card to `M8-2_014.UPD`**, run the normal firmware update.
3. Set Colour space **sRGB**, Saturation **Standard**, shoot a JPG of a colourful scene.
4. Monochrome JPG → the matrices are used. No change → note it, flash stock back.
