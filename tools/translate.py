#!/usr/bin/env python3
"""
Static recompiler: The Little Mermaid (NES, 6502 disassembly by cyneprepou4uk) -> Z80 (Sega Master System).

Register mapping:   6502 A -> Z80 A,  X -> C (B always 0),  Y -> E (D always 0)
                    HL = scratch, IX/IY/AF' scratch for index caches and the runtime.
Memory map:         NES RAM $0000-$07FF  -> Z80 $C000-$C7FF (SMS RAM)
                    NES switchable bank $8000-$BFFF -> Z80 $8000-$BFFF (Sega mapper slot 2, raw bank)
                    NES fixed bank $C000-$FFFF -> Z80 $0000-$3FFF (ROM page 0, slot 0)
                    Static addresses are remapped at translation time; (zp),Y pointers at run time.
Stack:              6502 S is mirrored by Z80 SP = $C100 + S + 1, JSR/RTS -> CALL/RET.
Data:               never translated, NES banks are kept byte-identical.
Flags:              C and N/Z are tracked with a global liveness analysis; V is never consumed
                    by the game so it is ignored.

Outputs one .asm file per Z80 code bank plus a symbol include.
"""
import re, sys, os, collections, json

SRC = sys.argv[1]          # directory with original bank_XX.asm files
OUT = sys.argv[2]          # output dir
os.makedirs(OUT, exist_ok=True)

CODE_BANKS = ['04', '05', '06', 'FF']
ALL_BANKS = ['00', '01', '02', '03', '04', '05', '06', 'FF']

rx_line = re.compile(r'^([C-]) ([D-]) (.) (.) (.) (.) 0x([0-9A-F]{6}) ([0-9A-F]{2}):([0-9A-F]{4}): (.{9})\s*(.*)$')
rx_label = re.compile(r'^([A-Za-z_@][A-Za-z0-9_]*):')

# ---------------------------------------------------------------- 6502 opcode table
MODES = {}
def op(code, mn, mode): MODES[code] = (mn, mode)
_tab = """
69 ADC imm;65 ADC zp;75 ADC zpx;6D ADC abs;7D ADC absx;79 ADC absy;61 ADC indx;71 ADC indy
29 AND imm;25 AND zp;35 AND zpx;2D AND abs;3D AND absx;39 AND absy;21 AND indx;31 AND indy
0A ASL acc;06 ASL zp;16 ASL zpx;0E ASL abs;1E ASL absx
90 BCC rel;B0 BCS rel;F0 BEQ rel;30 BMI rel;D0 BNE rel;10 BPL rel;50 BVC rel;70 BVS rel
24 BIT zp;2C BIT abs;00 BRK imp
18 CLC imp;D8 CLD imp;58 CLI imp;B8 CLV imp
C9 CMP imm;C5 CMP zp;D5 CMP zpx;CD CMP abs;DD CMP absx;D9 CMP absy;C1 CMP indx;D1 CMP indy
E0 CPX imm;E4 CPX zp;EC CPX abs;C0 CPY imm;C4 CPY zp;CC CPY abs
C6 DEC zp;D6 DEC zpx;CE DEC abs;DE DEC absx;CA DEX imp;88 DEY imp
49 EOR imm;45 EOR zp;55 EOR zpx;4D EOR abs;5D EOR absx;59 EOR absy;41 EOR indx;51 EOR indy
E6 INC zp;F6 INC zpx;EE INC abs;FE INC absx;E8 INX imp;C8 INY imp
4C JMP abs;6C JMP ind;20 JSR abs
A9 LDA imm;A5 LDA zp;B5 LDA zpx;AD LDA abs;BD LDA absx;B9 LDA absy;A1 LDA indx;B1 LDA indy
A2 LDX imm;A6 LDX zp;B6 LDX zpy;AE LDX abs;BE LDX absy
A0 LDY imm;A4 LDY zp;B4 LDY zpx;AC LDY abs;BC LDY absx
4A LSR acc;46 LSR zp;56 LSR zpx;4E LSR abs;5E LSR absx
EA NOP imp
09 ORA imm;05 ORA zp;15 ORA zpx;0D ORA abs;1D ORA absx;19 ORA absy;01 ORA indx;11 ORA indy
48 PHA imp;08 PHP imp;68 PLA imp;28 PLP imp
2A ROL acc;26 ROL zp;36 ROL zpx;2E ROL abs;3E ROL absx
6A ROR acc;66 ROR zp;76 ROR zpx;6E ROR abs;7E ROR absx
40 RTI imp;60 RTS imp
E9 SBC imm;E5 SBC zp;F5 SBC zpx;ED SBC abs;FD SBC absx;F9 SBC absy;E1 SBC indx;F1 SBC indy
38 SEC imp;F8 SED imp;78 SEI imp
85 STA zp;95 STA zpx;8D STA abs;9D STA absx;99 STA absy;81 STA indx;91 STA indy
86 STX zp;96 STX zpy;8E STX abs;84 STY zp;94 STY zpx;8C STY abs
AA TAX imp;A8 TAY imp;BA TSX imp;8A TXA imp;9A TXS imp;98 TYA imp
"""
for part in _tab.replace('\n', ';').split(';'):
    part = part.strip()
    if not part: continue
    c, mn, md = part.split()
    op(int(c, 16), mn, md)
MODE_LEN = {'imp': 1, 'acc': 1, 'imm': 2, 'zp': 2, 'zpx': 2, 'zpy': 2, 'rel': 2, 'indx': 2, 'indy': 2,
            'abs': 3, 'absx': 3, 'absy': 3, 'ind': 3}

# flags bitmask
FC, FZN = 1, 2
ALLF = FC | FZN

# ---------------------------------------------------------------- parse
class Ins:
    __slots__ = ('inline_words', 'bank', 'addr', 'bytes', 'mn', 'mode', 'val', 'text', 'labels', 'succ', 'callee',
                 'use', 'defs', 'live_in', 'live_out', 'is_target', 'fall', 'executed', 'zbank', 'special')

def nes_bank_base(b): return 0xC000 if b == 'FF' else 0x8000

symbols = {}           # label -> (bank, addr)
code = {}              # (bank, addr) -> Ins
data_addrs = collections.defaultdict(set)
order = collections.defaultdict(list)   # bank -> list of addrs in order (code only)

for b in ALL_BANKS:
    pending = []
    last_global = None
    last_ins = None
    for line in open(os.path.join(SRC, f'bank_{b}.asm'), encoding='utf-8'):
        line = line.rstrip('\n')
        m = rx_line.match(line)
        if not m:
            s = line.split(';')[0].strip()
            lm = rx_label.match(s)
            if lm:
                name = lm.group(1)
                if name.startswith('@'):
                    name = f'{last_global}{name}'
                else:
                    last_global = name
                pending.append(name)
            continue
        addr = int(m.group(9), 16)
        by = [int(x, 16) for x in m.group(10).split()]
        txt = m.group(11).split(';')[0].strip()
        for name in pending:
            symbols[name] = (b, addr)
        is_ins = re.match(r'^[A-Z]{3}\b', txt) is not None
        if is_ins and by[0] in MODES:
            i = Ins()
            i.bank, i.addr, i.bytes, i.text = b, addr, by, txt
            i.mn, i.mode = MODES[by[0]]
            assert MODE_LEN[i.mode] == len(by), (b, hex(addr), txt)
            i.val = by[1] if len(by) == 2 else (by[1] | by[2] << 8) if len(by) == 3 else None
            i.labels = pending
            i.executed = m.group(1) == 'C'
            i.is_target = False
            i.special = None
            i.inline_words = []
            last_ins = i
            code[(b, addr)] = i
            order[b].append(addr)
        else:
            for k in range(len(by)): data_addrs[b].add(addr + k)
            if last_ins is not None and 'jump_to_pointers_after_jsr' in last_ins.text and txt.startswith('.word'):
                last_ins.inline_words.append(txt.split()[1])
                pending = []
                continue
            last_ins = None
        pending = []

# load raw binary for data checks
def eval_label_bank(i):
    """bank of a JSR/JMP absolute target"""
    t = i.val
    if t >= 0xC000: return 'FF'
    if i.bank != 'FF': return i.bank
    # FF code referencing switchable code: look at symbol name in the operand text
    opnd = i.text.split(None, 1)[1].strip()
    name = re.match(r'[A-Za-z_][A-Za-z0-9_]*', opnd).group(0)
    if name in symbols: return symbols[name][0]
    raise Exception(f'cannot resolve bank for {i.text} at {i.bank}:{i.addr:04X}')

# ---------------------------------------------------------------- CFG
def nxt(i):
    k = (i.bank, i.addr + len(i.bytes))
    return k if k in code else None

for k, i in code.items():
    i.succ = []
    i.callee = None
    i.fall = nxt(i)
    mn = i.mn
    if mn in ('BCC', 'BCS', 'BEQ', 'BNE', 'BMI', 'BPL', 'BVC', 'BVS'):
        off = i.val - 256 if i.val >= 128 else i.val
        t = (i.bank, (i.addr + 2 + off) & 0xFFFF)
        i.val = t[1]
        i.succ = [t, i.fall]
    elif mn == 'JMP' and i.mode == 'abs':
        i.succ = [(eval_label_bank(i), i.val)]
    elif mn == 'JSR' and i.inline_words:
        i.mn = mn = 'JTAB'
        i.succ = [symbols[n] for n in i.inline_words]
    elif mn == 'JSR':
        i.callee = (eval_label_bank(i), i.val)
        i.succ = [i.fall]
    elif mn in ('RTS', 'RTI', 'BRK') or (mn == 'JMP'):
        i.succ = []
    else:
        i.succ = [i.fall]
    for j, s in enumerate(i.succ):
        if s is not None and s in code and (mn == 'JTAB' or s != i.fall or (j == 0 and mn in ('BCC', 'BCS', 'BEQ', 'BNE', 'BMI', 'BPL', 'BVC', 'BVS', 'JMP'))):
            code[s].is_target = True
    if i.callee and i.callee in code:
        code[i.callee].is_target = True

# code labels referenced from data / immediates (indirect jump targets)
indirect_targets = set()
def mark_indirect(name):
    if name in symbols and symbols[name] in code:
        indirect_targets.add(symbols[name])
        code[symbols[name]].is_target = True

for b in ALL_BANKS:
    for line in open(os.path.join(SRC, f'bank_{b}.asm'), encoding='utf-8'):
        m = rx_line.match(line)
        if not m: continue
        txt = m.group(11).split(';')[0]
        if re.match(r'^\s*\.(byte|word|dbyt)', txt) or re.match(r'^\s*(LDA|LDX|LDY)\s+#', txt):
            for name in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', txt):
                if name in ('byte', 'word', 'dbyt', 'LDA', 'LDX', 'LDY'): continue
                mark_indirect(name)

# first instruction after data / unknown predecessor is a target too
for b in CODE_BANKS:
    prev = None
    for a in order[b]:
        i = code[(b, a)]
        if prev is None or prev.fall != (b, a):
            i.is_target = True
        prev = i

# ---------------------------------------------------------------- special patterns
# RTS trick: LDA #>(lbl-1) / PHA / LDA #<(lbl-1) / PHA / JMP (ind)
for b in CODE_BANKS:
    for a in order[b]:
        i = code[(b, a)]
        if i.mn == 'LDA' and i.mode == 'imm':
            seq = [i]
            k = i.fall
            for _ in range(4):
                if k is None: break
                seq.append(code[k]); k = code[k].fall
            if len(seq) == 5 and [s.mn for s in seq] == ['LDA', 'PHA', 'LDA', 'PHA', 'JMP'] and seq[2].mode == 'imm' and seq[4].mode == 'ind':
                ret = ((seq[0].val << 8) | seq[2].val) + 1
                seq[0].special = ('push_ret', (b, ret))
                for s in seq[1:4]: s.special = ('skip',)
                code[(b, ret)].is_target = True
                print(f'RTS trick at {b}:{a:04X} -> {ret:04X}', file=sys.stderr)

# ---------------------------------------------------------------- liveness (C, ZN)
USE_DEF = {
    'ADC': (FC, ALLF), 'SBC': (FC, ALLF), 'CMP': (0, ALLF), 'CPX': (0, ALLF), 'CPY': (0, ALLF),
    'AND': (0, FZN), 'ORA': (0, FZN), 'EOR': (0, FZN), 'LDA': (0, FZN), 'LDX': (0, FZN), 'LDY': (0, FZN),
    'TAX': (0, FZN), 'TAY': (0, FZN), 'TXA': (0, FZN), 'TYA': (0, FZN), 'TSX': (0, FZN),
    'INX': (0, FZN), 'INY': (0, FZN), 'DEX': (0, FZN), 'DEY': (0, FZN), 'INC': (0, FZN), 'DEC': (0, FZN),
    'PLA': (0, FZN), 'ASL': (0, ALLF), 'LSR': (0, ALLF), 'ROL': (FC, ALLF), 'ROR': (FC, ALLF),
    'CLC': (0, FC), 'SEC': (0, FC), 'BCC': (FC, 0), 'BCS': (FC, 0), 'BEQ': (FZN, 0), 'BNE': (FZN, 0),
    'BMI': (FZN, 0), 'BPL': (FZN, 0), 'BVC': (0, 0), 'BVS': (0, 0), 'BIT': (0, FZN), 'PHP': (ALLF, 0),
    'PLP': (0, ALLF), 'RTS': (0, 0), 'RTI': (0, 0), 'JMP': (0, 0), 'JSR': (0, 0),
}
for i in code.values():
    u, d = USE_DEF.get(i.mn, (0, 0))
    if i.mn == 'JMP' and i.mode == 'ind': u = ALLF
    i.use, i.defs = u, d
    i.live_in = 0
    i.live_out = 0

def live_in_of(k):
    if k is None or k not in code: return ALLF
    return code[k].live_in

# ---- interprocedural info: function entries, their bodies, call sites
callsites = collections.defaultdict(list)
for i in code.values():
    if i.mn == 'JSR' and i.callee in code:
        callsites[i.callee].append(i)

def intra_succ(i):
    if i.mn == 'JSR': return [i.fall] if i.fall else []
    return [s for s in i.succ if s is not None]

def reach_from(k):
    seen = set([k]); st = [k]
    while st:
        x = st.pop()
        if x not in code: continue
        for s in intra_succ(code[x]):
            if s in code and s not in seen:
                seen.add(s); st.append(s)
    return seen

rts_owner = collections.defaultdict(set)     # rts key -> set of entries
unknown_rts = set()
for e in callsites:
    for x in reach_from(e):
        if x in code and code[x].mn == 'RTS':
            rts_owner[x].add(e)
rts_extra = collections.defaultdict(set)     # rts key -> extra return points
reach_cache = {}
def reach_c(k):
    if k not in reach_cache: reach_cache[k] = reach_from(k)
    return reach_cache[k]
entry_reach = {e: reach_c(e) for e in callsites}
for S in code.values():
    if not (S.mn == 'JMP' and S.mode == 'ind'): continue
    sk = (S.bank, S.addr)
    E_S = [e for e in callsites if sk in entry_reach[e]]
    trick = None
    # RTS trick: the instruction 4 before pushes a return address
    for j in code.values():
        if j.special and j.special[0] == 'push_ret' and j.bank == S.bank and 0 < S.addr - j.addr <= 8:
            trick = j.special[1]
    for t in indirect_targets:
        if t[0] != S.bank: continue
        for x in reach_c(t):
            if x in code and code[x].mn == 'RTS':
                if trick: rts_extra[x].add(trick)
                elif E_S: rts_owner[x] |= set(E_S)
                else: unknown_rts.add(x)
roots = {symbols['vec_FEC0_RESET'], symbols['vec_C000_NMI']}
for r in roots:
    for x in reach_from(r):
        if x in code and code[x].mn == 'RTS' and not rts_owner.get(x):
            unknown_rts.add(x)
for i in code.values():
    k = (i.bank, i.addr)
    if i.mn == 'RTS' and not rts_owner.get(k) and not rts_extra.get(k):
        unknown_rts.add(k)

# transparency: flags that may pass unmodified from entry to some RTS
transp = {e: 0 for e in callsites}
def compute_transp():
    ch = True
    while ch:
        ch = False
        for e in callsites:
            res = 0
            for f in (FC, FZN):
                seen = set([e]); st = [e]; ok = False
                while st and not ok:
                    x = st.pop()
                    if x not in code: ok = True; break
                    i = code[x]
                    if i.mn == 'JSR':
                        if i.defs & f: continue
                        if not (transp.get(i.callee, ALLF) & f): continue
                        nx = [i.fall] if i.fall else []
                    else:
                        if i.defs & f: continue
                        if i.mn in ('RTS',): ok = True; break
                        if i.mn in ('RTI', 'BRK') or (i.mn == 'JMP' and i.mode == 'ind'): ok = True; break
                        nx = [s for s in i.succ if s is not None]
                        if len(nx) < len(i.succ): ok = True; break
                    for s in nx:
                        if s not in seen: seen.add(s); st.append(s)
                if ok: res |= f
            if res != transp[e]:
                transp[e] = res; ch = True
compute_transp()

def run_liveness(local):
    for i in code.values(): i.live_in = 0; i.live_out = 0
    changed = True
    it = 0
    while changed:
        changed = False
        it += 1
        for i in code.values():
            k = (i.bank, i.addr)
            if i.mn == 'JSR':
                out = live_in_of(i.fall)
                lin = ubd.get(i.callee, ALLF) | (out & transp.get(i.callee, ALLF))
            elif i.mn == 'RTS':
                if local: out = 0
                elif k in unknown_rts: out = ALLF
                else:
                    out = 0
                    for e in rts_owner[k]:
                        for cs in callsites[e]: out |= live_in_of(cs.fall)
                    for r in rts_extra[k]: out |= live_in_of(r)
                lin = out
            else:
                if i.mn in ('RTI', 'BRK') or (i.mn == 'JMP' and i.mode == 'ind'):
                    out = ALLF if i.mn != 'RTI' else 0
                else:
                    out = 0
                    for s in i.succ: out |= live_in_of(s)
                lin = i.use | (out & ~i.defs)
            if out != i.live_out or lin != i.live_in:
                i.live_out, i.live_in = out, lin
                changed = True
            if local and k in ubd and ubd[k] != lin:
                ubd[k] = lin; changed = True
    return it

ubd = {e: 0 for e in callsites}
run_liveness(True)
it = run_liveness(False)
print(f'liveness converged in {it} iterations', file=sys.stderr)

# ---------------------------------------------------------------- Z80 code bank placement
# Z80 code banks (Sega mapper pages in slot 1, $4000). Assignment by NES bank / address range.
def zbank_of(bank, addr):
    return PLACEMENT(bank, addr)

PLACE = json.load(open(os.path.join(os.path.dirname(__file__), 'placement.json')))
def PLACEMENT(bank, addr):
    for rng in PLACE[bank]:
        lo, hi, zb = int(rng[0], 16), int(rng[1], 16), rng[2]
        if lo <= addr <= hi: return zb
    raise Exception(f'no placement for {bank}:{addr:04X}')

for i in code.values():
    if i.bank in CODE_BANKS:
        i.zbank = PLACEMENT(i.bank, i.addr)

def zl(k):
    return f'Z{k[0]}_{k[1]:04X}'

# ---------------------------------------------------------------- code generation
IO_READ = {0x2002: 'ppu_r2002', 0x2007: 'ppu_r2007', 0x4016: 'joy_r4016', 0x4017: 'joy_r4017'}
IO_WRITE = {0x2000: 'ppu_w2000', 0x2001: 'ppu_w2001', 0x2003: None, 0x2005: 'ppu_w2005',
            0x2006: 'ppu_w2006', 0x2007: 'ppu_w2007', 0x4014: 'ppu_w4014', 0x4016: 'joy_w4016'}

def is_io(a): return 0x2000 <= a < 0x6000

def M(a):
    """NES address -> Z80 address (static)"""
    if a < 0x2000: return 0xC000 + (a & 0x7FF)
    if a >= 0xC000: return a - 0xC000
    return a
def is_rom(a): return a >= 0x8000 or (0x6000 <= a < 0x8000)

HL_CLOBBER = re.compile(r'^(call|rst|ret|jp|jr|ex |exx|pop hl|ld hl|ld h,|ld l,|inc hl|dec hl|inc h|dec h|inc l|dec l|add hl|adc hl|sbc hl|set \d,[hl]\b|res \d,[hl]\b|ld sp)|^\s*;|\n')

class Gen:
    def __init__(self, zb):
        self.zb = zb
        self.lines = []
        self.carry = 'N'     # N native, I inverted, 0, 1
        self.uniq = 0
        self.ix = None       # IX = ix + X  (index register cache)
        self.iy = None       # IY = iy + Y
        self.look = []       # following instructions of the current basic block
        self.hl = None       # known value of HL (or None)

    def e(self, s):
        # HL value tracking: reuse / shorten 'ld hl,imm' when HL is known
        if s.startswith('ld hl,0x') and '(' not in s:
            v = int(s[6:], 16)
            if self.hl == v:
                return
            if self.hl is not None and (self.hl >> 8) == (v >> 8):
                self.lines.append(f'\tld l,0x{v & 0xFF:02X}')
                self.hl = v
                return
            self.lines.append('\t' + s)
            self.hl = v
            return
        if HL_CLOBBER.search(s):
            self.hl = None
        self.lines.append('\t' + s)
        if s.startswith('call') or s.startswith('jp') or s.startswith('ret') or s.startswith('ld sp'):
            if not s.startswith('jp nz') and not s.startswith('jp z') and not s.startswith('jp c') \
               and not s.startswith('jp nc') and not s.startswith('jp m') and not s.startswith('jp p'):
                self.ix = self.iy = None
            if s.startswith('call'):
                self.ix = self.iy = None
    def lab(self, s):
        self.lines.append(s + ':')
        self.hl = None
        if not s.startswith('.'):
            self.ix = self.iy = None

    def newlab(self):
        self.uniq += 1
        return f'.t{self.uniq}'

    def mat_carry(self):
        """make Z80 carry == 6502 carry"""
        if self.carry == 'I': self.e('ccf')
        elif self.carry == '1': self.e('scf')
        elif self.carry == '0': self.e('scf'); self.e('ccf')
        self.carry = 'N'

    def carry_needs_preserve(self, i):
        # Z80 carry must survive the current instruction (which does not define carry)
        return (i.live_out & FC) and self.carry in ('N', 'I')

    # effective address in HL for indexed / indirect modes; preserves A and S/Z flags
    def ea(self, i, preserve_c):
        """effective address -> returns operand string '(hl)' or '(ix+d)'/'(iy+d)'.
        Preserves A and S/Z (and carry if preserve_c)."""
        md, v = i.mode, M(i.val)
        if md in ('zp', 'abs'):
            self.e(f'ld hl,0x{v:04X}')
            return '(hl)'
        if md in ('zpx', 'absx', 'zpy', 'absy'):
            isx = md in ('zpx', 'absx')
            r, rr, xr = ('c', 'bc', 'ix') if isx else ('e', 'de', 'iy')
            cur = self.ix if isx else self.iy
            if cur is not None and -128 <= v - cur <= 127:
                return f'({xr}{v - cur:+d})'
            if v & 0xFF == 0:
                self.e(f'ld h,0x{v >> 8:02X}')
                self.e(f'ld l,{r}')
                return '(hl)'
            # look ahead in the block: worth loading the index register?
            modes = ('zpx', 'absx') if isx else ('zpy', 'absy')
            bases = [v]
            for j in self.look:
                if j.mode in modes and j.val & 0xFF and not is_io(j.val) and not is_rom(j.val):
                    bases.append(M(j.val))
                if isx and j.mn in ('TAX', 'LDX', 'TSX', 'INX', 'DEX'): break
                if not isx and j.mn in ('TAY', 'LDY', 'INY', 'DEY'): break
            best, bk = 0, None
            for b0 in bases:
                k = b0 + 127
                if not (-128 <= v - k <= 127): continue
                n = sum(1 for b in bases if -128 <= b - k <= 127)
                if n > best: best, bk = n, k
            if best >= 2:
                if preserve_c: self.e("ex af,af'")
                self.e(f'ld {xr},0x{bk & 0xFFFF:04X}')
                self.e(f'add {xr},{rr}')
                if preserve_c: self.e("ex af,af'")
                if isx: self.ix = bk
                else: self.iy = bk
                return f'({xr}{v - bk:+d})'
            if preserve_c: self.e("ex af,af'")
            self.e(f'ld hl,0x{v:04X}')
            self.e(f'add hl,{rr}')
            if preserve_c: self.e("ex af,af'")
            return '(hl)'
        if md == 'indy':
            # pointer + Y, then NES -> Z80 address: $00-$3F and $C0-$FF pages swap (xor $C0)
            l = self.newlab()
            self.e("ex af,af'")
            self.e(f'ld hl,(0x{v:04X})')
            self.e('add hl,de')
            l2 = self.newlab()
            self.e('ld a,h')
            self.e('add a,0x40')        # 00-3F -> 40-7F, C0-FF -> 00-3F, 40-BF -> 80-FF (kept)
            self.e(f'jp m,{l}')
            self.e('cp 0x40')
            self.e(f'jr c,{l2}')
            self.e('or 0x80')            # RAM page 00-3F -> C0-FF
            self.lab(l2)
            self.e('ld h,a')
            self.lab(l)
            self.e("ex af,af'")
            return '(hl)'
        raise Exception(f'ea mode {md} at {i.bank}:{i.addr:04X}')

    def zn_test(self, i, reg):
        """set Z80 S/Z from reg if 6502 N/Z are live after i"""
        if not (i.live_out & FZN): return
        preserve = self.carry_needs_preserve(i) if i.defs & FC == 0 else False
        if reg == 'a' and not preserve:
            self.e('or a')
            if self.carry in ('N', 'I'):
                # carry got clobbered but it is dead
                pass
        else:
            self.e(f'inc {reg}')
            self.e(f'dec {reg}')

    def target_call(self, k, kind):
        """emit CALL/JP to code key k, far if in another Z80 bank"""
        if k not in code:
            self.e(f'call rt_bad_target ; {k}')
            return
        t = code[k]
        if t.zbank == self.zb:
            self.e(f'{kind} {zl(k)}')
        else:
            FAR_BANKS.add(t.zbank)
            self.e(f'ld hl,{zl(k)}')
            self.e(f'call far_{t.zbank}')
            if kind != 'call':   # far jump = tail call
                self.e('ret')

    def gen(self, i):
        mn, md, v = i.mn, i.mode, i.val
        lo = i.live_out
        if mn in ('TAX', 'LDX', 'TSX', 'INX', 'DEX'): self.ix = None
        if mn in ('TAY', 'LDY', 'INY', 'DEY'): self.iy = None
        if i.special:
            if i.special[0] == 'skip': return
            if i.special[0] == 'push_ret':
                tk = i.special[1]
                # push the Z80 return address; the handler RTS returns there
                self.e(f'ld hl,{zl(tk)}')
                self.e('push hl')
                return
        # ---- loads
        if mn in ('LDA', 'LDX', 'LDY'):
            reg = {'LDA': 'a', 'LDX': 'c', 'LDY': 'e'}[mn]
            if md == 'imm':
                self.e(f'ld {reg},0x{v:02X}')
            elif md in ('zp', 'abs') and is_io(v):
                fn = IO_READ.get(v)
                if fn is None: raise Exception(f'io read {v:04X}')
                if reg == 'a': self.e(f'call {fn}')
                else:
                    self.e('push af'); self.e(f'call {fn}'); self.e(f'ld {reg},a'); self.e('pop af')
            elif md in ('zp', 'abs') and reg == 'a':
                self.e(f'ld a,(0x{M(v):04X})')
            else:
                op_ = self.ea(i, self.carry_needs_preserve(i))
                self.e(f'ld {reg},{op_}')
            self.zn_test(i, reg)
            return
        if mn in ('STA', 'STX', 'STY'):
            reg = {'STA': 'a', 'STX': 'c', 'STY': 'e'}[mn]
            base = v
            if md in ('zp', 'abs') and is_io(base):
                if base in IO_WRITE:
                    fn = IO_WRITE[base]
                    if fn is None: return
                    if reg == 'a': self.e(f'call {fn}')
                    else:
                        self.e('push af'); self.e(f'ld a,{reg}'); self.e(f'call {fn}'); self.e('pop af')
                if 0x4000 <= base < 0x4018:
                    off = base - 0x4000
                    self.e(f'ld hl,APU_SH+0x{off:02X}')
                    self.e(f'ld (hl),{reg}')
                    self.e(f'ld l,low APU_W+0x{off:02X}')
                    self.e('ld (hl),1')
                return
            if md in ('absx', 'absy') and is_io(base):
                if 0x4000 <= base < 0x4018 and reg == 'a':
                    r = 'c' if md == 'absx' else 'e'
                    self.e('push af')
                    self.e(f'ld a,{r}')
                    self.e(f'add a,low APU_SH+0x{base - 0x4000:02X}')
                    self.e('ld l,a')
                    self.e('ld h,high APU_SH')
                    self.e('pop af')
                    self.e('ld (hl),a')
                    self.e('set 5,l')
                    self.e('ld (hl),1')
                    return
                raise Exception('indexed io write')
            if md in ('absx', 'absy', 'abs') and is_rom(base):
                # mapper write (bus conflict table) -> bank switch with value in reg
                if reg == 'a': self.e('call rt_nes_bank')
                else:
                    self.e('push af'); self.e(f'ld a,{reg}'); self.e('call rt_nes_bank'); self.e('pop af')
                return
            if md in ('zp', 'abs') and reg == 'a':
                self.e(f'ld (0x{M(v):04X}),a')
                return
            op_ = self.ea(i, self.carry_needs_preserve(i))
            self.e(f'ld {op_},{reg}')
            return
        # ---- transfers
        if mn in ('TAX', 'TAY', 'TXA', 'TYA'):
            d, s = {'TAX': ('c', 'a'), 'TAY': ('e', 'a'), 'TXA': ('a', 'c'), 'TYA': ('a', 'e')}[mn]
            self.e(f'ld {d},{s}')
            self.zn_test(i, d)
            return
        if mn in ('INX', 'INY', 'DEX', 'DEY'):
            r = 'c' if mn[2] == 'X' else 'e'
            self.e(f'{"inc" if mn[0] == "I" else "dec"} {r}')
            return
        if mn == 'TSX':
            # S = SP - 0x101 (low byte)
            if self.carry_needs_preserve(i): self.e('push af'); self.e('ld hl,2'); pres = True
            else: self.e('ld hl,0'); pres = False
            self.e('add hl,sp')
            self.e('ld c,l')
            self.e('dec c')
            if pres: self.e('pop af')
            self.zn_test(i, 'c')
            return
        if mn == 'TXS':
            self.e('ld h,0xC1')
            self.e('ld l,c')
            self.e('inc hl')
            self.e('ld sp,hl')
            return
        # ---- stack
        if mn == 'PHA':
            self.e('push af')
            self.e('inc sp')
            return
        if mn == 'PLA':
            self.e('dec sp')
            self.e('pop hl')
            self.e('ld a,h')
            self.zn_test(i, 'a')
            return
        if mn == 'PHP':
            self.mat_carry()
            self.e('push af')
            self.e('pop hl')
            self.e('ld h,l')
            self.e('push hl')
            self.e('inc sp')
            return
        if mn == 'PLP':
            self.e('dec sp')
            self.e('pop hl')
            self.e('ld l,h')
            self.e('ld h,a')
            self.e('push hl')
            self.e('pop af')
            self.carry = 'N'
            return
        # ---- flags
        if mn == 'CLC': self.carry = '0'; return
        if mn == 'SEC': self.carry = '1'; return
        if mn in ('SEI', 'CLI', 'CLD', 'SED', 'NOP', 'CLV'): return
        # ---- arithmetic
        if mn in ('ADC', 'SBC', 'AND', 'ORA', 'EOR', 'CMP'):
            if md == 'imm':
                opnd = f'0x{v:02X}'
            elif md in ('zp', 'abs') and is_io(v):
                raise Exception('alu io')
            else:
                pres = (self.carry in ('N', 'I')) and (mn in ('ADC', 'SBC') or (lo & FC and mn not in ('CMP',)))
                opnd = self.ea(i, pres)
            if mn == 'ADC':
                if self.carry == '0': self.e(f'add a,{opnd}')
                else:
                    if self.carry == 'I': self.e('ccf')
                    elif self.carry == '1': self.e('scf')
                    self.e(f'adc a,{opnd}')
                self.carry = 'N'
            elif mn == 'SBC':
                if self.carry == '1': self.e(f'sub {opnd}')
                else:
                    if self.carry == 'N': self.e('ccf')
                    elif self.carry == '0': self.e('scf')
                    self.e(f'sbc a,{opnd}')
                self.carry = 'I'
            elif mn == 'CMP':
                self.e(f'cp {opnd}')
                self.carry = 'I'
            else:
                z = {'AND': 'and', 'ORA': 'or', 'EOR': 'xor'}[mn]
                if (lo & FC) and self.carry in ('N', 'I'):
                    l1, l2 = self.newlab(), self.newlab()
                    self.e(f'jr c,{l1}')
                    self.e(f'{z} {opnd}')
                    self.e(f'jr {l2}')
                    self.lab(l1)
                    self.e(f'{z} {opnd}')
                    self.e('scf')
                    self.lab(l2)
                else:
                    self.e(f'{z} {opnd}')
            return
        if mn in ('CPX', 'CPY'):
            r = 'c' if mn == 'CPX' else 'e'
            self.e('ld d,a')
            self.e(f'ld a,{r}')
            if md == 'imm': self.e(f'cp 0x{v:02X}')
            else:
                self.e(f'ld hl,0x{M(v):04X}')
                self.e('cp (hl)')
            self.e('ld a,d')
            self.e('ld d,0')
            self.carry = 'I'
            return
        if mn == 'BIT':
            # Z from A&M, N from M bit 7 (V ignored)
            self.e(f'ld hl,0x{M(v):04X}')
            self.e('ld d,a')
            self.e('and (hl)')        # Z
            self.e('ld a,d')
            self.e('ld d,0')
            # N: only correct when Z==0 path doesn't need N... handled as special case
            if self.carry in ('N', 'I') and (lo & FC):
                raise Exception('BIT with live carry')
            return
        # ---- shifts / inc / dec
        if mn in ('ASL', 'LSR', 'ROL', 'ROR'):
            opnd = 'a'
            if md != 'acc':
                opnd = self.ea(i, self.carry_needs_preserve(i) and mn in ('ROL', 'ROR'))
            if mn == 'ASL':
                self.e('add a,a' if md == 'acc' else f'sla {opnd}')
            elif mn == 'LSR':
                self.e(f'srl {opnd}')
            else:
                if self.carry == '0':
                    self.e(f'{"sla" if mn == "ROL" else "srl"} {opnd}')
                else:
                    self.mat_carry()
                    if md == 'acc' and not (lo & FZN):
                        self.e('rla' if mn == 'ROL' else 'rra')
                    else:
                        self.e(f'{"rl" if mn == "ROL" else "rr"} {opnd}')
            self.carry = 'N'
            return
        if mn in ('INC', 'DEC'):
            op_ = self.ea(i, self.carry_needs_preserve(i))
            self.e(f'{mn.lower()} {op_}')
            return
        # ---- control flow
        if mn == 'JTAB':
            self.mat_carry()
            self.e('call rt_jtab')
            for k in i.succ:
                assert code[k].zbank == self.zb
                self.e(f'dw {zl(k)}')
            return
        if mn in ('BEQ', 'BNE', 'BMI', 'BPL', 'BCC', 'BCS', 'BVC', 'BVS'):
            tk = (i.bank, v)
            if mn in ('BVC', 'BVS'):
                raise Exception('BV?')
            t_live = live_in_of(tk)
            if mn in ('BCC', 'BCS'):
                if self.carry in ('0', '1'):
                    taken = (mn == 'BCS') == (self.carry == '1')
                    if taken:
                        if t_live & FC: self.mat_carry()
                        self.jump_to(tk)
                    return
                if self.carry == 'I':
                    if lo & FC:
                        self.e('ccf'); self.carry = 'N'
                        cond = 'c' if mn == 'BCS' else 'nc'
                    else:
                        cond = 'nc' if mn == 'BCS' else 'c'
                else:
                    cond = 'c' if mn == 'BCS' else 'nc'
            else:
                cond = {'BEQ': 'z', 'BNE': 'nz', 'BMI': 'm', 'BPL': 'p'}[mn]
                if self.carry != 'N' and (t_live & FC):
                    self.mat_carry()
            self.cjump(cond, tk)
            return
        if mn == 'JMP':
            if md == 'abs':
                tk = (eval_label_bank(i), v)
                if live_in_of(tk) & FC: self.mat_carry()
                self.jump_to(tk)
            else:
                self.mat_carry()
                self.e(f'ld hl,(0x{M(v):04X})')
                self.e(f'jp rt_jmp_ind_{self.zb}')
            return
        if mn == 'JSR':
            if (live_in_of(i.callee) | live_in_of(i.fall)) & FC: self.mat_carry()
            hook = CALL_HOOKS.get(i.callee)
            if hook:
                self.e(hook)
            else:
                self.target_call(i.callee, 'call')
            self.carry = 'N'
            return
        if mn in ('RTS', 'RTI'):
            self.mat_carry()
            self.e('ret')
            return
        if mn == 'BRK':
            self.e('call rt_brk')
            return
        raise Exception(f'unhandled {mn} {md} at {i.bank}:{i.addr:04X}')

    def jump_to(self, tk):
        if tk in code and code[tk].zbank == self.zb:
            self.e(f'jp {zl(tk)}')
        else:
            self.target_call(tk, 'jp')

    def cjump(self, cond, tk):
        if tk in code and code[tk].zbank == self.zb:
            self.e(f'jp {cond},{zl(tk)}')
        else:
            l = self.newlab()
            inv = {'z': 'nz', 'nz': 'z', 'c': 'nc', 'nc': 'c', 'm': 'p', 'p': 'm'}[cond]
            self.e(f'jp {inv},{l}')
            self.target_call(tk, 'jp')
            self.lab(l)

# hooks: replace JSR to specific routines
CALL_HOOKS = {}
FAR_BANKS = set()
# native NES bank switching routines
CALL_HOOKS[symbols['sub_FFCD_prg_bankswitch_with_backup']] = 'call rt_ffcd'
CALL_HOOKS[symbols['sub_FFCF_prg_bankswitch']] = 'call rt_ffcf'
CALL_HOOKS[symbols['sub_FFC8_nmi_prg_bankswitch']] = 'ld c,a\n\tcall rt_nes_bank\n\tinc c\n\tdec c'
if not os.environ.get('NO_NATIVE'):
    # native Z80 replacements of hot NES routines (src/rt_native.asm)
    CALL_HOOKS[symbols['sub_804D_display_player_hearts_with_sprites']] = 'call rt_hearts'
    CALL_HOOKS[symbols['sub_80EC']] = 'call rt_apuw'
    CALL_HOOKS[symbols['sub_C0CB_write_buffer_to_ppu']] = 'call rt_ppubuf0'
    CALL_HOOKS[symbols['sub_C0CF_write_buffer_to_ppu']] = 'call rt_ppubuf'
    CALL_HOOKS[symbols['sub_C1BC_hide_unused_sprites']] = 'call rt_hide_sprites'
    CALL_HOOKS[symbols['sub_C118_read_joy_regs']] = 'call rt_read_joy'
if os.environ.get('NOSOUND'):
    for _n in ('sub_0x014010_update_sound_engine', 'sub_0x014013_prepare_new_sfx'):
        CALL_HOOKS[symbols[_n]] = '; sound disabled'
# instructions to replace with custom code: (bank, addr) -> list of asm lines
INSERT_BEFORE = {}

def sym(name): return symbols[name]

# frame sync: when the scheduler finds no runnable thread it jumps back to loc_FF39_loop.
# we insert a call to the runtime frame routine (wait vblank, flush video, run NMI).
_k = None
for a in order['FF']:
    i = code[('FF', a)]
    if i.mn == 'JMP' and i.mode == 'abs' and i.val == sym('loc_FF39_loop')[1] and i.addr < 0xFF60:
        _k = ('FF', a)
INSERT_BEFORE[_k] = ['call rt_frame']
if not os.environ.get('NO_NATIVE'):
    INSERT_BEFORE[sym('bra_8216_loop')] = ['call rt_sprloop', 'ret']
    INSERT_BEFORE[sym('sub_0x010013_sprite_engine')] = ['call rt_sprengine', 'ret']
NMI_ENTRY = sym('vec_C000_NMI')
RESET_ENTRY = sym('vec_FEC0_RESET')

# ---------------------------------------------------------------- emit
banks_out = collections.defaultdict(list)
gens = {}
for b in CODE_BANKS:
    prev = None
    lst_ = [code[(b, a)] for a in order[b]]
    for n_, a in enumerate(order[b]):
        i = code[(b, a)]
        zb = i.zbank
        look = []
        for j in lst_[n_ + 1:]:
            if j.is_target or j.zbank != i.zbank or j.mn in ('JSR', 'JMP', 'RTS', 'RTI', 'JTAB', 'BRK'): break
            look.append(j)
        g = gens.get(zb)
        if g is None:
            g = gens[zb] = Gen(zb)
        # crossing to another z80 bank with fallthrough
        if prev is not None and prev.fall == (b, a) and prev.zbank != zb:
            pg = gens[prev.zbank]
            if prev.mn not in ('JMP', 'RTS', 'RTI', 'JTAB'):
                if live_in_of((b, a)) & FC: pg.mat_carry()
                pg.target_call((b, a), 'jp')
        elif prev is not None and prev.fall is None and prev.mn not in ('JMP', 'RTS', 'RTI', 'BRK', 'JTAB') and prev.zbank == zb:
            # falls into data (never executed in practice)
            g.e(f'call rt_fall_into_data')
        if i.is_target or prev is None or prev.zbank != zb or prev.fall != (b, a):
            if i.is_target and g.carry != 'N' and (i.live_in & FC):
                g.mat_carry()
            g.carry = 'N'
            g.lab(zl((b, a)))
        g.lines.append(f'; {b}:{a:04X} {i.text}')
        for s in INSERT_BEFORE.get((b, a), []):
            g.e(s)
        g.look = look
        try:
            g.gen(i)
        except Exception as ex:
            print(f'ERROR {b}:{a:04X} {i.text}: {ex}', file=sys.stderr)
            g.e(f'call rt_untranslated ; {ex}')
        prev = i
    # end of bank
    if prev and prev.fall is None and prev.mn not in ('JMP', 'RTS', 'RTI', 'JTAB'):
        gens[prev.zbank].e('call rt_fall_into_data')

# indirect jump dispatch tables, one per Z80 bank that contains a JMP (ind)
NESBANKNUM = {'04': 4, '05': 5, '06': 6, 'FF': 0xFF}
disp = collections.defaultdict(list)
for k in sorted(indirect_targets, key=lambda k: (NESBANKNUM[k[0]], k[1])):
    disp['all'].append(k)
for zb, g in gens.items():
    has_ind = any('rt_jmp_ind_' in l for l in g.lines)
    if not has_ind: continue
    g.lines.append(f'rt_jmp_ind_{zb}:')
    g.e(f'ld ix,dispatch_tab_{zb}')
    g.e(f'ld iy,{len(disp["all"])}')
    g.e('jp rt_dispatch')
    g.lines.append(f'dispatch_tab_{zb}:')
    for k in disp['all']:
        t = code[k]
        g.e(f'dw 0x{k[1]:04X}')
        g.e(f'db 0x{NESBANKNUM[k[0]]:02X},{t.zbank}')
        g.e(f'dw {zl(k)}')

for zb, g in gens.items():
    with open(os.path.join(OUT, f'code_{zb}.asm'), 'w') as f:
        f.write(f'; generated code bank {zb}\n')
        f.write('\n'.join(g.lines) + '\n')

with open(os.path.join(OUT, 'entry.inc'), 'w') as f:
    f.write(f'NES_RESET_BANK equ {code[RESET_ENTRY].zbank}\nNES_RESET equ {zl(RESET_ENTRY)}\n')
    f.write(f'NES_NMI_BANK equ {code[NMI_ENTRY].zbank}\nNES_NMI equ {zl(NMI_ENTRY)}\n')
    _su = symbols['sub_0x014010_update_sound_engine']
    f.write(f'NES_SND_BANK equ {code[_su].zbank}\nNES_SND_UPDATE equ {zl(_su)}\n')
    for name in ('ram_oam',):
        pass
print('banks:', sorted(gens.keys()), 'targets:', len(indirect_targets), file=sys.stderr)

if os.environ.get('TRACE'):
    b, a = os.environ['TRACE'].split(':')
    start = (b, int(a, 16))
    prevm = {start: None}; q = collections.deque([start]); found = []
    while q:
        k = q.popleft()
        i = code[k]
        if i.use & FC or i.mn in ('BRK',) or (i.mn == 'JMP' and i.mode == 'ind') or (k in unknown_rts):
            found.append(k)
            if len(found) > 3: break
            continue
        cands = ([i.callee] if i.mn == 'JSR' else []) + [s for s in i.succ if s]
        if i.mn in ('JSR',) and not i.fall: found.append(k)
        if i.mn != 'JSR' and len([s for s in i.succ if s]) < len(i.succ): found.append(k)
        if i.mn == 'RTS':
            for e in rts_owner[k]:
                for cs in callsites[e]:
                    if cs.fall: cands.append(cs.fall)
        for s2 in cands:
            if s2 in code and code[s2].live_in & FC and s2 not in prevm:
                if i.defs & FC and i.mn != 'JSR': continue
                prevm[s2] = k; q.append(s2)
    for f in found:
        path = []; k = f
        while k: path.append(k); k = prevm[k]
        print('USE at', f, ':', ' <- '.join(f'{x[0]}:{x[1]:04X} {code[x].mn}' for x in path[:40]), file=sys.stderr)

with open(os.path.join(OUT, 'farstubs.inc'), 'w') as f:
    for zb in sorted(FAR_BANKS | set(gens)):
        f.write(f'''far_{zb}:
    ex af,af'
    ld a,(cur_zbank)
    push af
    ld a,{zb}
    ld (cur_zbank),a
    ld (0FFFEh),a
    ex af,af'
    call jp_hl
    jp far_ret
''')
with open(os.path.join(OUT, 'codebanks.inc'), 'w') as f:
    for zb in sorted(gens):
        f.write(f'    MMU 1, {zb}, 4000h\n    INCLUDE "code_{zb}.asm"\ncodeend_{zb}:\n')
with open(os.path.join(OUT, 'codeasserts.inc'), 'w') as f:
    for zb in sorted(gens):
        f.write(f'    ASSERT codeend_{zb} <= RT_BASE\n')
    f.write(f'CODE_PAGES equ {len(gens)}\nLAST_CODE_PAGE equ {max(gens)}\n')
