# LeicaM8

[English](README.en.md)

Màu JPG tuỳ biến (Portra, Kodachrome…) cho Leica M8, firmware 2.014, bằng cách sửa `LUTS/GAMMA`
(đường cong tone + ma trận màu). Không đụng `PXA`, nên không chạm bootloader/updater.

Dựa trên [gasdevmco/leica-m8-firmware](https://github.com/gasdevmco/leica-m8-firmware) (MIT):
định dạng `.upd`, đường cong GAMMA đã được chứng minh trên máy thật.

**Không commit firmware Leica.** `firmware/stock/m8-2_014.upd` (SHA-256 `99f52548…09ed0`, nguồn:
`fichiers.touslesdrivers.com/38007/m8-2_014.zip`) và `build/` bị gitignore.

## Ma trận màu (GAMMA + 0x1D0) — tĩnh, chưa thử trên máy

- 30 ma trận 3×3 int16 Q13 (8192 = 1.0); mọi hàng cộng = 1.0 → ma trận sau WB. Thêm 2 int16 cuối
  (`1742, 5858`) chưa rõ.
- Chỉ số = 10·không gian màu + 2·bão hoà + biến thể. Không gian 1 = sRGB (định thức lớn nhất; 0/2 đoán
  Adobe/ECI theo thứ tự hàng đường cong). Bão hoà 0..4 = Low..High (định thức tăng đơn điệu).
- Biến thể B: ở mức Standard đúng bằng biến thể A với cột G và B của **hàng đỏ** đổi chỗ (#14/#15); các mức
  khác lệch thêm. Ý nghĩa chưa rõ, nên build biến đổi từng ma trận riêng, không giả định quan hệ A/B.
- #14 (sRGB Standard) gần nhất với ma trận cam→sRGB tính từ hệ số M8 của dcraw/Adobe.

## Nghiên cứu look (`research/film_fit.py`)

Fit HaldCLUT RawTherapee (CC BY-SA 4.0) bằng mô hình của M8 `curve(M · linear)`. Trung vị ΔE00:

| Film | chỉ curve | curve + ma trận |
|---|---|---|
| Portra 160 | 5.6 | 3.2 |
| Portra 400 NC | 7.0 | 3.8 |
| Kodachrome 64 | 9.2 | 4.0 |
| Kodachrome 200 | 8.3 | 2.6 |
| Kodachrome 25 | 9.5 | 7.7 (bỏ) |

Kết quả fit: `research/fits/*.npz` (`M`, `curve` trên lưới v = u^(1/2.2)).

## Profile màu (đã build, chưa flash, chưa thử trên máy)

```sh
research/.venv/bin/python research/spectral_gen.py   # look từ datasheet Kodak -> research/clut/SFL *.npz
python3 research/film_fit.py "research/clut/SFL Kodachrome 64.npz" "research/clut/SFL Portra 160 Endura.npz"
python3 tools/m8lut.py build --srgb SFL_Portra_160_Endura          # một look, trên firmware gốc
python3 tools/m8lut.py build --base firmware/dng/m8-2_014-patched.upd \
    --srgb SFL_Kodachrome_64 --adobe SFL_Portra_160_Endura --out m8-2_014-dng14-kodachrome-portra.upd
python3 research/ccd_check.py build/X.upd "research/clut/<look>.npz" ...   # số đo + build/preview.png
```

**Nguồn look:** [Spectral Film LUT](https://github.com/JanLohse/spectral_film_lut) (MIT): datasheet Kodak
đã số hoá (độ nhạy phổ, đường đặc tuyến, mật độ phổ thuốc nhuộm) → mô phỏng phổ cảnh → film (→ giấy in).
Kodachrome 64 (slide, cân bằng theo trắng của slide, xem ở D65); Portra 160 in trên Kodak Portra Endura.
Input là ánh sáng cảnh (scene-linear), khớp đúng đầu vào của pipeline M8. Bộ CLUT RawTherapee cũ chỉ còn
để tham khảo (Kodachrome bị vàng nhạt).

**Đối chiếu độc lập** (`research/spk_crosscheck.py`, chạy trong `research/.venv-spk`): cùng 24 ô
ColorChecker qua [spektrafilm](https://github.com/andreavolpato/spektrafilm) (GPL-3, mô phỏng phổ khác,
cũng từ datasheet): trung vị ΔE76 giữa hai bộ mô phỏng 5.6 (Kodachrome 64), 9.6 (Portra 160 + Endura;
spektrafilm cho da ấm và magenta rực hơn). Hai nguồn độc lập cùng hướng → look có cơ sở.

Mỗi Color space trong menu là một bộ ma trận + đường cong riêng, nên **một bản flash chứa được 3 look**:
look định nghĩa trong sRGB tuyến tính, áp lên rendering Leica của chính không gian đó
(`T · M_look · T⁻¹ · ma trận Leica`), đường cong mã hoá lại theo gamma của không gian (Adobe 2.2, ECI 1.8).
Saturation và Contrast vẫn hoạt động. JPG Adobe/ECI mang ICC profile riêng (gasdevmco FINDINGS), xem
bằng app có quản lý màu.

### Bản kết hợp: 14-bit DNG + Portra + Kodachrome

`build/m8-2_014-dng14-kodachrome-portra.upd` (SHA-256 `377f544d…01ad81`):

| Color space | JPG |
|---|---|
| sRGB | Kodachrome 64 |
| Adobe RGB | Portra 160 (Endura) |
| ECI RGB | Leica gốc |

- Base = build `9b9a489a…` của [gasdevmco/leica-m8-firmware](https://github.com/gasdevmco/leica-m8-firmware)
  v0.10.0 (`python3 m8patch.py m8-2_014.upd`): JPG fine+RAW giữ được + DNG 14-bit trong máy. Patch đó
  chỉ đổi `PXA`, profile màu chỉ đổi `GAMMA` → không chồng nhau. `m8lut.py` chỉ nhận base có hash nằm
  trong danh sách build công bố của dự án đó và GAMMA của base phải là gốc.
- Đã kiểm: PXA = base từng byte; GAMMA = hợp của 2 build đơn từng byte; ECI giữ gốc; mọi phần khác = gốc.
  Look ở slot Adobe giải mã về sRGB lệch trung vị ΔE00 2.0 so với slot sRGB — cùng cỡ với chính
  Leica (Adobe vs sRGB gốc: 2.3), vì Leica tự chỉnh riêng từng không gian.
- DNG 14-bit là dữ liệu cảm biến thô: không bị profile ảnh hưởng. Đã có tiền lệ trên máy thật: Stage 12
  của gasdevmco (đường cong GAMMA bake + patch PXA) chạy tốt; ma trận thì chưa (xem Thử 1).

Tương thích cảm biến CCD (KAF-10500):

- **Ma trận = M_look · ma trận gốc của Leica**, hàng cộng = 1 như cả 30 ma trận Leica: xám vẫn xám (AWB
  của máy vẫn đúng), highlight CCD clip vẫn trung tính.
- **Tone lấy từ trục xám của film**, bù điểm đen (Dmax → 0) như ICC perceptual; mid-grey đặt đúng 147
  như Leica (đo sáng của M8 tính theo mức này).
- **Shoulder**: trên mid-grey, gain giảm dần về 1.0 tại điểm CCD clip → 255 chỉ ở chỗ cảm biến clip.
- Không khuếch đại noise vùng tối, không tăng ám magenta do IR.

| Build | ΔE00 vs nguồn | clip (cam 1,1,1) | noise tối 1% | noise 18% | chroma IR |
|---|---|---|---|---|---|
| Leica gốc | | 255,255,255 | 1.00 | 1.00 | 25.5 |
| Portra 160 (Endura) | 4.3 | 255,255,255 | 0.22 | 0.76 | 12.1 |
| Kodachrome 64 | 5.0 | 255,255,255 | 0.35 | 0.80 | 17.3 |

Khác biệt so với Leica gốc trên ColorChecker: trung vị ΔE00 8.2 (Portra), 6.0 (Kodachrome), xám giữ
nguyên. Cả hai đều **dịu hơn** sRGB Standard của Leica (vốn rất rực). So sánh nửa-nửa: `docs/compare.png`.

Noise = độ khuếch đại so với Leica gốc. Chroma IR là **giả định** (IR lọt vào R và B nhiều hơn G); vẫn
nên dùng filter UV/IR. Giới hạn của ma trận 3×3: vàng/xanh dương Kodachrome nhạt hơn mô phỏng
(vàng film 244,220,84 → M8 222,209,110).

![so sánh](docs/compare.png)

![preview](docs/preview.png)

## Thử 1: Blackfin có dùng ma trận không?

```sh
python3 tools/m8lut.py bw-test     # build/m8-2_014-bwtest.upd: #14 và #15 -> đen trắng, 36 byte
```

1. Pin đầy; thẻ thứ hai chỉ chứa `m8-2_014.upd` gốc để rollback.
2. Chép file build vào thẻ, **đổi tên trên thẻ thành `M8-2_014.UPD`**, cập nhật firmware như bình thường.
3. Đặt Color space **sRGB**, Saturation **Standard**, chụp JPG một cảnh nhiều màu.
4. JPG đen trắng → ma trận được dùng. Không đổi → ghi lại, flash gốc.
