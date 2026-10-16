; ===========================================================================
; NES PPU registers
; ===========================================================================
ppu_w2000:
    push af
    ld (ppu_ctrl),a
    ld hl,1
    bit 2,a
    jr z,.i
    ld l,32
.i: ld (ppu_inc),hl
    pop af
    ret

; rendering on/off -> SMS display on/off
ppu_w2001:
    push af
    ld (ppu_mask),a
    and 18h
    ld a,(vdp_r1)
    jr z,.off
    or 40h
    jr .s
.off:
    and 0BFh
.s: ld (vdp_r1),a
    VDPREG 1
    pop af
    ret

ppu_r2002:                      ; returns A, preserves carry
    ld hl,stat_tog
    ld a,(hl)
    cpl
    ld (hl),a
    ld hl,ppu_w
    ld (hl),0
    ret

ppu_w2005:
    push af
    ld hl,ppu_w
    ld a,(hl)
    xor 1
    ld (hl),a
    jr z,.y
    pop af
    ld (scroll_x),a
    ret
.y: pop af
    ld (scroll_y),a
    ret

ppu_w2006:
    push af
    ld hl,ppu_w
    ld a,(hl)
    xor 1
    ld (hl),a
    jr z,.lo
    pop af
    push af
    and 3Fh
    ld (ppu_v+1),a
    pop af
    ret
.lo:
    pop af
    ld (ppu_v),a
    ret

ppu_r2007:
    ld a,0
    ret

ppu_w4014:                      ; OAM DMA: remember the page
    ld (oam_page),a
    ret

; ---------------------------------------------------------------- $2007 writes
; runs on its own stack: the game's threads have little stack room (4 thread
; stacks share page 1) and this handler nests several calls
ppu_w2007:
    ld (hsave),sp
    ld sp,HSTACK
    call ppu_w2007_
    ld sp,(hsave)
    ret
ppu_w2007_:
    push af
    push bc
    push de
    ld c,a                      ; value
    ld hl,(ppu_v)
    ld a,h
    and 3Fh
    ld h,a
    cp 20h
    jp c,.chr
    cp 3Fh
    jp z,.pal
    ; nametable: NTSH + (addr & 07FFh) (vertical mirroring)
    and 07h
    or high NTSH
    ld h,a
    ld a,(hl)
    cp c
    jr z,.done
    ld b,a                      ; old value
    ld (hl),c
    ld a,h
    and 03h
    cp 03h
    jr nz,.tile
    ld a,l
    cp 0C0h
    jr nc,.attr
.tile:
    call queue_cell
    jr .done
.attr:
    ld a,b
    xor c                       ; changed bits
    call queue_attr
.done:
    ld hl,(ppu_v)
    ld de,(ppu_inc)
    add hl,de
    ld (ppu_v),hl
    pop de
    pop bc
    pop af
    ret
.pal:
    ld a,l
    and 1Fh
    ld l,a
    and 13h
    cp 10h
    ld a,l
    jr nz,.p1
    and 0Fh                     ; $3F10/14/18/1C mirror $3F00/04/08/0C
.p1:
    add a,low NESPAL
    ld l,a
    ld h,high NESPAL
    ld a,c
    and 3Fh
    ld (hl),a
    ld a,1
    ld (pal_dirty),a
    jr .done
.chr:
    ; HL = 0000-1FFF: copy to cartridge RAM, mark the tile dirty
    ld a,SRAM_ON
    ld (0FFFCh),a
    set 7,h                     ; CHR = 8000h
    ld (hl),c
    xor a
    ld (0FFFCh),a
    res 7,h
    ; tile = HL >> 4 (0..511): bit (tile & 7) of CHRDIRTY[tile >> 3]
    ld a,l
    rrca
    rrca
    rrca
    rrca
    and 0Fh
    ld e,a                      ; low 4 bits of tile
    ld a,h
    add a,a
    add a,a
    add a,a
    add a,a
    or e                        ; tile & 0FFh
    ld e,a
    and 7
    ld b,a
    ld a,e
    rrca
    rrca
    rrca
    and 1Fh
    ld e,a
    ld a,h
    and 10h                     ; tile bit 8 -> +32
    add a,a
    add a,e
    add a,low CHRDIRTY
    ld l,a
    ld h,high CHRDIRTY
    ld a,b
    call bit_mask
    or (hl)
    ld (hl),a
    ld a,1
    ld (chr_dirty_n),a
    jp .done

; A = 0..7 -> A = 1 << A
bit_mask:
    push hl
    ld hl,bit_tab
    add a,l
    ld l,a
    jr nc,.n
    inc h
.n: ld a,(hl)
    pop hl
    ret
bit_tab:
    db 1,2,4,8,16,32,64,128

; ---------------------------------------------------------------- dirty cell queue
; HL = NTSH address of a tile that changed: queue it if its column is on screen
queue_cell:
    ld a,(full_redraw)
    or a
    ret nz
    ; NES column = nt*32 + col; on screen if COLMAP[col] == it
    ld a,l
    and 1Fh
    ld e,a                      ; col
    ld a,h
    and 04h                     ; nt * 4
    add a,a
    add a,a
    add a,a                     ; nt * 32
    or e
    ld d,a                      ; NES column
    ld a,e
    add a,low COLMAP
    ld e,a
    ld a,d
    ld d,high COLMAP
    ex de,hl
    cp (hl)
    ex de,hl
    ret nz
queue_any:                      ; HL = NTSH address
    ld a,(dq_count)
    cp 128
    jr nc,.full
    inc a
    ld (dq_count),a
    dec a
    add a,a
    ld e,a
    ld d,high DIRTYQ
    ld a,l
    ld (de),a
    inc e
    ld a,h
    ld (de),a
    ret
.full:
    ld a,1
    ld (full_redraw),a
    ret

; HL = NTSH address of an attribute byte, A = changed bits: queue the cells of the
; changed 16x16 quadrants
queue_attr:
    ld d,a
    ld a,(full_redraw)
    or a
    ret nz
    ; top-left cell of the 32x32 block: row = (ofs-3C0h)>>3 * 4, col = (ofs & 7) * 4
    ld a,l
    and 07h
    add a,a
    add a,a
    ld c,a                      ; col
    ld a,l
    sub 0C0h
    and 38h
    rrca
    ld b,a                      ; row*... = ((ofs>>3)&7)*4
    ld a,h
    and 0FCh
    ld h,a                      ; nametable base
    ld a,d
    and 03h
    call nz,.q00
    ld a,d
    and 0Ch
    jr z,.n1
    inc c
    inc c
    call .q00
    dec c
    dec c
.n1:
    ld a,d
    and 30h
    jr z,.n2
    inc b
    inc b
    call .q00
    dec b
    dec b
.n2:
    ld a,d
    and 0C0h
    ret z
    inc b
    inc b
    inc c
    inc c
    ; fall through
.q00:                           ; queue the 2x2 cells at row B, col C (H = nametable base)
    ld a,b
    cp 30
    ret nc
    push hl
    push de
    call .one
    inc c
    call .one
    inc b
    call .one
    dec c
    call .one
    dec b
    pop de
    pop hl
    ret
.one:
    ld a,b
    cp 30
    ret nc
    push hl
    push bc
    ; HL = base + row*32 + col
    ld a,b
    rrca
    rrca
    rrca
    ld l,a
    and 03h
    or h
    ld h,a
    ld a,l
    and 0E0h
    or c
    ld l,a
    call queue_cell
    pop bc
    pop hl
    ret
