#!/usr/bin/env python3
# cynes: dump 2KB RAM at the end of each frame that contained a joypad read (indexed by read count)
import sys, cynes
rom, fm2, out, nmax = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
data = bytearray(open(rom, 'rb').read())
base = 16 + 7 * 0x4000 - 0xC000
data[base + 0xC0F0: base + 0xC0F9] = bytes([0xEE, 0xFF, 0x07, 0xA2, 0x01, 0x8E, 0x16, 0x40, 0x60])
data[base + 0xC118: base + 0xC11D] = bytes([0x20, 0xF0, 0xC0, 0xEA, 0xEA])
open('/tmp/claude_patched.nes', 'wb').write(data)
frames = [l for l in open(fm2) if l.startswith('|')]
nes = cynes.NES('/tmp/claude_patched.nes')
res = bytearray(); reads = 0; last = 0
for l in frames:
    f = l.split('|')[2]; v = 0
    for i, ch in enumerate(f):
        if ch != '.': v |= 1 << i
    nes.controller = v
    nes.step()
    c = nes[0x07FF]; d = (c - last) & 0xFF; last = c
    if d:
        reads += d
        res += bytes(nes[a] for a in range(0x800))
        if reads >= nmax: break
open(out, 'wb').write(res)
