; ===========================================================================
; Native Z80 versions of hot NES routines (NES RAM at 0C000h)
; ===========================================================================

; native sub_C1BC_hide_unused_sprites: instead of writing Y=F8 to unused OAM
; entries, remember how many are used (flush_sprites stops there)
rt_hide_sprites:
    ld a,(0C097h)                ; ram_oam_index
    cp 4
    jr nz,.n
    ld a,0F8h
    ld (0C200h),a
    ld a,4
.n: ; jump into the unrolled table at entry index/4 (3 bytes per entry)
    rrca
    rrca
    and 3Fh
    ld l,a
    add a,a
    add a,l
    ld l,a
    ld h,0
    jr nc,.nc
    inc h
.nc:
    push de
    ld de,.tab
    add hl,de
    pop de
    ld a,0F8h
    jp (hl)
.tab:
.k = 0
    REPT 64
    ld (0C200h+.k*4),a
.k = .k + 1
    ENDR
    ld c,0
    inc c
    dec c                       ; X = 0, Z set, carry kept
    ret

; native version of the sprite engine inner loop (bank 04, 8216-8258):
; writes OAM entries for the sprites of one animation frame.
; in: C = X (OAM index, non-zero), E = Y, RAM 0002/0005 pointers, 0004 counter,
;     0010 attr xor, 0011 priority, 0012 base Y, 0013 base X
rt_sprloop:
    ld hl,(0C002h)
    add hl,de
    push hl
    pop ix                      ; IX = p2 + Y
    ld hl,(0C005h)
    add hl,de
    push hl
    pop iy                      ; IY = p5 + Y
    ld a,(0C010h)
    ld b,a
    ld a,(0C011h)
    ld d,a
.loop:
    inc e
    inc ix
    inc iy
    ld h,0C2h
    ld l,c
    ld a,(ix+0)
    inc l
    ld (hl),a                   ; spr_T
    dec l
    ld a,(0C012h)
    add a,(iy+0)
    ld (hl),a                   ; spr_Y
    bit 7,(iy+0)
    jr nz,.n1
    jr c,.off1
    jr .ok1
.n1:
    jr nc,.off1
.ok1:
    inc e
    inc ix
    inc iy
    ld a,(ix+0)
    xor b
    or d
    inc l
    inc l
    ld (hl),a                   ; spr_A
    ld a,(0C013h)
    add a,(iy+0)
    inc l
    ld (hl),a                   ; spr_X
    bit 7,(iy+0)
    jr nz,.n2
    jr c,.off2
    jr .ok2
.n2:
    jr nc,.off2
.ok2:
    inc c
    inc c
    inc c
    inc c
    ld hl,0C097h
    ld (hl),c                   ; ram_oam_index
    jr z,.exit
.cont:
    ld hl,0C004h
    dec (hl)
    jp p,.loop
.exit:
    ld b,0
    ld d,0
    ret
.off1:
    inc e
    inc ix
    inc iy
.off2:
    ld h,0C2h
    ld l,c
    ld a,0F8h
    ld (hl),a
    jr .cont

; native sub_804D_display_player_hearts_with_sprites (bank 04 mapped at 8000h)
rt_hearts:
    ld a,(0C0BAh)                ; max hearts
    add a,a
    add a,a
    ld (0C097h),a                ; ram_oam_index
    ld c,a
    ld b,0
    push de
    ld hl,8070h                 ; tbl_8070_hearts_sprite_data
    ld de,0C200h
    ldir                        ; BC = 0 -> X = 0
    pop de
    ld a,(0C0B1h)                ; ram_hearts
    or a
    ret z
    add a,a
    add a,a
    ld c,a
.l: ld a,c
    sub 3
    ld l,a
    ld h,0C2h
    ld (hl),98h                 ; full heart tile
    ld a,c
    sub 4
    ld c,a
    jr nz,.l
    ld a,98h
    inc c
    dec c
    ret

; native sub_C0CB / sub_C0CF_write_buffer_to_ppu (X = offset into ram_ppu_buffer 0780h)
rt_ppubuf0:
    ld c,0
    xor a
    ld (0C019h),a                ; ram_buffer_ready_flag
rt_ppubuf:
.lp:
    ld hl,0C780h
    add hl,bc
    ld a,(hl)
    or a
    ret m
    call ppu_w2006
    ld hl,0C781h
    add hl,bc
    ld a,(hl)
    call ppu_w2006
    ld hl,0C782h
    add hl,bc
    ld e,(hl)                   ; Y = count-1
.l2:
    ld hl,0C783h
    add hl,bc
    ld a,(hl)
    call ppu_w2007
    inc c
    dec e
    jp p,.l2
    inc c
    inc c
    inc c
    jr nz,.lp
    ret

; native sub_C118_read_joy_regs
rt_read_joy:
    push af
    push de
    call read_input             ; msx order: b0 A .. b7 Right
    ld l,a
    ld h,high BITREV
    ld a,(hl)                   ; NES order: b7 A .. b0 Right
    ld hl,0C014h                 ; ram_btn_press
    ld (hl),a
    inc hl
    ld (hl),0
    xor a
    ld (0C000h),a
    ld (0C001h),a
    ; press = (new ^ hold) & new ; hold = new
    ld de,0C016h                 ; ram_btn_hold
    ld hl,0C014h
    ld b,2
.ph:
    ld c,(hl)
    ld a,(de)
    xor c
    and c
    ld (hl),a
    ld a,c
    ld (de),a
    inc hl
    inc de
    djnz .ph
    ; opposite directions -> keep only SSAB
    ld hl,0C014h
    ld b,4
.op:
    ld a,(hl)
    and 0Ch
    cp 0Ch
    jr z,.cl
    ld a,(hl)
    and 03h
    cp 03h
    jr nz,.nx
.cl:
    ld a,(hl)
    and 0F0h
    ld (hl),a
.nx:
    inc hl
    djnz .op
    ld a,(0C014h)
    ld e,a
    pop af
    ld a,e
    pop de
    ld bc,00FFh                 ; X = FF, B = 0
    ret


; native sub_80EC (sound engine): APU register write. A = value, X = channel, Y = reg 0..3
; reg = ((X & 3) ^ 3) * 4 | Y ; Y <- reg ; flags from the value (PLA)
rt_apuw:
    ld (0C0C4h),a                ; (STY ram_00C4 uses Y; keep value safe in L)
    ld l,a
    ld a,e
    ld (0C0C4h),a                ; ram_00C4_se_t03 = Y
    ld a,c
    and 3
    xor 3
    add a,a
    add a,a
    or e
    ld e,a                      ; Y = reg
    ld a,l
    ld h,high APU_SH
    ld l,e
    ld (hl),a
    set 5,l
    ld (hl),1
    inc a
    dec a                       ; Z/N from value
    ret


; native sub_0x010013_sprite_engine (bank 04 code; zbank 9 mapped): loops over the
; 16 objects (alternating direction each frame) and calls the translated sub_8084
rt_sprengine:
    call rt_hearts
    ld hl,0C095h                 ; ram_frm_cnt_2
    inc (hl)
    ld a,(hl)
    rrca
    jr c,.rev
    ld c,0
.f: ld a,c
    ld (0C096h),a
    call .obj
    ld hl,0C096h
    inc (hl)
    ld c,(hl)
    ld a,c
    cp 10h
    jr nz,.f
    ret
.rev:
    ld c,0Fh
.r: ld a,c
    ld (0C096h),a
    call .obj
    ld hl,0C096h
    dec (hl)
    ld c,(hl)
    bit 7,c
    jr z,.r
    ret
.obj:
    ld h,0C3h
    ld l,c
    ld a,(hl)                   ; ram_obj_flags,X
    or a
    jp m,Z04_8084
    ld a,0A0h
    add a,c
    ld l,a
    ld h,0C4h
    ld (hl),0                   ; ram_04A0_obj,X
    ld a,0E0h
    add a,c
    ld l,a
    ld h,0C3h
    ld (hl),0FFh                ; ram_03E0_obj_data_index,X
    ret
