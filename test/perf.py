#!/usr/bin/env python3
"""normal play speed: logic frames in 6 s (360 vblanks) while swimming right in stage 1"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
from smsemu import *
S = {}
for l in open('build/main.sym'):
    m = re.match(r'(\S+): EQU 0x([0-9A-F]+)', l)
    if m: S[m.group(1)] = int(m.group(2), 16)
e = SMS(sys.argv[1] if len(sys.argv) > 1 else 'build/mermaid.sms')
e.run(400); e.run(3, PAUSE); e.run(200, 0); e.run(3, PAUSE); e.run(300, 0); e.run(120, RIGHT)
fc = lambda: int.from_bytes(e.ram(S['frame_cnt'], 2), 'little')
f0 = fc()
e.run(360, RIGHT)
print('logic frames in 6s:', fc() - f0, '(NES: 360)')
e.screenshot('test/out_perf.png')
