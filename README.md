# LeicaM8

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

## Thử 1: Blackfin có dùng ma trận không?

```sh
python3 tools/m8lut.py bw-test     # build/m8-2_014-bwtest.upd: #14 và #15 -> đen trắng, 36 byte
```

1. Pin đầy; thẻ thứ hai chỉ chứa `m8-2_014.upd` gốc để rollback.
2. Chép file build vào thẻ, **đổi tên trên thẻ thành `M8-2_014.UPD`**, cập nhật firmware như bình thường.
3. Đặt Color space **sRGB**, Saturation **Standard**, chụp JPG một cảnh nhiều màu.
4. JPG đen trắng → ma trận được dùng. Không đổi → ghi lại, flash gốc.
