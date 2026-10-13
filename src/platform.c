/* Mode-4 VDP, PSG music and controller I/O for an actual Master System. */
#include "platform.h"
#include "art.h"
__sfr __at(0xbe) VDP_DATA;
__sfr __at(0xbf) VDP_CTRL;
__sfr __at(0xdc) JOY;
__sfr __at(0x7f) PSG;
__sfr __at(0x7e) VCOUNT;
volatile u16 vblank_counter;
volatile u8 pause_request;
u8 sat_y[64],sat_xp[128],sat_count;
u8 music_enabled=1;
static u8 sfx_id,sfx_time,sfx_prio;
static const u16 notes[16]={855,762,679,640,571,508,453,428,381,339,320,285,254,226,214,190};
/* SFX share PSG channel 2 (and the noise channel for explosions/hits) with the
   music. Main-line code owns the bits in sfx_mask; the music player only
   updates its shadow registers for those channels and restores them when the
   effect ends. Two-byte tone writes are made atomic so the line interrupt can
   never slip a latch byte between them. */
volatile u8 sfx_mask;
static void tone(u8 channel,u16 period){
    u8 lo=0x80|(channel<<5)|(period&15),hi=(period>>4)&63;
    __asm di __endasm;
    PSG=lo;PSG=hi;
    __asm ei __endasm;
}
static void volume(u8 channel,u8 v){PSG=0x90|(channel<<5)|(v&15);}
u8 joy_read(void){return (~JOY)&63;}
/* SDCC register ABI: first byte in A, second in L. A __critical function
   prologue uses LD A,I and would overwrite the register argument. */
void vdp_reg(u8 reg,u8 value) __naked {
    (void)reg;(void)value;
    __asm
        ld c,a
        di
        ld a,l
        out (0xbf),a
        ld a,c
        or #0x80
        out (0xbf),a
        ei
        ret
    __endasm;
}
/* PAL VDPs count 0..F2 then jump back to BA; NTSC count 0..DA then jump to D5. */
static u8 detect_pal(void){
    u8 v,prev=VCOUNT;u16 guard=0;
    while(--guard){
        v=VCOUNT;
        if(v<prev && prev!=0xff)return prev>=0xf0;
        prev=v;
    }
    return 0;
}
void display_on(void){vdp_reg(1,0x62);}
void hw_init(void){
    /* 315-5124 (SMS1) uses the nominally-unused low bits of R5/R6 as
       address masks. R5 bit0 must be 1 for SAT X/pattern reads, and R6
       bits0..1 must be 1 for sprite pattern bits6..7. Also valid on SMS2. */
    /* R0 bit4 enables the line interrupt; R10=100 fires it once per frame at
       raster line 100 (the next underflow would be line 201, which is never
       counted), well away from the VBlank transfer window. It drives music. */
    static const u8 regs[11]={0x14,0x22,0xff,0xff,0xff,0x7f,0x03,0x00,0x00,0x00,100};
    u8 i; for(i=0;i<11;i++)vdp_reg(i,regs[i]);
    sound_mute();
    music_is_pal=detect_pal();
    __asm ei __endasm;
}
void scene_load(u8 bank){
    vdp_reg(1,0x22);  /* display disabled; frame interrupt remains enabled */
    ROM_PAGE=bank;
    vdp_copy(0xc000,ROM_PTR,32);
    vdp_copy(0x0000,ROM_PTR+32,4096);
    vdp_copy(0x1000,ROM_PTR+BG_OFFSET,10240);
    vdp_copy(0x3800,ROM_PTR+MAP_OFFSET,1536);
    vdp_reg(8,0);vdp_reg(9,0);
    sprites_begin();sprites_flush();
    display_on();
}
void sprites_begin(void){sat_count=0;}
void sprite(u8 x,s16 y,u8 pattern){
    u8 n;
    if(sat_count>=63 || y<=-16 || y>=168)return;
    n=sat_count++;
    sat_y[n]=(u8)(y-1);sat_xp[n+n]=x;sat_xp[n+n+1]=pattern;
}
void sprites_flush(void){
    sat_y[sat_count]=0xd0;
    vdp_copy(0x3f00,sat_y,64);
    vdp_copy(0x3f80,sat_xp,128);
}
void sound_mute(void){PSG=0x9f;PSG=0xbf;PSG=0xdf;PSG=0xff;}
void sound_start(u8 id){
    u8 priority=(id==1?1:(id==2?2:3));
    if(sfx_time && priority<sfx_prio)return;
    sfx_id=id;sfx_prio=priority;sfx_time=(id==1?4:(id==2?16:22));
    sfx_mask=(id==2 || id==4)?0x0c:0x04;
}
/* Called once per logic update (sound effects keep their original pacing). */
void sfx_tick(void){
    if(!sfx_time)return;
    if(sfx_id==1){tone(2,90+(4-sfx_time)*90);volume(2,8+(4-sfx_time));}
    else if(sfx_id==2 || sfx_id==4){PSG=0xe7;volume(3,5+(16-(sfx_time>16?16:sfx_time))/2);tone(2,700-sfx_time*12);volume(2,10);}
    else if(sfx_id==3){tone(2,notes[(22-sfx_time)&15]);volume(2,5+(22-sfx_time)/3);}
    else {tone(2,280+((sfx_time&3)<<6));volume(2,7+(22-sfx_time)/4);}
    if(!--sfx_time){
        volume(2,15);if(sfx_mask&8)volume(3,15);
        sfx_prio=0;sfx_mask=0;   /* hand the channels back to the music */
    }
}

/* ---- Music: PSG register streams converted from the Amiga modules ----------
   The per-frame player is src/music.s, called from a line interrupt in the
   middle of the active display, so it keeps a steady 50 Hz tempo however slow
   a logic frame is and never delays the VBlank pattern/SAT transfers. NTSC
   skips every sixth interrupt. Streams live in banks MUSIC_FIRST_BANK.. and are
   paged into slot 2 only inside the interrupt; the main program's page is
   restored before it returns. Stream format: tools/convert_music.py. */
#define MUSIC_TABLE
#include "music.h"
u8 music_is_pal,music_track=255;
/* player state shared with music.s */
u8 m_hold,m_wait,m_bank,m_left,m_rbank,m_prev,m_restore,m_div,m_lbank;
const u8 *m_ptr,*m_rptr,*m_laddr;
u8 sh_regs[16];

void music_play(u8 track){
    u8 c;
    if(track==music_track || track>=MUSIC_TRACKS)return;
    __asm di __endasm;
    music_track=track;m_bank=music_bank[track];m_ptr=(const u8 *)music_addr[track];
    m_lbank=music_loop_bank[track];m_laddr=(const u8 *)music_loop_addr[track];
    m_wait=0;m_left=0;m_div=0;
    for(c=0;c<4;c++){
        sh_regs[c*4]=c==3?0xe4:0x80|(c<<5);sh_regs[c*4+1]=0;
        sh_regs[c*4+2]=0x9f|(c<<5);sh_regs[c*4+3]=1<<c;
    }
    __asm ei __endasm;
}
void music_pause(u8 on){
    __asm di __endasm;
    m_hold=on;if(!on)m_restore=0x0f;
    __asm ei __endasm;
}
