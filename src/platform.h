#ifndef PLATFORM_H
#define PLATFORM_H
#include <stdint.h>
typedef uint8_t u8; typedef int8_t s8; typedef uint16_t u16; typedef int16_t s16; typedef uint32_t u32;
extern volatile u16 vblank_counter;
extern volatile u8 pause_request;
extern u8 sat_y[64], sat_xp[128], sat_count;
#define UP 1
#define DOWN 2
#define LEFT 4
#define RIGHT 8
#define FIRE 16
#define BUTTON2 32
#define ROM_PAGE (*(volatile u8 *)0xffff)
#define ROM_PTR ((const u8 *)0x8000)
u8 joy_read(void);
void vdp_reg(u8 reg,u8 value);
void vdp_copy(u16 address,const void *src,u16 count) __sdcccall(0);
void hw_init(void);
void scene_load(u8 bank);
void display_on(void);
void sprites_begin(void);
void sprite(u8 x,s16 y,u8 pattern);
void meta(u8 cx,u8 cy,u8 pattern,u8 width,u8 height) __sdcccall(0);
void sprites_flush(void);
void sfx_tick(void);
void music_irq(void);
void music_play(u8 track);
void music_pause(u8 on);
extern u8 music_is_pal,music_track;
void sound_start(u8 id);
void sound_mute(void);
extern u8 music_enabled;
#endif
