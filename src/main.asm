; The Little Mermaid - Sega Master System port (Sega mapper, 16KB pages)
;   page 0      NES fixed bank image (slot 0) + SMS vectors
;   pages 1-7   NES banks 00-06, raw (slot 2)
;   pages 9-14  translated code (slot 1), runtime at RT_BASE in every code page
;               (assembled in page 9, copied to the others by tools/finish_rom.py)
    DEFDEVICE SMSROM, 4000h, 32
    DEVICE SMSROM
    INCLUDE "vars.inc"
    INCLUDE "../gen/entry.inc"

    ; ---- page 0: NES fixed bank image, vectors over bytes that are only 6502 code
    MMU 0, 0, 0000h
    INCBIN "../nes/prg.bin", 1C000h, 4000h
    ORG 0000h
    di
    ld a,FIRST_CODE_PAGE
    ld (0FFFEh),a
    jp boot
    ASSERT $ <= 0009h
    ORG 0038h                   ; frame interrupt
    push af
    in a,(0BFh)
    ld a,(vbl_count)
    inc a
    ld (vbl_count),a
    pop af
    ei
    reti
    ASSERT $ <= 0046h
    ORG 0066h                   ; PAUSE button
    push af
    ld a,4
    ld (pause_cnt),a
    pop af
    retn
    ASSERT $ <= 006Fh

    ; ---- NES banks 00-06
    MACRO NESBANK n
        MMU 2, n+1, 8000h
        INCBIN "../nes/prg.bin", n*4000h, 4000h
    ENDM
    NESBANK 0
    NESBANK 1
    NESBANK 2
    NESBANK 3
    NESBANK 4
    NESBANK 5
    NESBANK 6

    ; ---- SMS header (end of NES bank 00, padding there); checksum by finish_rom.py
    MMU 1, 1, 4000h
    ORG 7FF0h
    db "TMR SEGA", 0, 0, 0, 0, 0, 0, 0, 4Ch

    ; ---- runtime
    MMU 1, FIRST_CODE_PAGE, RT_BASE
rt_start:
    INCLUDE "rt_core.asm"
    INCLUDE "rt_ppu.asm"
    INCLUDE "rt_video.asm"
    INCLUDE "rt_io.asm"
    INCLUDE "rt_native.asm"
    INCLUDE "tables.inc"
rt_end:
    ASSERT rt_end <= 8000h

    ; ---- translated code
    INCLUDE "../gen/codebanks.inc"
    INCLUDE "../gen/codeasserts.inc"

    IFDEF TAS_MODE
TAS_PAGE equ 16
    MMU 2 n, TAS_PAGE, 8000h
    INCBIN TAS_FILE
TAS_LEN equ ($$ - TAS_PAGE) * 4000h + ($ - 8000h)
    ENDIF

    SAVEDEV "../build/mermaid.sms", 0, 0, 32*4000h
