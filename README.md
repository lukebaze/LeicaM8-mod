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
- Biến thể B = biến thể A với cột G và B của **hàng đỏ** đổi chỗ (vd #14/#15). Ý nghĩa chưa rõ.
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
python3 tools/m8lut.py look Kodak_Portra_160_2      # build/m8-2_014-kodak_portra_160_2.upd
python3 tools/m8lut.py look Kodak_Kodachrome_64
python3 tools/m8lut.py look Kodak_Kodachrome_200
python3 research/ccd_check.py build/X.upd "research/clut/<film>.png" ...   # số đo + build/preview.png
```

Chỉ sửa không gian **sRGB** (ma trận #10–19, đường cong 5–9). Adobe RGB / ECI RGB giữ màu Leica gốc,
nên đổi Color space là về màu gốc, không cần flash lại. Saturation và Contrast vẫn hoạt động.

Tương thích cảm biến CCD (KAF-10500):

- **Ma trận = M_look · ma trận gốc của Leica**: giữ nguyên chuyển đổi cam→sRGB riêng của CCD, look
  chỉ chồng lên trên.
- **Tone lấy từ trục xám của film**, mid-grey đặt đúng 147 như Leica (đo sáng của M8 tính theo mức này).
- **Shoulder**: trên mid-grey, gain giảm dần về 1.0 tại điểm CCD clip → 255 chỉ ở chỗ cảm biến clip,
  không bỏ vùng highlight CCD còn giữ. Highlight clip hoàn toàn vẫn trung tính.
- Không khuếch đại noise vùng tối (CCD nhiều noise ở ISO cao), không tăng ám magenta do IR.

| Build | ΔE00 vs CLUT | clip (cam 1,1,1) | noise tối 1% | noise 18% | chroma IR |
|---|---|---|---|---|---|
| Leica gốc | | 255,255,255 | 1.00 | 1.00 | 25.5 |
| Portra 160 | 3.3 | 255,255,255 | 0.70 | 0.55 | 18.2 |
| Kodachrome 64 | 5.0 | 254,254,254 | 0.76 | 0.70 | 17.0 |
| Kodachrome 200 | 3.7 | 254,254,254 | 0.67 | 0.81 | 17.2 |

Noise = độ khuếch đại so với Leica gốc. Chroma IR là **giả định** (IR lọt vào R và B nhiều hơn G); vẫn
nên dùng filter UV/IR. ΔE cao hơn lúc fit (3.2 / 4.0) vì shoulder cố ý khác CLUT ở vùng highlight.

![preview](docs/preview.png)

Lưu ý: cả hai CLUT Kodachrome của RawTherapee đều làm **vàng nhạt** (vàng 231,199,31 → 255,217,124) và
trung tông hơi magenta; build làm đúng theo CLUT. Muốn vàng đậm kiểu Kodachrome thật cần nguồn look khác.

## Thử 1: Blackfin có dùng ma trận không?

```sh
python3 tools/m8lut.py bw-test     # build/m8-2_014-bwtest.upd: #14 và #15 -> đen trắng, 36 byte
```

1. Pin đầy; thẻ thứ hai chỉ chứa `m8-2_014.upd` gốc để rollback.
2. Chép file build vào thẻ, **đổi tên trên thẻ thành `M8-2_014.UPD`**, cập nhật firmware như bình thường.
3. Đặt Color space **sRGB**, Saturation **Standard**, chụp JPG một cảnh nhiều màu.
4. JPG đen trắng → ma trận được dùng. Không đổi → ghi lại, flash gốc.
