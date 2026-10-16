#!/usr/bin/env python3
"""screenshots of the TAS replay at given read counts: tas_shot.py rom read1 read2 ..."""
import sys, os, re, ctypes as C
sys.path.insert(0, os.path.dirname(__file__))
from smsemu import SMS
S = {}
for l in open('build/main.sym'):
    m = re.match(r'(\S+): EQU 0x([0-9A-F]+)', l)
    if m: S[m.group(1)] = int(m.group(2), 16)
e = SMS(sys.argv[1])
L = e.lib
cap = 30000
buf = (C.c_ubyte * (2048 * cap))()
C.c_void_p.in_dll(L, 'dbg_snap_buf').value = C.cast(buf, C.c_void_p).value
C.c_uint.in_dll(L, 'dbg_snap_cap').value = cap
C.c_uint.in_dll(L, 'dbg_snap_pc').value = S['read_input']
e.dbg_enable.value = 1
n = C.c_uint.in_dll(L, 'dbg_snap_n')
for t in sorted(int(x) for x in sys.argv[2:]):
    while n.value < t:
        e.run(1)
    e.screenshot(f'test/out_tas_{t}.png')
    print(t, 'frame', e.frames)
