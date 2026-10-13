; Standalone cartridge startup, Z80 IM-1 VBlank/line interrupt and console-pause NMI.
; This is original project code, not a Spectrum or Game Gear startup.
.module crt0
.globl _main, _vblank_counter, _pause_request, _music_irq
.area _HEADER (ABS)
.org 0x0000
    jp init
.org 0x0038
    jp irq
.org 0x0066
    push af
    ld a,#1
    ld (_pause_request),a
    pop af
    retn
.org 0x0100
init:
    di
    im 1
    ld sp,#0xdff0
    ld a,#0xab
    out (0x3e),a
    ld a,#0xff
    out (0x3f),a
    xor a
    ld (0xfffc),a
    ld (0xfffd),a
    inc a
    ld (0xfffe),a
    inc a
    ld (0xffff),a
    call gsinit
    call _main
stop:
    halt
    jr stop
irq:
    push af
    in a,(0xbf)
    bit 7,a
    jr z,line_irq
    push hl
    ld hl,(_vblank_counter)
    inc hl
    ld (_vblank_counter),hl
    pop hl
irq_done:
    pop af
    ei
    reti
; Mid-screen line interrupt (once per frame): advance the music stream.
line_irq:
    push bc
    push de
    push hl
    push ix
    push iy
    call _music_irq
    pop iy
    pop ix
    pop hl
    pop de
    pop bc
    jr irq_done
; Segment ordering. Code stays in the two fixed mapper pages below $8000.
.area _HOME
.area _CODE
.area _INITIALIZER
.area _GSINIT
.area _GSFINAL
.area _DATA
.area _INITIALIZED
.area _BSEG
.area _BSS
.area _HEAP
.area _GSINIT
gsinit:
    ld bc,#l__DATA
    ld a,b
    or c
    jr z,zero_done
    ld hl,#s__DATA
    ld (hl),#0
    dec bc
    ld a,b
    or c
    jr z,zero_done
    ld e,l
    ld d,h
    inc de
    ldir
zero_done:
    ld bc,#l__INITIALIZER
    ld a,b
    or c
    jr z,copy_done
    ld de,#s__INITIALIZED
    ld hl,#s__INITIALIZER
    ldir
copy_done:
.area _GSFINAL
    ret
