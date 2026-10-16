#!/usr/bin/env python3
"""Replay the TAS on the SMS port (ROM built with TAS=tas/tas1.bin) and compare key game
variables at every joypad read with a reference run of the NES original
(tools/tas_ramlog.py -> /tmp/claude_cy_ram.bin)."""
import sys, os, re, ctypes as C
sys.path.insert(0, os.path.dirname(__file__))
from smsemu import SMS
rom = sys.argv[1] if len(sys.argv) > 1 else 'build/mermaid_tas.sms'
ref = sys.argv[2] if len(sys.argv) > 2 else '/tmp/claude_cy_ram.bin'
S = {}
for l in open('build/main.sym'):
    m = re.match(r'(\S+): EQU 0x([0-9A-F]+)', l)
    if m: S[m.group(1)] = int(m.group(2), 16)
cy = open(ref, 'rb').read()
nref = len(cy) // 2048
e = SMS(rom)
L = e.lib
buf = (C.c_ubyte * (2048 * (nref + 16)))()
C.c_void_p.in_dll(L, 'dbg_snap_buf').value = C.cast(buf, C.c_void_p).value
C.c_uint.in_dll(L, 'dbg_snap_cap').value = nref + 16
C.c_uint.in_dll(L, 'dbg_snap_pc').value = S['read_input']
e.dbg_enable.value = 1
n = C.c_uint.in_dll(L, 'dbg_snap_n')
frames = 0
while n.value < nref and frames < 60 * 60 * 25:
    e.run(60)
    frames += 60
ms = bytes(buf)[:n.value * 2048]
print('emulated frames', frames, 'reads', n.value, 'of', nref)
keys = [0xE9, 0x330, 0x340, 0x360, 0x370, 0xFC, 0xFD, 0xFA, 0xB1, 0xB0]
def kc(k): return bytes(cy[k * 2048 + a] for a in keys)
def km(k): return bytes(ms[k * 2048 + a] for a in keys)
m = min(nref, n.value)
run = 0
for k in range(3, m - 4):
    ok = any(kc(k) == km(k + d) for d in range(-2, 4))
    run = 0 if ok else run + 1
    if run == 30:
        print('DESYNC at read', k - 29, 'of', nref)
        break
else:
    print('SYNC OK up to read', m, 'of', nref)
if len(sys.argv) > 3:
    open(sys.argv[3], 'wb').write(ms)
