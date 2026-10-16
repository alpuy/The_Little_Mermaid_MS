#!/usr/bin/env python3
"""scripted play: python3 test/play.py rom script
script: list of 'frames:pad' steps (pad names joined by +), 'shot:name' for screenshots"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
from smsemu import *
NAMES = {'U': UP, 'D': DOWN, 'L': LEFT, 'R': RIGHT, '1': B1, '2': B2, 'P': PAUSE, '-': 0}
S = {}
for l in open('build/main.sym'):
    m = re.match(r'(\S+): EQU 0x([0-9A-F]+)', l)
    if m: S[m.group(1)] = int(m.group(2), 16)
e = SMS(sys.argv[1])
for step in sys.argv[2:]:
    a, b = step.split(':')
    if a == 'shot':
        e.screenshot(f'test/out_{b}.png')
        continue
    pad = 0
    for ch in b:
        pad |= NAMES[ch]
    e.run(int(a), pad)
pc, sp = e.z80()
v = e.ram(S['VARS'], 0x30)
print('PC=%04X SP=%04X' % (pc, sp), 'emu frames', e.frames, 'game frames', int.from_bytes(v[0x1E:0x20], 'little'),
      'trap', v[0x1B:0x1E].hex(), 'stage', e.ram(0xC0E9)[0])
