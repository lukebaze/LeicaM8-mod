"""Emulator check of `m8lut.py build --raw-default` (factory default Compression = JPG fine+RAW).

Runs the camera's real settings code (defaults 0x20F9C / 0x2174C, loader 0x21848, crc32) from the PXA
of the base and of the build, in gasdevmco's Unicorn harness (tools/m8_emutest.py of
github.com/gasdevmco/leica-m8-firmware; needs `unicorn`):

  /tmp/m8venv/bin/python research/settings_emutest.py BASE.upd BUILD.upd [/path/to/leica-m8-firmware]
"""
import os, sys
args = sys.argv[1:]
base_path, build_path = args[0], args[1]
sys.path.insert(0, os.path.join(args[2] if len(args) > 2 else '/tmp/m8fw', 'tools'))
import m8_emutest as T
from m8_rawpatch import find_lump

def pxa(path):
    d = open(path, 'rb').read(); o, n = find_lump(d, b'PXA'); return d[o:o + n]

B, N = pxa(base_path), pxa(build_path)
diff = [i for i in range(len(B)) if B[i] != N[i]]
ok = bad = 0
def check(label, got, want):
    global ok, bad
    good = got == want; ok += good; bad += not good
    print(f'{"ok  " if good else "FAIL"} {label}: {got!r}' + ('' if good else f' (want {want!r})'))

check('PXA differs only inside the word at 0x20FF4', sorted({hex(0x20000 + (i & ~3)) for i in diff}), ['0x20ff4'])
REC = lambda blk, k: blk[0x1C + 0x50 * k: 0x1C + 0x50 * (k + 1)]
comp = lambda blk, k: int.from_bytes(REC(blk, k)[0x2C:0x2E], 'little')
rest = lambda blk: blk[0x1C + 0x50:0x1C + 0x50 * 6]

# 1. EEPROM unreadable / bad CRC -> factory defaults for the whole block (as after a reset)
for label, ee in (('bad CRC', T.make_eeprom(B, 1, 1, crc_ok=False)), ('all zero', bytes(0x400))):
    rb, rn = T.run_loader(B, ee), T.run_loader(N, ee)
    check(f'{label}: base compression in records 0-5', [comp(rb['block'], k) for k in range(6)], [1] * 6)
    check(f'{label}: build compression in records 0-5', [comp(rn['block'], k) for k in range(6)], [5] * 6)
    other = [i for i in range(0x400) if rb['block'][i] != rn['block'][i]]
    check(f'{label}: only the compression bytes differ', other, sorted(0x1C + 0x50 * k + 0x2C for k in range(6)))
    check(f'{label}: same firmware calls', rn['calls'], rb['calls'])

# 2. A valid EEPROM keeps the owner's settings; only record 0 (rebuilt at every boot) changes
for prof, c in ((0, 1), (1, 1), (2, 3), (3, 5), (4, 1)):
    ee = T.make_eeprom(B, prof, c)
    rb, rn = T.run_loader(B, ee), T.run_loader(N, ee)
    check(f'valid EEPROM, profile {prof} comp {c}: active compression base/build',
          (rb['comp'], rn['comp']), (c, 5 if prof == 0 else c))
    check(f'valid EEPROM, profile {prof}: records 1-5 identical', rest(rb['block']) == rest(rn['block']), True)
    check(f'valid EEPROM, profile {prof}: record 0 compression base/build',
          (comp(rb['block'], 0), comp(rn['block'], 0)), (1, 5))

print(f'\n{ok} passed, {bad} failed')
sys.exit(bad != 0)
