"""Emulator check of `m8lut.py build --raw-default [--ev-default T]` (factory settings template patches).

Runs the camera's real settings code (defaults 0x20F9C / 0x2174C, loader 0x21848, crc32) from the PXA
of the base and of the build, in gasdevmco's Unicorn harness (tools/m8_emutest.py of
github.com/gasdevmco/leica-m8-firmware; needs `unicorn`):

  /tmp/m8venv/bin/python research/settings_emutest.py BASE.upd BUILD.upd [--ev T] [--fw /path/to/leica-m8-firmware]

Expected: reset records get compression 5 (JPG fine+RAW) and exposure index 9+T (T thirds of a stop);
nothing else in the 0x400-byte block changes; a valid EEPROM keeps the owner's records 1-5, and only
record 0 (rebuilt from the template at every boot) takes the new defaults.
"""
import os, sys
a = sys.argv[1:]
opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d
base_path, build_path = a[0], a[1]
T_EV = int(opt('--ev', 0))
sys.path.insert(0, os.path.join(opt('--fw', '/tmp/m8fw'), 'tools'))
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

words = ['0x20ff4'] + (['0x20fe0'] if T_EV else [])
check('PXA differs only inside the patched words', sorted({hex(0x20000 + (i & ~3)) for i in diff}), sorted(words))
REC = lambda k: 0x1C + 0x50 * k
field = lambda blk, k, off: int.from_bytes(blk[REC(k) + off:REC(k) + off + 2], 'little')
comp = lambda blk, k: field(blk, k, 0x2C)
ev = lambda blk, k: field(blk, k, 0x22)
rest = lambda blk: blk[REC(1):REC(6)]
EV_NEW = 9 + T_EV
want_off = sorted(REC(k) + o for k in range(6) for o in ([0x2C] + ([0x22] if T_EV else [])))

# 1. EEPROM unreadable / bad CRC -> factory defaults for the whole block (as after a reset)
for label, ee in (('bad CRC', T.make_eeprom(B, 1, 1, crc_ok=False)), ('all zero', bytes(0x400))):
    rb, rn = T.run_loader(B, ee), T.run_loader(N, ee)
    check(f'{label}: base compression / EV in records 0-5', ([comp(rb['block'], k) for k in range(6)], [ev(rb['block'], k) for k in range(6)]), ([1] * 6, [9] * 6))
    check(f'{label}: build compression / EV in records 0-5', ([comp(rn['block'], k) for k in range(6)], [ev(rn['block'], k) for k in range(6)]), ([5] * 6, [EV_NEW] * 6))
    check(f'{label}: only the patched fields differ', [i for i in range(0x400) if rb['block'][i] != rn['block'][i]], want_off)
    check(f'{label}: same firmware calls', rn['calls'], rb['calls'])

# 2. A valid EEPROM keeps the owner's settings; only record 0 (rebuilt at every boot) changes
for prof, c in ((0, 1), (1, 1), (2, 3), (3, 5), (4, 1)):
    ee = T.make_eeprom(B, prof, c)
    rb, rn = T.run_loader(B, ee), T.run_loader(N, ee)
    check(f'valid EEPROM, profile {prof} comp {c}: active compression base/build',
          (rb['comp'], rn['comp']), (c, 5 if prof == 0 else c))
    check(f'valid EEPROM, profile {prof}: records 1-5 identical', rest(rb['block']) == rest(rn['block']), True)
    check(f'valid EEPROM, profile {prof}: record 0 compression / EV base vs build',
          ((comp(rb['block'], 0), ev(rb['block'], 0)), (comp(rn['block'], 0), ev(rn['block'], 0))), ((1, 9), (5, EV_NEW)))

print(f'\n{ok} passed, {bad} failed')
sys.exit(bad != 0)
