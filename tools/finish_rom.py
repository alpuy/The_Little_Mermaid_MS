#!/usr/bin/env python3
"""Post-process the assembled ROM: copy the runtime block (RT_BASE..7FFF of the
first code page) into every code page, trim to the used size and set the SMS
header checksum (32KB range)."""
import sys, re
rom, sym = sys.argv[1], sys.argv[2]
S = {}
for l in open(sym):
    m = re.match(r'(\S+): EQU 0x([0-9A-F]+)', l)
    if m: S[m.group(1)] = int(m.group(2), 16)
d = bytearray(open(rom, 'rb').read())
first, last, rt = S['FIRST_CODE_PAGE'], S['LAST_CODE_PAGE'], S['RT_BASE']
blk = d[first * 0x4000 + (rt - 0x4000): (first + 1) * 0x4000]
for p in range(first + 1, last + 1):
    d[p * 0x4000 + (rt - 0x4000): (p + 1) * 0x4000] = blk
size = 0x40000 if 'TAS_LEN' not in S else 0x80000
d = d[:size]
cs = sum(d[0:0x7FF0]) & 0xFFFF
d[0x7FFA] = cs & 0xFF
d[0x7FFB] = cs >> 8
open(rom, 'wb').write(d)
print(f'runtime {S["rt_end"] - rt} bytes, ROM {len(d) // 1024}KB')
