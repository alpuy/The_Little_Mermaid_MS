#!/usr/bin/env python3
"""Run an FCEUX .fm2 movie on the original NES ROM (cynes) and record the joypad value
seen by every call of the game's read_joy routine. Output: one byte per read, in the
MSX runtime's bit order (b0 A, b1 B, b2 Select, b3 Start, b4 Up, b5 Down, b6 Left, b7 Right)."""
import sys, cynes
from PIL import Image
rom, fm2, out = sys.argv[1], sys.argv[2], sys.argv[3]
data = bytearray(open(rom, 'rb').read())
base = 16 + 7 * 0x4000 - 0xC000           # file offset of bank FF address
patch = bytes([0xEE, 0xFF, 0x07, 0xA2, 0x01, 0x8E, 0x16, 0x40, 0x60])
data[base + 0xC0F0: base + 0xC0F0 + len(patch)] = patch
assert data[base + 0xC118: base + 0xC11D] == bytes([0xA2, 0x01, 0x8E, 0x16, 0x40])
data[base + 0xC118: base + 0xC11D] = bytes([0x20, 0xF0, 0xC0, 0xEA, 0xEA])
open('/tmp/claude_patched.nes', 'wb').write(data)
frames = [l for l in open(fm2) if l.startswith('|')]
nes = cynes.NES('/tmp/claude_patched.nes')
reads = bytearray()
last = 0
shots = [int(x) for x in sys.argv[4:]]
for n, l in enumerate(frames):
    f = l.split('|')[2]
    v = 0
    for i, ch in enumerate(f):
        if ch != '.': v |= 1 << i
    nes.controller = v
    fb = nes.step()
    c = nes[0x07FF]
    d = (c - last) & 0xFF
    last = c
    rv = int(f'{v:08b}'[::-1], 2)   # bit reversal -> msx order
    for _ in range(d): reads.append(rv)
    if n in shots:
        Image.fromarray(fb).save(f'{out}.{n}.png')
open(out, 'wb').write(reads)
print('frames', len(frames), 'reads', len(reads), 'stage', nes[0xE9])
