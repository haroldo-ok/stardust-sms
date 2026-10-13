; Fast sequential VRAM/CRAM transfer, stack ABI (--sdcccall 0).
; void vdp_copy(uint16_t address, const void *src, uint16_t count)
; Address bit 15 selects CRAM, otherwise the VRAM write command is supplied.
; Addresses, lengths and source pointers are little-endian arguments.
.module vdp
.globl _vdp_copy
.area _CODE
_vdp_copy:
    push iy
    ld iy,#4
    add iy,sp
    di
    ld a,0(iy)
    out (0xbf),a
    ld a,1(iy)
    or #0x40
    out (0xbf),a
    ei
    ld l,2(iy)
    ld h,3(iy)
    ld e,4(iy)
    ld d,5(iy)
    ld c,#0xbe
    ld a,d
    or a
    jr z,partial
fullblock:
    ld b,#0
full_loop:
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    jp nz,full_loop
    dec d
    jr nz,fullblock
partial:
    ld b,e
    ld a,b
    or a
    jr z,finished
    and #15
    jr nz,short_loop
partial_loop:
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    outi
    jp nz,partial_loop
    jr finished
short_loop:
    outi
    jp nz,short_loop
finished:
    pop iy
    ret

; Fast metasprite compositor: five packed byte arguments, stack ABI.
; Keeps the actual SMS scanline behaviour, with rotating actor order in C.
; Main registers: HL=Y cursor, IY=X/pattern cursor, D=Y, E=pattern,
; B=columns, C=X. Alternate B=rows, C=remaining SAT capacity.
.globl _meta, _sat_y, _sat_xp, _sat_count
_meta:
    push ix
    push iy
    ld ix,#6
    add ix,sp
    ld a,(_sat_count)
    cp #63
    jp nc,meta_return
    neg
    add a,#63
    exx
    ld c,a
    exx
    ld a,4(ix)
    add a,#15
    srl a
    srl a
    srl a
    srl a
    exx
    ld b,a
    exx
    ld a,3(ix)
    srl a
    ld b,a
    ld a,0(ix)
    sub b
    ld c,a
    ld a,4(ix)
    srl a
    ld b,a
    ld a,1(ix)
    sub b
    ld d,a
    ld e,2(ix)
    ld a,3(ix)
    add a,#7
    srl a
    srl a
    srl a
    ld b,a
    push bc
    push de
    ld a,(_sat_count)
    ld l,a
    ld h,#0
    ld de,#_sat_y
    add hl,de
    push hl
    ld a,(_sat_count)
    add a,a
    ld l,a
    ld h,#0
    ld de,#_sat_xp
    add hl,de
    push hl
    pop iy
    pop hl
    pop de
    pop bc
meta_row:
    push bc
    ld a,d
    cp #168
    jr c,meta_cell
    cp #241
    jr nc,meta_cell
    ; Completely clipped row: advance patterns but allocate no SAT entries.
    ld a,b
    add a,a
    add a,e
    ld e,a
    jr meta_next_row
meta_cell:
    ld a,d
    dec a
    ld (hl),a
    inc hl
    ld 0(iy),c
    ld 1(iy),e
    inc iy
    inc iy
    ld a,c
    add a,#8
    ld c,a
    inc e
    inc e
    exx
    dec c
    exx
    jr z,meta_full
    djnz meta_cell
meta_next_row:
    pop bc
    ld a,d
    add a,#16
    ld d,a
    exx
    dec b
    exx
    jr nz,meta_row
    jr meta_finish
meta_full:
    pop bc
meta_finish:
    ld de,#_sat_y
    or a
    sbc hl,de
    ld a,l
    ld (_sat_count),a
meta_return:
    pop iy
    pop ix
    ret

; Encoded 32-column embossed font row. Pattern = ASCII + 96, palette 0.
; void encode_line(u8 *dst,const char *src,u8 priority), explicit stack ABI.
.globl _encode_line
_encode_line:
    push iy
    ld iy,#4
    add iy,sp
    ld e,0(iy)
    ld d,1(iy)
    ld l,2(iy)
    ld h,3(iy)
    ld c,#0
    ld a,4(iy)
    or a
    jr z,font_priority_done
    ld c,#0x10
font_priority_done:
    ld b,#32
font_loop:
    ld a,(hl)
    inc hl
    or a
    jr z,font_pad
    cp #32
    jr c,font_bad
    cp #96
    jr nc,font_bad
    add a,#96
    jr font_put
font_bad:
    ld a,#128
font_put:
    ld (de),a
    inc de
    ld a,c
    ld (de),a
    inc de
    djnz font_loop
    jr font_done
font_pad:
    ld a,#128
font_pad_loop:
    ld (de),a
    inc de
    ld a,c
    ld (de),a
    inc de
    ld a,#128
    djnz font_pad_loop
font_done:
    pop iy
    ret
