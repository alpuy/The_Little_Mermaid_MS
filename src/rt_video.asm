; ===========================================================================
; Video flush: NES PPU state -> SMS VDP (mode 4, 224 lines)
;
; Background: the SMS name table holds 32 of the 64 NES columns (the ones on
; screen, COLMAP) and the 30 NES rows in 32 SMS rows (ROWMAP, with 2 spare rows
; that move with the vertical scroll). Each cell shows a pattern made for its
; (tile, palette) pair: the 4 NES background palettes are merged into SMS
; palette 0 (colour 3*pal + pixel). Patterns live in slots 0-255, reference counted.
; Sprites: 4 NES sprite palettes merged into SMS palette 1; patterns per
; (tile, palette, flips) in slots 256-439 (SMS sprites cannot flip).
; ===========================================================================

flush_light:
    ret

flush_video:
    ld a,(ppu_mask)
    and 18h
    jr z,.nospr
    call flush_sprites
.nospr:
    ld a,(pal_dirty)
    or a
    call nz,flush_palette
    ld a,(chr_dirty_n)
    or a
    call nz,flush_chr
    ld a,(full_redraw)
    or a
    jr z,.nofull
    xor a
    ld (full_redraw),a
    ld (dq_count),a
    ld hl,COLMAP
    ld b,32
.fc:ld (hl),0FFh
    inc l
    djnz .fc
.nofull:
    call flush_scroll
    jp flush_queue

; ---------------------------------------------------------------- palette
flush_palette:
    xor a
    ld (pal_dirty),a
    ld hl,0
    di
    ld a,l
    out (0BFh),a
    ld a,0C0h
    out (0BFh),a                ; CRAM 0
    ei
    ; background: 0, pal0 1-3, pal1 1-3, pal2 1-3, pal3 1-3, 3 unused
    ld hl,NESPAL
    call .one
    ld b,4
.bg:inc l
    call .one
    inc l
    call .one
    inc l
    call .one
    inc l
    djnz .bg
    call .zero3
    ; sprites: 16 = backdrop (border), then the 4 sprite palettes
    ld l,low NESPAL
    call .one
    ld l,low NESPAL+10h
    ld b,4
.sp:inc l
    call .one
    inc l
    call .one
    inc l
    call .one
    inc l
    djnz .sp
.zero3:
    xor a
    out (0BEh),a
    nop
    nop
    nop
    out (0BEh),a
    nop
    nop
    nop
    out (0BEh),a
    ret
.one:
    ld a,(hl)
    push hl
    ld hl,nes2sms
    add a,l
    ld l,a
    jr nc,.n
    inc h
.n: ld a,(hl)
    out (0BEh),a
    pop hl
    ret

; ---------------------------------------------------------------- CHR changes
flush_chr:
    xor a
    ld (chr_dirty_n),a
    ld hl,CHRDIRTY
    ld c,0                      ; tile (low 8 bits)
.byte:
    ld a,(hl)
    or a
    jr nz,.bits
    ld a,c
    add a,8
    ld c,a
    jr nz,.nx
    ; crossed from sprite tiles to background tiles
.nx:
    inc l
    ld a,l
    cp low CHRDIRTY+64
    jr nz,.byte
    ret
.bits:
    ld (hl),0
    ld b,8
.bit:
    rrca
    jr nc,.nb
    push af
    push bc
    push hl
    ld a,l
    sub low CHRDIRTY
    cp 32
    ld a,c
    jr nc,.bg
    call spr_tile_inval
    jr .done
.bg:call bg_tile_regen
.done:
    pop hl
    pop bc
    pop af
.nb:
    inc c
    djnz .bit
    jr .nx

; A = background tile whose CHR changed: rebuild its patterns
bg_tile_regen:
    ld (cell_tile),a
    ld l,a
    ld h,high BGMAP
    ld b,4
.p: ld a,(hl)
    cp 0FFh
    jr z,.n
    push hl
    push bc
    ld e,a
    ld a,h
    sub high BGMAP
    ld (cell_pal),a
    ld a,e
    call gen_bg
    pop bc
    pop hl
.n: inc h
    djnz .p
    ret

; A = sprite tile whose CHR changed: forget its patterns (made again when used)
spr_tile_inval:
    ld e,a
    ld a,SRAM_ON
    ld (0FFFCh),a
    ld l,e
    ld h,high SPRMAP
    ld b,16
.p: ld a,(hl)
    ld (hl),0FFh
    cp 0FFh
    jr z,.n
    push hl
    ld l,a
    ld h,high SPRATTR
    ld (hl),0FFh
    pop hl
.n: inc h
    djnz .p
    xor a
    ld (0FFFCh),a
    ret

; ---------------------------------------------------------------- scroll
flush_scroll:
    ; ---- horizontal: x = scroll_x + 256 * (ctrl & 1)
    ld a,(scroll_x)
    ld l,a
    ld a,(ppu_ctrl)
    and 1
    ld h,a
    ld a,l
    neg
    ld (reg8),a
    ld de,8
    add hl,de                   ; first visible pixel (left column is blanked)
    ; base column = (x+8) >> 3 (mod 64)
    srl h
    rr l
    srl h
    rr l
    srl h
    rr l
    ld a,l
    and 3Fh
    ld d,a                      ; base
    ; for each SMS column s: wanted c = base + ((s - base) & 31)
    ld e,0
.col:
    ld a,e
    sub d
    and 1Fh
    add a,d
    and 3Fh
    ld c,a
    ld a,e
    add a,low COLMAP
    ld l,a
    ld h,high COLMAP
    ld a,c
    cp (hl)
    jr z,.cok
    ld (hl),a
    push de
    call copy_col               ; C = NES column
    pop de
.cok:
    inc e
    ld a,e
    cp 32
    jr nz,.col
    ; ---- vertical: first visible NES line = (scroll_y + CROP) mod 240
    ld a,(scroll_y)
    cp 240
    jr c,.y1
    sub 240
.y1:add a,CROP
    cp 240
    jr c,.y2
    sub 240
.y2:ld b,a
    and 7
    ld (tmp1),a                 ; fine y
    ld a,b
    rrca
    rrca
    rrca
    and 1Fh
    ld b,a                      ; top row t
    ; spare rows at 'gap' must be just above t: gap == t or gap == t-1 (mod 30)
    ld a,(gap)
    cp b
    jr z,.gok
    inc a
    cp 30
    jr c,.g1
    xor a
.g1:cp b
    jr z,.gok
    ; move the gap to t: rows between the old and the new gap change SMS row
    push bc
    ld hl,ROWMAP
    ld de,tmprow
    ld bc,30
    ldir
    pop bc
    ld a,b
    ld (gap),a
    call set_rowmap
    ld b,0
.rc:ld a,b
    add a,low tmprow
    ld l,a
    ld h,high tmprow
    ld c,(hl)                   ; old SMS row
    ld a,b
    add a,low ROWMAP
    ld l,a
    ld h,high ROWMAP
    ld a,(hl)
    cp c
    jr z,.rs
    push bc
    call copy_row               ; B = NES row
    pop bc
.rs:inc b
    ld a,b
    cp 30
    jr nz,.rc
    ; recompute t (B was used)
    ld a,(gap)
    ld b,a
.gok:
    ld a,b
    add a,low ROWMAP
    ld l,a
    ld h,high ROWMAP
    ld a,(hl)
    add a,a
    add a,a
    add a,a
    ld hl,tmp1
    add a,(hl)
    ld (reg9),a
    ; write the scroll registers
    ld a,(reg8)
    VDPREG 8
    ld a,(reg9)
    VDPREG 9
    ret

tmprow equ VARS+60h              ; 30 bytes: previous ROWMAP

; ROWMAP[r] = r < gap ? r : r + 2
set_rowmap:
    ld a,(gap)
    ld c,a
    ld hl,ROWMAP
    ld b,0
.l: ld a,b
    cp c
    jr c,.s
    add a,2
.s: ld (hl),a
    inc l
    inc b
    ld a,b
    cp 30
    jr nz,.l
    ret

; C = NES column (0-63): draw it in SMS column C & 31
copy_col:
    ld b,0
.r: push bc
    ld a,c
    and 1Fh
    ld e,a
    ld a,c
    rlca
    rlca
    rlca
    and 01h
    ld d,a                      ; nt
    ld c,e
    call cell_draw
    pop bc
    inc b
    ld a,b
    cp 30
    jr nz,.r
    ret

; B = NES row: draw it for every SMS column showing a NES column
copy_row:
    ld e,0
.c: ld a,e
    add a,low COLMAP
    ld l,a
    ld h,high COLMAP
    ld a,(hl)
    cp 0FFh
    jr z,.n
    push de
    push bc
    rlca
    rlca
    rlca
    and 01h
    ld d,a
    ld c,e
    call cell_draw
    pop bc
    pop de
.n: inc e
    ld a,e
    cp 32
    jr nz,.c
    ret

; ---------------------------------------------------------------- queued cells
flush_queue:
    ld a,(dq_count)
    or a
    ret z
    ld b,a
    xor a
    ld (dq_count),a
    ld hl,DIRTYQ
.q: push bc
    push hl
    ld e,(hl)
    inc l
    ld d,(hl)                   ; NTSH address
    ; nt = bit 2 of D, row = (DE >> 5) & 31, col = E & 31
    ld a,e
    and 1Fh
    ld c,a
    ld a,d
    and 03h
    ld b,a
    ld a,e
    rlca
    rlca
    rlca
    and 07h
    ld l,a
    ld a,b
    add a,a
    add a,a
    add a,a
    or l
    ld b,a                      ; row
    cp 30
    jr nc,.skip
    ld a,d
    rrca
    rrca
    and 01h
    ld d,a                      ; nt
    ; still on screen?
    rrca
    rrca
    rrca                        ; nt * 32
    or c
    ld e,a
    ld a,c
    add a,low COLMAP
    ld l,a
    ld h,high COLMAP
    ld a,e
    cp (hl)
    call z,cell_draw
.skip:
    pop hl
    inc l
    inc l
    pop bc
    djnz .q
    ret

; ---------------------------------------------------------------- one cell
; B = NES row (0-29), C = column (0-31), D = nametable (0/1)
cell_draw:
    ld a,d
    add a,a
    add a,a
    add a,high NTSH
    ld h,a
    ld a,b
    rrca
    rrca
    rrca
    ld l,a
    and 03h
    add a,h
    ld h,a
    ld a,l
    and 0E0h
    or c
    ld l,a
    ld a,(hl)
    ld (cell_tile),a
    ; attribute: base + 3C0h + (row>>2)*8 + (col>>2)
    ld a,h
    or 03h
    ld h,a
    ld a,b
    and 1Ch
    add a,a
    ld l,a
    ld a,c
    rrca
    rrca
    and 07h
    or l
    or 0C0h
    ld l,a
    ld a,(hl)
    bit 1,b
    jr z,.a1
    rrca
    rrca
    rrca
    rrca
.a1:bit 1,c
    jr z,.a2
    rrca
    rrca
.a2:and 03h
    ld (cell_pal),a
    ; SMS cell = ROWMAP[row]*32 + col
    ld a,b
    add a,low ROWMAP
    ld l,a
    ld h,high ROWMAP
    ld a,(hl)
    rrca
    rrca
    rrca
    ld l,a
    and 03h
    add a,high CELLSLOT
    ld h,a
    ld a,l
    and 0E0h
    or c
    ld l,a                      ; HL = CELLSLOT + cell
    push hl
    call bg_slot                ; A = slot
    pop hl
    cp (hl)
    ret z                       ; already shown
    ld e,(hl)
    ld (hl),a
    ld d,a
    ; reference counts
    ld a,e
    cp 0FFh
    jr z,.nold
    ld e,a
    push hl
    ld h,high REFCNT
    ld l,e
    dec (hl)
    pop hl
.nold:
    push hl
    ld h,high REFCNT
    ld l,d
    inc (hl)
    pop hl
    ; VRAM: VR_NT + cell*2
    ld a,h
    sub high CELLSLOT
    ld h,a
    add hl,hl
    ld a,h
    add a,high VR_NT
    ld h,a
    ld a,l
    di
    out (0BFh),a
    ld a,h
    or 40h
    out (0BFh),a
    ei
    ld a,d
    out (0BEh),a                ; pattern (slots 0-255), palette 0, no flip
    xor a
    nop
    nop
    nop
    out (0BEh),a
    ret

; cell_tile, cell_pal -> A = pattern slot (made if needed)
bg_slot:
    ld a,(cell_pal)
    add a,high BGMAP
    ld h,a
    ld a,(cell_tile)
    ld l,a
    ld a,(hl)
    cp 0FFh
    ret nz
    push hl
    push bc
    push de
    ; a slot no cell uses
    ld a,(bg_clock)
    ld l,a
    ld h,high REFCNT
    ld b,0
.s: inc l
    ld a,(hl)
    or a
    jr z,.got
    djnz .s
.got:
    ld a,l
    ld (bg_clock),a
    ; forget its old (tile, pal)
    ld h,high SLOTPAL
    ld a,(hl)
    cp 0FFh
    jr z,.nf
    add a,high BGMAP
    ld d,a
    ld h,high SLOTTILE
    ld e,(hl)
    ld a,0FFh
    ld (de),a
.nf:
    ld h,high SLOTTILE
    ld a,(cell_tile)
    ld (hl),a
    inc h
    ld a,(cell_pal)
    ld (hl),a
    ld a,l
    pop de
    pop bc
    pop hl
    ld (hl),a
    push af
    call gen_bg
    pop af
    ret

; A = slot: make the pattern of (cell_tile, cell_pal)
gen_bg:
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    call vram_wr
    ld a,(cell_tile)
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    ld de,CHR+1000h
    add hl,de
    push hl
    pop ix
    ld a,(cell_pal)
    ld c,1                      ; row step
    jp gen_pattern

; IX = NES tile (16 bytes), C = row step (+1 or -1 for vertical flip),
; A = palette, VRAM address set. Optional horizontal flip: gen_pattern_h.
gen_pattern:
    ld hl,.tab
    add a,a
    add a,l
    ld l,a
    jr nc,.n
    inc h
.n: ld a,(hl)
    inc hl
    ld h,(hl)
    ld l,a
    ld (tmpw),hl
    ld a,SRAM_ON
    ld (0FFFCh),a
    ld b,8
.row:
    ld d,(ix+0)                 ; low plane
    ld e,(ix+8)                 ; high plane
    ld a,(tmp2)
    or a
    jr z,.nh
    ld h,high BITREV
    ld l,d
    ld d,(hl)
    ld l,e
    ld e,(hl)
.nh:
    ld hl,(tmpw)
    call jp_hl
    ld a,c                      ; IX += C (signed)
    rla
    sbc a,a
    ld h,a
    ld a,ixl
    add a,c
    ld ixl,a
    ld a,ixh
    adc a,h
    ld ixh,a
    djnz .row
    xor a
    ld (0FFFCh),a
    ld (tmp2),a
    ret
.tab:
    dw .p0, .p1, .p2, .p3
    ; D = lo, E = hi -> 4 bitplanes (colour = 3*pal + pixel)
.p0:
    ld a,d
    out (0BEh),a
    ld a,e
    nop
    nop
    nop
    out (0BEh),a
    xor a
    nop
    nop
    nop
    out (0BEh),a
    nop
    nop
    nop
    nop
    out (0BEh),a
    ret
.p1:
    ld a,d
    cpl
    and e
    out (0BEh),a
    ld a,d
    and e
    nop
    nop
    out (0BEh),a
    ld a,d
    or e
    nop
    nop
    out (0BEh),a
    xor a
    nop
    nop
    nop
    out (0BEh),a
    ret
.p2:
    ld a,d
    out (0BEh),a
    ld a,e
    cpl
    and d
    nop
    nop
    out (0BEh),a
    nop
    nop
    nop
    nop
    out (0BEh),a
    ld a,e
    nop
    nop
    nop
    out (0BEh),a
    ret
.p3:
    ld a,d
    cpl
    and e
    out (0BEh),a
    ld a,d
    xor e
    nop
    nop
    out (0BEh),a
    ld a,d
    and e
    nop
    nop
    out (0BEh),a
    ld a,d
    or e
    nop
    nop
    out (0BEh),a
    ret

; ---------------------------------------------------------------- sprites
flush_sprites:
    ld a,(stamp)
    inc a
    ld (stamp),a
    ld a,SRAM_ON
    ld (0FFFCh),a
    ld a,(oam_page)
    add a,high NESRAM
    ld h,a
    ld l,0
    ld de,SATSH
    ld b,64
.s: ld a,(hl)                   ; y
    cp 0EFh
    jr c,.vis
    ld a,0E0h                   ; below the 224 visible lines
    ld (de),a
    inc l
    inc l
    inc l
    inc l
    jr .next
.vis:
    sub CROP
    ld (de),a
    inc l
    ld a,(hl)                   ; tile
    ld (cell_tile),a
    inc l
    ld a,(hl)                   ; attributes: palette, flips
    and 03h
    ld c,a
    ld a,(hl)
    rlca
    rlca
    and 03h
    add a,a
    add a,a
    or c
    ld (cell_pal),a             ; pal | hflip<<2 | vflip<<3
    inc l
    ld a,(hl)                   ; x
    inc l
    push hl
    push de
    push bc
    push af
    call spr_slot               ; A = slot
    ld c,a
    pop af
    pop de                      ; (B)
    ld b,d
    pop de
    ; x/pattern pair at SATSH + 40h + 2*i
    push de
    ld h,a
    ld a,e
    add a,a
    add a,40h
    ld e,a
    ld a,h
    ld (de),a
    inc e
    ld a,c
    ld (de),a
    pop de
    pop hl
.next:
    inc e
    djnz .s
    xor a
    ld (0FFFCh),a
    ; upload the sprite table (64 y + 64 x/n pairs at 3F80h)
    ld hl,VR_SAT
    call vram_wr
    ld hl,SATSH
    ld b,64
.u1:ld a,(hl)
    out (0BEh),a
    inc hl
    nop
    nop
    djnz .u1
    ld hl,VR_SAT+80h
    call vram_wr
    ld hl,SATSH+40h
    ld b,128
.u2:ld a,(hl)
    out (0BEh),a
    inc hl
    nop
    nop
    djnz .u2
    ret

; cell_tile, cell_pal (attr) -> A = sprite slot (0-183), pattern made if needed.
; Cartridge RAM must be mapped.
spr_slot:
    ld a,(cell_pal)
    add a,high SPRMAP
    ld h,a
    ld a,(cell_tile)
    ld l,a
    ld a,(hl)
    cp 0FFh
    jr z,.new
    ld l,a
    ld h,high SPRSTAMP
    ld a,(stamp)
    ld (hl),a
    ld a,l
    ret
.new:
    push hl
    ; a slot not used in this frame
    ld a,(spr_clock)
    ld l,a
    ld h,high SPRSTAMP
    ld a,(stamp)
    ld c,a
    ld b,NSPRSLOT
.f: inc l
    ld a,l
    cp NSPRSLOT
    jr c,.f1
    ld l,0
.f1:ld a,(hl)
    cp c
    jr nz,.got
    djnz .f
.got:
    ld (hl),c                   ; stamp
    ld a,l
    ld (spr_clock),a
    ; forget its old key
    ld h,high SPRATTR
    ld a,(hl)
    cp 0FFh
    jr z,.nf
    add a,high SPRMAP
    ld d,a
    ld h,high SPRTILE
    ld e,(hl)
    ld a,0FFh
    ld (de),a
.nf:
    ld h,high SPRTILE
    ld a,(cell_tile)
    ld (hl),a
    ld h,high SPRATTR
    ld a,(cell_pal)
    ld (hl),a
    ld a,l
    pop hl
    ld (hl),a
    push af
    ; make the pattern: VRAM 2000h + slot*32
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    ld de,VR_SPRPAT
    add hl,de
    call vram_wr
    ld a,(cell_tile)
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    ld de,CHR
    add hl,de
    ld c,1
    ld a,(cell_pal)
    bit 3,a                     ; vertical flip: rows 7..0
    jr z,.nv
    ld de,7
    add hl,de
    ld c,-1
.nv:push hl
    pop ix
    bit 2,a
    jr z,.nh
    ld a,1
    ld (tmp2),a
.nh:ld a,(cell_pal)
    and 03h
    call gen_pattern
    ld a,SRAM_ON                ; gen_pattern unmaps the cartridge RAM
    ld (0FFFCh),a
    pop af
    ret
