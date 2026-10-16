; ===========================================================================
; Joypad: NES $4016 serial reads, from the SMS pad (port DCh) or a TAS stream
; ===========================================================================
joy_w4016:
    ld (hsave),sp
    ld sp,HSTACK
    call joy_w4016_
    ld sp,(hsave)
    ret
joy_w4016_:
    push af
    and 1
    jr z,.x
    push bc
    push de
    call read_input
    ld (joy_shift),a
    pop de
    pop bc
.x: pop af
    ret

joy_r4016:
    push af
    ld hl,joy_shift
    ld a,(hl)
    srl (hl)
    and 1
    ld h,a
    pop af
    ld a,h
    ret

joy_r4017:
    ld a,0
    ret

; returns A = NES buttons: b0 A, b1 B, b2 Select, b3 Start, b4 Up, b5 Down, b6 Left, b7 Right
read_input:
    IFDEF TAS_MODE
    ld hl,(tas_ptr)
    ld de,TAS_LEN
    or a
    sbc hl,de
    ld a,0
    ret nc                      ; movie finished
    ld hl,(tas_ptr)
    ld a,h
    rlca
    rlca
    and 3
    add a,TAS_PAGE
    ld (0FFFFh),a
    ld a,h
    and 3Fh
    or 80h
    ld h,a
    ld c,(hl)
    ld a,(cur_nesbank)
    inc a
    ld (0FFFFh),a
    ld hl,(tas_ptr)
    inc hl
    ld (tas_ptr),hl
    ld a,c
    ret
    ENDIF
    ; SMS pad 1 (active low): b0 up, b1 down, b2 left, b3 right, b4 button 1, b5 button 2
    in a,(0DCh)
    cpl
    ld b,a
    and 0Fh
    rlca
    rlca
    rlca
    rlca                        ; directions -> b4-b7
    ld c,a
    bit 5,b
    jr z,$+4
    set 0,c                     ; button 2 -> A
    bit 4,b
    jr z,$+4
    set 1,c                     ; button 1 -> B
    ld a,(pause_cnt)            ; PAUSE button -> Start for a few frames
    or a
    jr z,.np
    dec a
    ld (pause_cnt),a
    set 3,c
.np:
    ld a,c
    ret

; ===========================================================================
; NES APU -> SN76489 PSG (port 7Fh)
;   pulse 1 -> tone 0, pulse 2 -> tone 1, triangle -> tone 2, noise -> noise
; Same clock as the NES pulses: PSG period = NES timer + 1 (10 bits: low notes
; go up one octave). Volume: NES linear 0-15 -> PSG attenuation.
; ===========================================================================

    ; length counter load + envelope restart when the 4th register of a channel is written
    MACRO TRIG _rg, _eb, _lv, _ev
        ld a,(APU_W+_rg)
        or a
        jr z,.s
        xor a
        ld (APU_W+_rg),a
        ld a,(apu_en)
        and _eb
        jr z,.e
        ld a,(APU_SH+_rg)
        rrca
        rrca
        rrca
        and 1Fh
        ld hl,len_tab
        add a,l
        ld l,a
        jr nc,$+3
        inc h
        ld a,(hl)
        ld (_lv),a
.e:
        ld a,15
        ld (_ev),a
.s:
    ENDM
    ; 2 length clocks (half frames) unless halted
    MACRO LEN _ct, _hb, _lv
        ld a,(APU_SH+_ct)
        bit _hb,a
        jr nz,.s
        ld a,(_lv)
        sub 2
        jr nc,.w
        xor a
.w:     ld (_lv),a
.s:
    ENDM

apu_frame:
    ld a,(APU_W+15h)
    or a
    jr z,.n15
    xor a
    ld (APU_W+15h),a
    ld a,(APU_SH+15h)
    ld (apu_en),a
    ld c,a
    ld hl,apu_len
    ld b,4
.dis:
    rr c
    jr c,.de
    ld (hl),0
.de:
    inc hl
    djnz .dis
.n15:
    TRIG 03h, 01h, apu_len+0, apu_envv+0
    TRIG 07h, 02h, apu_len+1, apu_envv+1
    TRIG 0Fh, 08h, apu_len+3, apu_envv+2
    ; triangle: length + linear reload flag
    ld a,(APU_W+0Bh)
    or a
    jr z,.nt
    xor a
    ld (APU_W+0Bh),a
    ld a,1
    ld (apu_linrl),a
    ld a,(apu_en)
    and 04h
    jr z,.nt
    ld a,(APU_SH+0Bh)
    rrca
    rrca
    rrca
    and 1Fh
    ld hl,len_tab
    add a,l
    ld l,a
    jr nc,$+3
    inc h
    ld a,(hl)
    ld (apu_len+2),a
.nt:
    ld a,(APU_SH+00h)
    ld hl,apu_envv+0
    ld de,apu_envd+0
    call env4
    ld a,(APU_SH+04h)
    ld hl,apu_envv+1
    ld de,apu_envd+1
    call env4
    ld a,(APU_SH+0Ch)
    ld hl,apu_envv+2
    ld de,apu_envd+2
    call env4
    ; triangle linear counter (4 clocks)
    ld a,(apu_linrl)
    or a
    ld a,(APU_SH+8)
    jr z,.ld
    and 7Fh
    ld (apu_lin),a
    ld a,(APU_SH+8)
    and 80h
    jr nz,.lc
    ld (apu_linrl),a            ; a = 0
    jr .lc
.ld:
    ld a,(apu_lin)
    sub 4
    jr nc,.l2
    xor a
.l2:
    ld (apu_lin),a
.lc:
    LEN 00h, 5, apu_len+0
    LEN 04h, 5, apu_len+1
    LEN 08h, 7, apu_len+2
    LEN 0Ch, 5, apu_len+3
    ; ---- pulse 1 -> tone 0
    ld a,(APU_SH+3)
    and 7
    ld h,a
    ld a,(APU_SH+2)
    ld l,a
    ld c,00h
    call psg_period             ; HL = timer: period t+1, Z if inaudible (t < 8)
    ld a,(apu_len+0)
    jr z,.q1
    or a
    jr z,.q1
    ld a,(APU_SH+0)
    bit 4,a
    jr nz,.c1
    ld a,(apu_envv+0)
.c1:
    and 0Fh
    jr .v1
.q1:
    xor a
.v1:
    ld c,90h
    call psg_vol
    ; ---- pulse 2 -> tone 1
    ld a,(APU_SH+7)
    and 7
    ld h,a
    ld a,(APU_SH+6)
    ld l,a
    ld c,20h
    call psg_period
    ld a,(apu_len+1)
    jr z,.q2
    or a
    jr z,.q2
    ld a,(APU_SH+4)
    bit 4,a
    jr nz,.c2
    ld a,(apu_envv+1)
.c2:
    and 0Fh
    jr .v2
.q2:
    xor a
.v2:
    ld c,0B0h
    call psg_vol
    ; ---- triangle -> tone 2: period 2(t+1)
    ld a,(APU_SH+0Bh)
    and 7
    ld h,a
    ld a,(APU_SH+0Ah)
    ld l,a
    inc hl
    add hl,hl
    dec hl
    ld c,40h
    call psg_period
    ld a,0
    jr z,.tq
    ld a,(apu_len+2)
    or a
    jr z,.tq
    ld a,(apu_lin)
    or a
    jr z,.tq
    ld a,11
.tq:
    ld c,0D0h
    call psg_vol
    ; ---- noise
    ld a,(APU_SH+0Eh)
    and 0Fh
    ld c,0E4h                   ; white noise, clock / 512
    cp 4
    jr c,.nr
    inc c                       ; / 1024
    cp 8
    jr c,.nr
    inc c                       ; / 2048
.nr:
    ld a,(psg_noise)
    cp c
    jr z,.ns
    ld a,c
    ld (psg_noise),a
    out (7Fh),a                 ; (writing resets the noise generator)
.ns:
    ld a,(apu_len+3)
    or a
    jr z,.nq
    ld a,(apu_en)
    and 8
    jr z,.nq
    ld a,(APU_SH+0Ch)
    bit 4,a
    jr nz,.nc
    ld a,(apu_envv+2)
.nc:
    and 0Fh
    jr .nv
.nq:
    xor a
.nv:
    ld c,0F0h
    jp psg_vol

; HL = NES timer, C = channel bits (00h/20h/40h): write the tone period (t + 1,
; raised by octaves to fit 10 bits). Returns Z if the channel must be silent.
psg_period:
    ld a,h
    or a
    jr nz,.ok
    ld a,l
    cp 8
    jr nc,.ok
    xor a                       ; Z: inaudible
    ret
.ok:
    inc hl
.fit:
    ld a,h
    cp 4
    jr c,.w
    srl h
    rr l
    jr .fit
.w: ld a,l
    and 0Fh
    or 80h
    or c
    out (7Fh),a                 ; latch + low 4 bits
    ld a,h
    add a,a
    add a,a
    add a,a
    add a,a
    ld h,a
    ld a,l
    rrca
    rrca
    rrca
    rrca
    and 0Fh
    or h
    out (7Fh),a                 ; high 6 bits
    or 1                        ; NZ
    ret

; A = NES volume 0-15, C = latch bits for the channel volume register
psg_vol:
    ld hl,att_tab
    add a,l
    ld l,a
    jr nc,$+3
    inc h
    ld a,(hl)
    or c
    out (7Fh),a
    ret

; 4 envelope clocks. A = control reg, HL = volume, DE = divider
env4:
    bit 4,a
    ret nz                      ; constant volume
    ld (env_ctl),a
    and 0Fh
    ld c,a
    ld b,4
.l: ld a,(de)
    or a
    jr z,.t
    dec a
    ld (de),a
    jr .n
.t: ld a,c
    ld (de),a
    ld a,(hl)
    or a
    jr z,.z
    dec (hl)
    jr .n
.z: ld a,(env_ctl)
    bit 5,a
    jr z,.n
    ld (hl),15
.n: djnz .l
    ret

len_tab:
    db 10,254,20,2,40,4,80,6,160,8,60,10,14,12,26,14
    db 12,16,24,18,48,20,96,22,192,24,72,26,16,28,32,30
att_tab:                        ; NES linear volume -> PSG attenuation (2 dB steps)
    db 15,12,9,7,6,5,4,3,3,2,2,1,1,1,0,0
