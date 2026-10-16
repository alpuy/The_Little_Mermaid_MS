# Strip the disassembly listing prefix so ca65 can assemble the original sources.
import re, sys, os
src, dst = sys.argv[1], sys.argv[2]
rx = re.compile(r'^.\s.\s.\s.\s.\s.\s0x......\s..:....:\s..\s..\s...')
os.makedirs(dst, exist_ok=True)
for f in os.listdir(src):
    if f.endswith('.asm') or f.endswith('.inc'):
        lines = open(os.path.join(src, f), encoding='utf-8').read().split('\n')
        out = [rx.sub('', l) for l in lines]
        open(os.path.join(dst, 'copy_' + f), 'w').write('\n'.join(out))
