; ---------------------------------------------------------------------------
; Sega Master System memory map
;   0000-3FFF  ROM page 0: NES fixed bank image (data read by the game) + vectors
;   4000-7FFF  slot 1: translated code page; runtime copy at RT_BASE in every code page
;   8000-BFFF  slot 2: NES switchable bank (raw), or cartridge RAM when the runtime needs it
;   C000-DFFF  RAM (8KB)
; ---------------------------------------------------------------------------
RT_BASE     equ 6800h           ; runtime (same bytes in every code page)
FIRST_CODE_PAGE equ 9

; ---- main RAM
NESRAM      equ 0C000h          ; NES $0000-$07FF
NTSH        equ 0C800h          ; NES nametables 0/1 (vertical mirroring): tiles + attributes
BGMAP       equ 0D000h          ; [pal*256 + tile] -> BG pattern slot (FFh = none)
CELLSLOT    equ 0D400h          ; SMS name table cell (row*32+col) -> slot (FFh = none)
REFCNT      equ 0D800h          ; slot -> number of name table cells using it
SLOTTILE    equ 0D900h          ; slot -> tile
SLOTPAL     equ 0DA00h          ; slot -> palette (FFh = free)
DIRTYQ      equ 0DB00h          ; 128 x word: changed nametable cells (NTSH offsets)
SATSH       equ 0DC00h          ; sprite table shadow: 64 y (DC00), then 64 x/pattern pairs (DC40-DCBF)
COLMAP      equ 0DCC0h          ; SMS column -> NES column (0-63) shown, FFh = none
ROWMAP      equ 0DCE0h          ; NES row (0-29) -> SMS row (0-31)
VARS        equ 0DD00h
APU_SH      equ 0DE00h          ; NES APU register shadow $4000-$401F
APU_W       equ 0DE20h          ; write flags per register (APU_SH + 20h)
NESPAL      equ 0DE40h          ; NES palette RAM shadow (32)
CHRDIRTY    equ 0DE60h          ; 512-bit bitmap of changed CHR tiles (sprite tiles 0-255, then BG)
RTSTACK     equ 0DFE0h          ; runtime stack top (grows down to ~DF20h)
HSTACK      equ 0DF20h          ; private stack of $2007/$4016 handlers (down to ~DEC0h)

; ---- cartridge RAM (mapped at 8000h with mapper register FFFCh = 08h)
SRAM_ON     equ 08h
CHR         equ 8000h           ; NES CHR-RAM copy (sprites 8000-8FFF, background 9000-9FFF)
SPRMAP      equ 0A000h          ; [attr*256 + tile] -> sprite slot (FFh = none); attr = pal | hflip<<2 | vflip<<3
SPRTILE     equ 0B000h          ; sprite slot -> tile
SPRATTR     equ 0B100h          ; sprite slot -> attr (FFh = free)
SPRSTAMP    equ 0B200h          ; sprite slot -> frame stamp of last use
NSPRSLOT    equ 184             ; sprite patterns 256-439

; ---- VRAM
VR_NT       equ 3700h           ; 32x32 name table (224-line mode)
VR_SAT      equ 3F00h
VR_SPRPAT   equ 2000h

CROP        equ 8               ; NES lines hidden at the top (224 of 240 shown)
    IFNDEF MAXSKIP
MAXSKIP     equ 1
    ENDIF

; ---- variables
cur_zbank   equ VARS+00h
cur_nesbank equ VARS+01h
ppu_v       equ VARS+02h        ; word
ppu_inc     equ VARS+04h        ; word
ppu_w       equ VARS+06h
ppu_ctrl    equ VARS+07h
ppu_mask    equ VARS+08h
scroll_x    equ VARS+09h
scroll_y    equ VARS+0Ah
stat_tog    equ VARS+0Bh
oam_page    equ VARS+0Ch
pal_dirty   equ VARS+0Dh
dq_count    equ VARS+0Eh
full_redraw equ VARS+0Fh
joy_shift   equ VARS+10h
fc_bank     equ VARS+11h
fc_jp       equ VARS+12h        ; 3 bytes: JP target (far call trampoline)
frame_sp    equ VARS+15h        ; word
dsp_kb      equ VARS+17h
dsp_key     equ VARS+18h        ; word
dsp_mid     equ VARS+1Ah
dbg_trap    equ VARS+1Bh        ; 3 bytes
frame_cnt   equ VARS+1Eh        ; word
vbl_count   equ VARS+20h
vbl_last    equ VARS+21h
snd_last    equ VARS+22h
skipped     equ VARS+23h
pause_cnt   equ VARS+24h
tas_ptr     equ VARS+25h        ; word
gap         equ VARS+27h        ; NES row where the 2 spare SMS rows are inserted
bg_clock    equ VARS+28h
spr_clock   equ VARS+29h
stamp       equ VARS+2Ah
vdp_r1      equ VARS+2Bh
chr_dirty_n equ VARS+2Ch        ; number of dirty CHR tiles (0 = none)
tmp1        equ VARS+2Dh
tmp2        equ VARS+2Eh
tmpw        equ VARS+30h        ; word
spr_left    equ VARS+32h
reg8        equ VARS+33h
reg9        equ VARS+34h
cell_pal    equ VARS+35h
cell_tile   equ VARS+36h
cell_sms    equ VARS+37h        ; word: SMS cell index
nt_base     equ VARS+39h        ; word: NTSH address of the NES nametable of the cell
apu_en      equ VARS+40h        ; $4015
apu_len     equ VARS+41h        ; 4 length counters
apu_envv    equ VARS+45h        ; 3 envelope volumes
apu_envd    equ VARS+48h        ; 3 envelope dividers
apu_lin     equ VARS+4Bh
apu_linrl   equ VARS+4Ch
env_ctl     equ VARS+4Dh
psg_noise   equ VARS+4Eh        ; last noise control written
hsave       equ VARS+50h        ; word: caller SP of a handler on HSTACK
