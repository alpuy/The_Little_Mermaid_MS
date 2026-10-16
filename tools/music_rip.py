#!/usr/bin/env python3
"""Run the NES sound engine (bank 05) offline for every music id and record,
per sound tick, the APU registers it writes, until the song loops.

usage: music_rip.py prg.bin out.inc [stats]
The output is an sjasmplus include with one compressed stream per song
(format: see src/music.asm)."""
import sys, hashlib
from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

PRG = open(sys.argv[1], 'rb').read()
BANK05 = PRG[5 * 0x4000:6 * 0x4000]
NSONGS = 13                       # music ids 00-0C
MAXFRAMES = 40000
SENTINEL = 0xFFF0

def new_machine():
    mem = ObservableMemory()
    for i in range(0x4000):
        mem[0x8000 + i] = BANK05[i]
    writes = []
    def apu_w(addr, val):
        writes.append((addr - 0x4000, val))
    mem.subscribe_to_write(range(0x4000, 0x4018), apu_w)
    mpu = MPU(memory=mem)
    return mpu, mem, writes

def call(mpu, addr, a=0):
    # push return address SENTINEL-1 (RTS adds 1)
    ret = SENTINEL - 1
    mpu.memory[0x100 + mpu.sp] = ret >> 8; mpu.sp -= 1
    mpu.memory[0x100 + mpu.sp] = ret & 0xFF; mpu.sp -= 1
    mpu.a = a
    mpu.pc = addr
    n = 0
    while mpu.pc != SENTINEL:
        mpu.step()
        n += 1
        if n > 200000:
            raise RuntimeError('runaway at %04X' % mpu.pc)

NFRAMES = 40000

def chan_key(mem, c):
    # channel data pointer (0750/0754 + X, X = 3 - c) + shared tempo accumulator
    x = 3 - c
    return (mem[0x750 + x], mem[0x754 + x], mem[0xC8])

def rip(song):
    """returns (per-tick write lists, per channel (loop, end))"""
    mpu, mem, writes = new_machine()
    mpu.sp = 0xFF
    call(mpu, 0x8003, 0xF0)       # engine reset (as the game does)
    writes.clear()
    call(mpu, 0x8003, song)
    first = list(writes)          # writes made when the song starts
    writes.clear()
    frames = []
    keys = [[chan_key(mem, c)] for c in range(4)]
    late4015 = 0
    for f in range(1, NFRAMES + 1):
        call(mpu, 0x8000)
        w = list(writes); writes.clear()
        if any(r == 0x15 for r, v in w):
            late4015 += 1
        if f == 1:
            w = first + w
        frames.append(w)
        for c in range(4):
            keys[c].append(chan_key(mem, c))
    loops = []
    for c in range(4):
        k = [kk[:2] for kk in keys[c]]       # data pointer after tick f
        ev = [(0, k[0])]                     # (tick, pointer) at every pointer change
        for f in range(1, NFRAMES + 1):
            if k[f] != k[f - 1]:
                ev.append((f, k[f]))
        best = None
        if ev[-1][1] == (0, 0) or len(ev) < 4:
            # the channel stops (or never plays): loop on one silent tick after its last write
            last = max([f + 1 for f in range(NFRAMES) if any(c * 4 <= r < c * 4 + 4 for r, v in frames[f])] + [1])
            best = (last, last + 1)
        else:
            ptrs = [p for t, p in ev]
            n = len(ptrs)
            # smallest j with some i < j such that the pointer sequence from i
            # equals the one from j until the end of the recording (>= 1 period)
            for j in range(1, n):
                for i in range(j):
                    if ptrs[i] == ptrs[j] and n - j >= j - i and ptrs[i:n - (j - i)] == ptrs[j:n]:
                        best = (ev[i][0], ev[j][0])
                        break
                if best:
                    break
        if not best:
            raise RuntimeError('song %02X channel %d: no loop' % (song, c))
        loops.append(best)
    return frames, loops, late4015

# per channel: final value of each of its 4 registers written during the tick.
# the 4th register (length / trigger) counts as written even with the same value;
# the others only when the value changes.
def chan_deltas(frames, c, loop, end):
    def run(fr, sh):
        regs = {}
        for r, v in fr:
            if c * 4 <= r < c * 4 + 4:
                regs[r - c * 4] = v
        d = {}
        for r, v in regs.items():
            if r == 3 or sh.get(r) != v:
                d[r] = v
            sh[r] = v
        return d
    sh = {}
    out = [run(fr, sh) for fr in frames[:end]]
    # the looped part is re-run with the shadow as it is at the loop end
    redo = [run(fr, sh) for fr in frames[loop:end]]
    return out[:loop], redo

# ---- encoding, one stream per channel
#   1-15        register mask, followed by the values of those registers (one tick)
#   80h+n       n (1-127) ticks without writes
#   0FFh        end: continue at the loop point
def encode(deltas):
    out = []
    i = 0
    while i < len(deltas):
        d = deltas[i]
        if not d:
            n = 0
            while i < len(deltas) and not deltas[i] and n < 127:
                n += 1; i += 1
            out.append(0x80 + n)
            continue
        rm = 0
        vals = []
        for k in range(4):
            if k in d:
                rm |= 1 << k
                vals.append(d[k])
        out.append(rm)
        out.extend(vals)
        i += 1
    return out

def main():
    stats = len(sys.argv) > 3
    total = 0
    with open(sys.argv[2], 'w') as f:
        f.write('; generated by tools/music_rip.py from the NES ROM (not distributed)\n')
        f.write('mus_table:\n')
        for s in range(NSONGS):
            for c in range(4):
                f.write('    db $$mus_%02X_%d\n    dw mus_%02X_%d\n' % (s, c, s, c))
        for s in range(NSONGS):
            frames, loops, late = rip(s)
            if stats:
                print('song %02X: loops %s, late 4015 writes %d' % (s, loops, late))
            for c in range(4):
                loop, end = loops[c]
                intro, body = chan_deltas(frames, c, loop, end)
                a = encode(intro); b = encode(body)
                total += len(a) + len(b) + 1
                f.write('mus_%02X_%d:\n' % (s, c))
                for k in range(0, len(a), 32):
                    f.write('    db ' + ','.join(str(x) for x in a[k:k + 32]) + '\n')
                f.write('mus_%02X_%d_loop:\n' % (s, c))
                for k in range(0, len(b), 32):
                    f.write('    db ' + ','.join(str(x) for x in b[k:k + 32]) + '\n')
                f.write('    db 0FFh, $$mus_%02X_%d_loop\n    dw mus_%02X_%d_loop\n' % (s, c, s, c))
    if stats:
        print('total', total)

main()
