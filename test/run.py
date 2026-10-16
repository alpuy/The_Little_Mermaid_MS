#!/usr/bin/env python3
"""quick run: python3 test/run.py rom frames [shot-frames...]"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from smsemu import *
import re
S = {}
for l in open('build/main.sym'):
    m = re.match(r'(\S+): EQU 0x([0-9A-F]+)', l)
    if m: S[m.group(1)] = int(m.group(2), 16)
e = SMS(sys.argv[1])
n = int(sys.argv[2])
shots = set(int(x) for x in sys.argv[3:])
for f in range(n):
    e.run(1)
    if f in shots:
        e.screenshot(f'test/out_{f}.png')
pc, sp = e.z80()
v = e.ram(S['VARS'], 0x30)
print('PC=%04X SP=%04X' % (pc, sp), 'frames', int.from_bytes(v[0x1E:0x20], 'little'), 'trap', v[0x1B:0x1E].hex(), 'zbank', v[0], 'vbl', v[0x20])
