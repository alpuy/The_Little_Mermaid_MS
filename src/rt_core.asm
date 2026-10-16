; ===========================================================================
; Runtime core (at RT_BASE, identical in every code page of slot 1).
; Conventions: translated code keeps 6502 A=A, X=C, Y=E and B=D=0.
; Runtime entry points preserve AF, BC, DE (unless returning a value); HL is scratch.
; ===========================================================================

; ---------------------------------------------------------------- VDP helpers
    MACRO VDPREG reg            ; write A to VDP register
        di
        out (0BFh),a
        ld a,80h|reg
        out (0BFh),a
        ei
    ENDM

; VRAM write address HL (0000-3FFF)
vram_wr:
    ld a,l
    di
    out (0BFh),a
    ld a,h
    or 40h
    out (0BFh),a
    ei
    ret

; ---------------------------------------------------------------- boot
boot:                           ; from 0000h: slot 1 = a code page, interrupts off
    ld sp,RTSTACK
    xor a
    ld (0FFFCh),a
    ld (0FFFDh),a
    ld a,2
    ld (0FFFFh),a
    ; clear RAM
    ld hl,0C000h
    ld de,0C001h
    ld bc,RTSTACK-0C000h-1
    ld (hl),0
    ldir
    ; PSG silent
    ld a,9Fh
    out (7Fh),a
    ld a,0BFh
    out (7Fh),a
    ld a,0DFh
    out (7Fh),a
    ld a,0FFh
    out (7Fh),a
    ; VDP registers
    ld hl,vdp_init
    ld b,11
    ld c,80h
.r: ld a,(hl)
    out (0BFh),a
    ld a,c
    out (0BFh),a
    inc hl
    inc c
    djnz .r
    ld a,(vdp_init+1)
    ld (vdp_r1),a
    ; clear VRAM
    ld hl,0
    call vram_wr
    ld bc,4000h
.v: xor a
    out (0BEh),a
    dec bc
    ld a,b
    or c
    jr nz,.v
    ; tables: none used / free
    ld hl,BGMAP
    ld de,BGMAP+1
    ld bc,0800h-1               ; BGMAP + CELLSLOT
    ld (hl),0FFh
    ldir
    ld hl,SLOTPAL
    ld de,SLOTPAL+1
    ld bc,255
    ld (hl),0FFh
    ldir
    ld hl,COLMAP
    ld de,COLMAP+1
    ld bc,31
    ld (hl),0FFh
    ldir
    call set_rowmap
    ld a,SRAM_ON
    ld (0FFFCh),a
    ld hl,CHR
    ld de,CHR+1
    ld bc,2000h-1
    ld (hl),0
    ldir
    ld hl,SPRMAP
    ld de,SPRMAP+1
    ld bc,1000h-1
    ld (hl),0FFh
    ldir
    ld hl,SPRATTR
    ld de,SPRATTR+1
    ld bc,255
    ld (hl),0FFh
    ldir
    xor a
    ld (0FFFCh),a
    ld a,0C3h                   ; far call trampoline: JP nnnn
    ld (fc_jp),a
    ld hl,1
    ld (ppu_inc),hl
    ld a,2
    ld (oam_page),a
    inc a
    ld (pal_dirty),a
    ld a,1
    ld (full_redraw),a
    xor a
    call rt_nes_bank
    im 1
    ei
    ; switch to 224 lines a couple of frames after the other registers (some
    ; emulators miss the mode change when R0 and R1 change in the same frame)
    halt
    halt
    ld a,(vdp_r1)
    or 10h
    ld (vdp_r1),a
    VDPREG 1
    ; start the game: reset code page, 6502 stack
    ld a,NES_RESET_BANK
    ld (cur_zbank),a
    ld (0FFFEh),a
    ld sp,0C200h
    ld bc,0
    ld de,0
    xor a
    jp NES_RESET

vdp_init:
    ; R0: mode 4, M2 (224 lines with M1), left column blanked
    ; R1: display off, frame interrupt (M1 for 224 lines set later)
    ; R2: name table 3700h (224-line mode) R5: SAT 3F00h R6: sprite patterns 2000h
    db 26h, 0A0h, 0FFh, 0FFh, 0FFh, 0FFh, 0FFh, 00h, 00h, 00h, 0FFh

; ---------------------------------------------------------------- bank switching
; far call: CALL farcall / DB page / DW target
farcall:
    ex af,af'
    pop hl
    ld a,(hl)
    inc hl
    ld (fc_bank),a
    ld a,(hl)
    inc hl
    ld (fc_jp+1),a
    ld a,(hl)
    inc hl
    ld (fc_jp+2),a
    push hl
farcall_go:                     ; stack: [return]; fc_bank/fc_jp set; caller AF in AF'
    ld a,(cur_zbank)
    ld h,a
    push hl
    ld hl,farret
    push hl
    ld a,(fc_bank)
    ld (cur_zbank),a
    ld (0FFFEh),a
    ex af,af'
    jp fc_jp

farret:
    ex af,af'
    pop hl
    ld a,h
    ld (cur_zbank),a
    ld (0FFFEh),a
    ex af,af'
rt_ret:
    ret

; fast far calls: LD HL,target / CALL far_N (generated stubs)
    INCLUDE "../gen/farstubs.inc"
far_ret:
    ex af,af'
    pop af
    ld (cur_zbank),a
    ld (0FFFEh),a
    ex af,af'
    ret
jp_hl:
    jp (hl)

; NES mapper write: A = NES bank 0..6 -> slot 2 page bank+1
rt_nes_bank:
    push af
    and 7
    ld (cur_nesbank),a
    inc a
    ld (0FFFFh),a
    pop af
    ret

; native sub_FFCD_prg_bankswitch_with_backup / sub_FFCF_prg_bankswitch
rt_ffcd:
    ld (NESRAM+009Bh),a         ; ram_prg_bank
rt_ffcf:
    ld (NESRAM+00BFh),a         ; ram_nmi_restore_prg_bank
    push af
    ld a,c
    ld (NESRAM+009Ch),a
    ld a,e
    ld (NESRAM+009Dh),a
    pop af
    call rt_nes_bank
    inc e
    dec e                       ; flags from LDY, carry kept
    ret

; JMP (ind): HL = NES address, IX = table, IY = entry count
; table entries: dw nesaddr / db nesbank, page / dw z80addr, sorted by (bankkey, addr)
rt_dispatch:
    push af
    push bc
    push de
    ld (dsp_key),hl
    ld a,h
    cp 0C0h
    ld a,0FFh
    jr nc,.kb
    ld a,(cur_nesbank)
.kb:
    ld (dsp_kb),a
    ld b,0                      ; lo
    ld a,iyl
    ld c,a                      ; hi
.loop:
    ld a,b
    cp c
    jr nc,.notfound
    add a,c
    rra
    ld (dsp_mid),a
    ld l,a
    ld h,0
    add hl,hl
    ld e,l
    ld d,h
    add hl,hl
    add hl,de                   ; mid*6
    push ix
    pop de
    add hl,de                   ; hl = entry
    inc hl
    inc hl
    ld a,(dsp_kb)
    cp (hl)
    jr c,.less
    jr nz,.greater
    dec hl
    ld a,(dsp_key+1)
    cp (hl)
    jr c,.less
    jr nz,.greater
    dec hl
    ld a,(dsp_key)
    cp (hl)
    jr c,.less
    jr nz,.greater
    inc hl
    inc hl
    inc hl
    ld a,(hl)                   ; page
    inc hl
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld hl,cur_zbank
    cp (hl)
    jr nz,.far
    ex de,hl
    pop de
    pop bc
    pop af
    jp (hl)
.far:
    ld (fc_bank),a
    ld (fc_jp+1),de
    pop de
    pop bc
    pop af
    ex af,af'
    ld hl,rt_ret
    push hl
    jp farcall_go
.less:
    ld a,(dsp_mid)
    ld c,a
    jr .loop
.greater:
    ld a,(dsp_mid)
    inc a
    ld b,a
    jr .loop
.notfound:
    ld hl,(dsp_key)
    ld (dbg_trap),hl
    ld a,0EEh
    jp rt_halt

; inline jump table after CALL (sound engine "jump_to_pointers_after_jsr")
; A = index; table of DW follows the CALL. Y (E) = A*2+2 like the original.
rt_jtab:
    pop hl
    add a,a
    ld e,a
    inc e
    inc e
    add a,l
    ld l,a
    jr nc,.nc
    inc h
.nc:
    ld a,(hl)
    inc hl
    ld h,(hl)
    ld l,a
    jp (hl)

; ---------------------------------------------------------------- traps
rt_untranslated:
    ld a,01h
    jr rt_trap
rt_fall_into_data:
    ld a,02h
    jr rt_trap
rt_bad_target:
    ld a,03h
    jr rt_trap
rt_brk:
    ld a,04h
rt_trap:
    pop hl
    ld (dbg_trap),hl
rt_halt:
    ld (dbg_trap+2),a
    di
.l: jr .l

; ---------------------------------------------------------------- frame
; Called by the scheduler when no thread is runnable: wait for vblank, push the
; pending video state to the VDP, then run the NES NMI handler.
rt_frame:
    ld (frame_sp),sp
    ld sp,RTSTACK
    push af
    push bc
    push de
    ; frameskip: if a vblank already passed since the last frame we are late:
    ; skip renders (at most MAXSKIP in a row) so the game logic keeps real time
    ld a,(vbl_count)
    ld hl,vbl_last
    cp (hl)
    jr z,.ontime
    ld a,(skipped)
    cp MAXSKIP
    jr nc,.render
    inc a
    ld (skipped),a
    call flush_light
    jr .rendered
.ontime:
    call wait_vblank
.render:
    xor a
    ld (skipped),a
    call flush_video
.rendered:
    ld a,(vbl_count)
    ld (vbl_last),a
    ld hl,(frame_cnt)
    inc hl
    ld (frame_cnt),hl
    ld a,(ppu_ctrl)
    bit 7,a
    jr z,.nonmi
    ld bc,0
    ld de,0
    call farcall
    db NES_NMI_BANK
    dw NES_NMI
    call apu_frame
    ; music runs in real time: one extra sound engine tick per extra vblank
    ld a,(vbl_count)
    ld hl,snd_last
    ld b,(hl)
    ld (hl),a
    sub b
    jr z,.nonmi
    dec a
    jr z,.nonmi
    cp 4
    jr c,.ex
    ld a,3
.ex:
    ld b,a
.xt:
    push bc
    ld a,(cur_nesbank)
    push af
    ld a,5
    call rt_nes_bank
    ld bc,0
    ld de,0
    call farcall
    db NES_SND_BANK
    dw NES_SND_UPDATE
    pop af
    call rt_nes_bank
    call apu_frame
    pop bc
    djnz .xt
.nonmi:
    pop de
    pop bc
    pop af
    ld sp,(frame_sp)
    ret

wait_vblank:                    ; wait for the next vblank interrupt
    ld a,(vbl_count)
    ld b,a
.w: halt
    ld a,(vbl_count)
    cp b
    jr z,.w
    ret
