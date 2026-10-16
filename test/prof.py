#!/usr/bin/env python3
"""Profile the TAS replay between reads A and B: python3 test/prof.py rom A B
Prints reads/second (speed) and the hottest runtime routines / NES code."""
import sys, os, re, ctypes as C, bisect, collections
sys.path.insert(0, os.path.dirname(__file__))
from smsemu import SMS
rom = sys.argv[1]; A = int(sys.argv[2]); B = int(sys.argv[3])
S = {}
for l in open('build/main.sym'):
    m = re.match(r'(\S+): EQU 0x([0-9A-F]+)', l)
    if m: S[m.group(1)] = int(m.group(2), 16)
# translated code: per page, z80 address -> NES address (from the listing)
maps = collections.defaultdict(list)
page = None
for l in open('build/main.lst', errors='replace'):
    m = re.match(r'# file opened: .*code_(\d+)\.asm', l)
    if m: page = int(m.group(1)); continue
    if l.startswith('# file closed'): page = None; continue
    if page is None: continue
    c = re.search(r';\s*((?:04|05|06|FF):[0-9A-F]{4})', l)
    a = re.match(r'^\s*\d+\+*\s*([0-9A-F]{4})\s', l)
    if c and a: maps[page].append((int(a.group(1), 16), c.group(1)))
for p in maps: maps[p].sort()
nesl = collections.defaultdict(list)
rx = re.compile(r'^([C-]) ([D-]) (.) (.) (.) (.) 0x([0-9A-F]{6}) ([0-9A-F]{2}):([0-9A-F]{4}):')
for b in ['04', '05', '06', 'FF']:
    pend = []
    for l in open(f'/home/user/nesdis/The Little Mermaid/bank_{b}.asm', encoding='utf-8'):
        m = rx.match(l)
        if m:
            for p in pend: nesl[b].append((int(m.group(9), 16), p))
            pend = []
        else:
            lm = re.match(r'^((?:sub|loc|ofs|vec|bra)_\w+):', l)
            if lm: pend.append(lm.group(1))
    nesl[b].sort()
rts = sorted((v, k) for k, v in S.items() if S['rt_start'] <= v < 0x8000 and '.' not in k and not k.startswith('codeend'))
e = SMS(rom); L = e.lib
cap = 30000; buf = (C.c_ubyte * (2048 * cap))()
C.c_void_p.in_dll(L, 'dbg_snap_buf').value = C.cast(buf, C.c_void_p).value
C.c_uint.in_dll(L, 'dbg_snap_cap').value = cap
C.c_uint.in_dll(L, 'dbg_snap_pc').value = S['read_input']
e.dbg_enable.value = 1
n = C.c_uint.in_dll(L, 'dbg_snap_n')
while n.value < A: e.run(1)
f0 = e.frames
e.profile_start(interval=1000, cap=2000000, tag_addr=S['cur_zbank'])
while n.value < B: e.run(1)
smp = e.profile_stop()
fr = e.frames - f0
print(f'reads {A}-{B}: {fr} frames, {(B - A) * 60 / fr:.1f} reads/s (NES: ~60)')
cnt = collections.Counter(); cnt2 = collections.Counter()
for pc, tag in smp:
    if S['rt_start'] <= pc < 0x8000:
        i = bisect.bisect_right(rts, (pc, '~')) - 1
        cnt['RT ' + rts[i][1]] += 1
    elif 0x4000 <= pc < S['rt_start'] and maps.get(tag):
        i = bisect.bisect_right(maps[tag], (pc, '~')) - 1
        k = maps[tag][max(i, 0)][1]
        b, a = k.split(':'); a = int(a, 16)
        j = bisect.bisect_right(nesl[b], (a, '~')) - 1
        cnt[nesl[b][j][1] if j >= 0 else k] += 1
        cnt2[k] += 1
    else:
        cnt['other %04X' % (pc & 0xFF00)] += 1
tot = len(smp)
for k, v in cnt.most_common(int(sys.argv[4]) if len(sys.argv) > 4 else 30):
    print(f'{v * 100 / tot:5.1f}% {k}')
