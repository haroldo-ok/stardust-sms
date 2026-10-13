; Music stream player, run from the mid-screen line interrupt (crt0.s).
; Plays the PSG register streams made by tools/convert_music.py from the
; Amiga StarDust modules. State and start/stop live in platform.c.
;
; Stream format
;   1cc1vvvv            volume latch, channel cc
;   1cc0llll 00hhhhhh   tone latch + data byte, channels 0-2
;   111001rr            noise control (channel 3)
;   0x00..0x3F          end of frame, then N idle frames
;   0x40                end of song: continue at the loop point
;   0x41 b lo hi n      play the n frames stored at bank b, address hi:lo,
;                       then resume after this command (never nested)
;
; Shadow registers: sh_regs[4*ch] = tone latch (noise control for ch 3),
; [4*ch+1] = tone data, [4*ch+2] = volume latch, [4*ch+3] = 1<<ch.
; Channels in the "busy" mask (sound effects, music off) are only shadowed and
; are rewritten from the shadow when they are handed back.
.module music
.globl _music_irq
.globl _music_track, _music_enabled, _music_is_pal, _sfx_mask
.globl _m_hold, _m_wait, _m_bank, _m_left, _m_rbank, _m_prev, _m_restore, _m_div
.globl _m_lbank, _m_ptr, _m_rptr, _m_laddr, _sh_regs
.area _CODE
_music_irq:
    ld a,(_m_hold)
    or a
    ret nz
    ld a,(_music_track)
    inc a
    ret z                   ; no track selected yet
    ld a,(_music_is_pal)
    or a
    jr nz,tempo_ok
    ld hl,#_m_div           ; NTSC: 60 interrupts/s, the music is 50 frames/s
    inc (hl)
    ld a,(hl)
    sub a,#6
    jr nz,tempo_ok
    ld (hl),a
    ret
tempo_ok:
    ld a,(_sfx_mask)
    ld e,a
    ld a,(_music_enabled)
    or a
    ld a,#0x0f
    jr z,mask_ok
    ld a,e
mask_ok:
    ld c,a                  ; C = channels the music must not write
    ld a,(_m_prev)
    ld d,a
    cpl
    and c
    ld b,a
    ld a,e
    cpl
    and b                   ; newly busy because the music was switched off
    call nz,quiet
    ld a,c
    cpl
    ld b,a
    and d                   ; handed back since the last frame
    ld hl,#_m_restore
    or (hl)
    ld (hl),#0
    and b
    call nz,restore
    ld a,c
    ld (_m_prev),a
    ld hl,#_m_wait
    ld a,(hl)
    or a
    jr z,decode
    dec (hl)
    ret
decode:
    ld a,(0xffff)           ; the main program's slot-2 page (RAM mirror)
    push af
    ld a,(_m_bank)
    ld (0xffff),a
    ld hl,(_m_ptr)
next:
    ld a,(hl)
    inc hl
    bit 6,h
    call nz,cross
    or a
    jp p,command
    ld b,a                  ; PSG latch byte
    rrca
    rrca
    rrca
    and #0x0c               ; 4 * channel
    ld e,a
    ld d,#0
    ld ix,#_sh_regs
    add ix,de
    bit 4,b
    jr z,not_volume
    ld 2(ix),b
write_b:
    ld a,3(ix)
    and c
    jr nz,next
    ld a,b
    out (0x7f),a
    jr next
not_volume:
    ld a,e
    cp #12
    jr nz,tone
    ld 0(ix),b              ; noise control
    jr write_b
tone:
    ld a,(hl)
    inc hl
    bit 6,h
    call nz,cross
    ld 0(ix),b
    ld 1(ix),a
    ld e,a
    ld a,3(ix)
    and c
    jr nz,next
    ld a,b
    out (0x7f),a
    ld a,e
    out (0x7f),a
    jr next
command:
    cp #0x40
    jr c,frame_end
    jr nz,subcall
    ld a,(_m_lbank)         ; end of song: jump to the loop point
    ld (_m_bank),a
    ld (0xffff),a
    ld hl,(_m_laddr)
    jr next
subcall:
    call rdb
    ld b,a
    call rdb
    ld e,a
    call rdb
    ld d,a
    call rdb
    ld (_m_left),a
    ld (_m_rptr),hl
    ld a,(_m_bank)
    ld (_m_rbank),a
    ld a,b
    ld (_m_bank),a
    ld (0xffff),a
    ex de,hl
    jp next
frame_end:
    ld (_m_wait),a
    ld a,(_m_left)
    or a
    jr z,done
    dec a
    ld (_m_left),a
    jr nz,done
    ld hl,(_m_rptr)         ; repeated section finished: resume after the call
    ld a,(_m_rbank)
    ld (_m_bank),a
done:
    ld (_m_ptr),hl
    pop af
    ld (0xffff),a
    ret
; HL reached $C000: continue at the start of the next bank. Preserves A.
cross:
    ld h,#0x80
    push af
    ld a,(_m_bank)
    inc a
    ld (_m_bank),a
    ld (0xffff),a
    pop af
    ret
rdb:
    ld a,(hl)
    inc hl
    bit 6,h
    ret z
    jr cross
; Silence the channels in A. Preserves C.
quiet:
    ld e,a
    ld a,#0x9f
    ld b,#4
quiet_loop:
    srl e
    jr nc,quiet_next
    out (0x7f),a
quiet_next:
    add a,#0x20
    djnz quiet_loop
    ret
; Rewrite the channels in A from the shadow registers. Preserves C.
restore:
    ld e,a
    ld ix,#_sh_regs
    ld b,#4
restore_loop:
    srl e
    jr nc,restore_next
    ld a,b
    cp #1                   ; B==1 is channel 3: one noise byte, no data byte
    ld a,0(ix)
    out (0x7f),a
    jr z,restore_vol
    ld a,1(ix)
    out (0x7f),a
restore_vol:
    ld a,2(ix)
    out (0x7f),a
restore_next:
    inc ix
    inc ix
    inc ix
    inc ix
    djnz restore_loop
    ret
