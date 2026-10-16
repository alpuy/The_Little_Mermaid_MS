#!/bin/bash
# Build the Master System ROM from the NES disassembly.
# Requires: python3, cc65 (ca65/ld65), sjasmplus.
set -e
cd "$(dirname "$0")"
NESSRC="${NESSRC:-../nesdis/The Little Mermaid}"
SJASM="${SJASMPLUS:-sjasmplus}"
mkdir -p build gen
if [ ! -f nes/prg.bin ]; then
  python3 tools/prep_nes.py "$NESSRC" nes/src
  cp -r "$NESSRC/incbin" "$NESSRC/ld65.cfg" nes/src/
  (cd nes/src && for b in 00 01 02 03 04 05 06 FF; do ca65 -U copy_bank_$b.asm -o b$b.o >/dev/null; done && ld65 -C ld65.cfg -o ../prg.bin b*.o)
fi
python3 tools/translate.py "$NESSRC" gen 2> build/translate.log || { cat build/translate.log; exit 1; }
grep -i error build/translate.log || true
python3 tools/gen_tables.py src/tables.inc
DEFS="${EXTRA_DEFS}"
if [ -n "$TAS" ]; then DEFS="$DEFS -DTAS_MODE -DTAS_FILE=\"$(realpath "$TAS")\""; fi
(cd src && eval "\"$SJASM\"" --nologo --msg=war --lst=../build/main.lst --sym=../build/main.sym $DEFS main.asm)
python3 tools/finish_rom.py build/mermaid.sms build/main.sym
