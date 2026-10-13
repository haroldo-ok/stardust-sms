/* STARDUST SMS -- an independent, prerendered-3D fan adaptation.
 * Z80 game logic. Four asteroid sectors per world, five distinct guardians,
 * hyperspace tunnels, gravity bonus missions, power-ups and campaign codes.
 * Build: SDCC Z80 ABI1 (explicit ABI0 assembly), fixed code + Sega art banks.
 */
#include "platform.h"
#include "art.h"
#include "music.h"

#define ACTORS 32
#define SHOTS 20
#define PLAYER_SHOTS 14
#define PLAY_H 168
#define Y_WRAP 2688
#define QX(x) ((u16)(x)<<4)
#define PX(e) ((u8)((e)->x>>4))
#define PY(e) ((u8)((e)->y>>4))
#define TITLE 0
#define MAP 1
#define ARENA 2
#define BOSS 3
#define TUNNEL 4
#define MISSION 5
#define CLEAR 6
#define GAMEOVER 7
#define ENDING 8
#define MANUAL 9
#define PASSWORD 10
#define ROCK 1
#define ENEMY_A 2
#define ENEMY_B 3
#define MINE 4
#define TOKEN 5
#define EXPLOSION 6
#define FIGHTER 7
#define BLASTER 0
#define BOUNCER 1
#define MISSILE 2
#define FLAMER 3

typedef struct {u16 x,y; s8 vx,vy; u8 kind,size,tier,hp,ttl,age;} Actor;
typedef struct {u16 x,y; s8 vx,vy; u8 life,owner,mode,damage;} Shot;
Actor actors[ACTORS]; Shot shots[SHOTS];
/* Globals intentionally have useful names in the linker map for emulator QA. */
u8 game_mode,world,sector,arena_mask,selected,scene_bank;
u8 health,shield,lives,gun,bombs,weapon,difficulty,practice;
u8 boss_hp,boss_max,boss_stage,boss_x,boss_y,boss_flash,boss_parts[4];
u8 rock_count,enemy_count,token_kind,token_clock;
u16 stage_time,stage_ticks,logic_frames;
u32 score,high_score;
u16 player_x,player_y;
s8 player_vx,player_vy;
u8 player_dir,invulnerable,death_time,shield_active,improved,reload,contact_wait;
u8 keys,pressed,previous,turn_clock,pause_active;
u8 hero_frame,flame_frame,token_frame,rock_stream,rock_frame;
u8 hud[3][64],hud_phase,hud_dirty;
u8 hit_colour,hit_palette,transfer_start,transfer_end;
u8 boss_part_x[4],boss_part_y[4],mission_fuel;
u16 rng_state,last_vblank;
u16 perf[8],done_perf[8];
u8 col_x[ACTORS],col_y[ACTORS],col_r[ACTORS],col_id[ACTORS],col_count;
u8 draw_id[ACTORS],draw_count,shot_id[SHOTS],shot_count;
__sfr __at(0x7e) VCOUNT;
static u16 stamp(void){u8 v=VCOUNT;return vblank_counter*262+(v<192?v+70:v-192);}
static u8 clear_boss,clear_wait,menu_return,practice_select;
u8 pass_digits[5],pass_position,pass_error;
static const char *message;
static u8 message_time;
char line[33];
static char code[6];
static const s8 dx16[16]={0,6,11,15,16,15,11,6,0,-6,-11,-15,-16,-15,-11,-6};
static const s8 dy16[16]={-16,-15,-11,-6,0,6,11,15,16,15,11,6,0,-6,-11,-15};
static const s8 acceleration[16]={0,2,3,4,4,4,3,2,0,-2,-3,-4,-4,-4,-3,-2};
static const s8 wave[64]={0,3,6,9,12,15,18,20,23,25,27,28,30,31,31,32,
32,32,31,31,30,28,27,25,23,20,18,15,12,9,6,3,
0,-3,-6,-9,-12,-15,-18,-20,-23,-25,-27,-28,-30,-31,-31,-32,
-32,-32,-31,-31,-30,-28,-27,-25,-23,-20,-18,-15,-12,-9,-6,-3};
static const u8 square[32]={0,1,4,9,16,25,36,49,64,81,100,121,144,169,196,225,
0,33,68,105,144,185,228,17,64,113,164,217,16,73,132,193};
static const u8 node_x[5]={46,106,171,202,109};
static const u8 node_y[5]={66,49,68,123,124};
static const u8 enemy_behaviour[5][2]={{0,1},{2,3},{4,5},{6,0},{5,3}};
static const u8 boss_health[5]={48,64,80,96,96};
static const char * const world_names[5]={"AURELIA","CRIMSON RIFT","EMERALD VOID","MORPH NEBULA","IRON CITADEL"};
static const char * const boss_names[5]={"GATE GUARDIAN","TAILED EYE","SPACE WORM","MORPH RUNNER","THE PROFESSOR"};
static const char * const weapon_names[4]={"BLASTER","BOUNCER","MISSILE","FLAMER"};
static const char alphabet[]="ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

static void start_title(void);
static void start_map(void);
static void start_arena(void);
static void start_boss(void);
static void start_tunnel(void);
static void start_mission(void);
static void start_gameover(void);
static void start_ending(void);
static void damage_player(u8 damage);
static void damage_rock(u8 index,u8 damage);
static void make_hud(void);

static u8 rnd(void){
    /* Galois LFSR, deterministic cartridge startup but input-sensitive seed. */
    rng_state=(rng_state>>1)^((rng_state&1)?0xb400:0);
    return (u8)(rng_state^(rng_state>>8));
}
static u8 absolute(s16 n){return (u8)(n<0?-n:n);}
static s8 sign(s16 n){return n<0?-1:(n>0?1:0);}
static u8 near(u8 x,u8 y,u8 tx,u8 ty,u8 radius){
    /* Wrapped x, bounded y: two 8-bit interval tests, no signed 16-bit abs
       calls in the hot projectile/actor collision loop. */
    u8 diameter=radius+radius;
    return (u8)(x-tx+radius)<diameter && (u8)(y-ty+radius)<diameter;
}
static u8 aim(u8 x,u8 y,u8 tx,u8 ty){
    s8 vx=(s8)(tx-x);s16 vy=(s16)ty-y;
    u8 ax=absolute(vx),ay=absolute(vy);
    if((u16)ay>(u16)ax*2)return vy<0?0:8;
    if((u16)ax>(u16)ay*2)return vx<0?12:4;
    if(vy<0)return vx<0?14:2;
    return vx<0?10:6;
}
static void blank_line(void) __naked {
    __asm
        ld hl,#_line
        ld b,#32
        ld a,#32
blank_fill_loop:
        ld (hl),a
        inc hl
        djnz blank_fill_loop
        ld (hl),#0
        ret
    __endasm;
}
static void insert(u8 pos,const char *text){while(*text && pos<32)line[pos++]=*text++;}
static void number2(u8 pos,u8 v){line[pos]=(v/10)%10+'0';line[pos+1]=v%10+'0';}
static void number3(u8 pos,u16 v){line[pos]=(v/100)%10+'0';line[pos+1]=(v/10)%10+'0';line[pos+2]=v%10+'0';}
static void score_digits(u8 pos,u32 n){
    static const u32 places[6]={100000UL,10000UL,1000UL,100UL,10UL,1UL};
    u8 i,d;u32 p;
    /* At most 54 subtractions; no expensive 32-bit division in the HUD. */
    for(i=0;i<6;i++){p=places[i];d=0;while(n>=p){n-=p;d++;}line[pos+i]='0'+d;}
}
void encode_line(u8 *dst,const char *text,u8 priority) __sdcccall(0);
static void text_line(u8 row,const char *text){
    u8 buf[64];encode_line(buf,text,row>=21);
    vdp_copy(0x3800+(u16)row*64,buf,64);
}
static void centred(u8 row,const char *text){
    const char *p=text;u8 len=0;while(*p && len<32){p++;len++;}
    blank_line();insert((32-len)>>1,text);text_line(row,line);
}
static void notify(const char *text){message=text;message_time=90;hud_dirty=1;}
static void add_score(u16 points){score+=points;if(score>999999UL)score=999999UL;if(score>high_score)high_score=score;hud_dirty=1;}
static void clear_objects(void){u8 i;draw_count=shot_count=col_count=0;for(i=0;i<ACTORS;i++)actors[i].kind=0;for(i=0;i<SHOTS;i++)shots[i].life=0;}
static u8 free_actor(void){
    u8 i;for(i=0;i<ACTORS;i++)if(!actors[i].kind)return i;
    for(i=0;i<ACTORS;i++)if(actors[i].kind==EXPLOSION || actors[i].kind==TOKEN)return i;
    return 255;
}
static u8 spawn(u8 kind,u8 x,u8 y,s8 vx,s8 vy,u8 size,u8 tier){
    u8 i=free_actor();Actor *a;
    if(i==255)return i;a=&actors[i];a->kind=kind;a->x=QX(x);a->y=QX(y);
    a->vx=vx;a->vy=vy;a->size=size;a->tier=tier;a->hp=2+world+sector/2;
    a->age=0;a->ttl=(kind==TOKEN?180:(kind==EXPLOSION?10:(kind==MINE?180:255)));
    return i;
}
static void explosion(u8 x,u8 y){spawn(EXPLOSION,x,y,0,0,1,0);}
static void reset_player(u8 x,u8 y){
    /* A tunnel/bonus exit can occur during the death animation. Resolve the
       pending respawn instead of cancelling it and entering with zero energy. */
    if(!health && lives){health=100;shield=60;}
    player_x=QX(x);player_y=QX(y);player_vx=player_vy=0;player_dir=0;
    invulnerable=75;death_time=0;reload=0;contact_wait=0;shield_active=0;
}
static void prepare_scene(u8 bank){
    scene_bank=bank;scene_load(bank);hero_frame=flame_frame=token_frame=255;
    rock_stream=rock_frame=0;hud_phase=0;hud_dirty=1;stage_ticks=0;
    message_time=0;token_clock=0;token_kind=0;pause_active=0;hit_palette=0x16;
    make_hud();
}
static u8 checksum(u32 p){return (u8)(p^(p>>5)^(p>>10)^(p>>15)^23)&31;}
static void password_make(void){
    u32 p=(u32)world|((u32)gun<<3)|((u32)lives<<5)|((u32)arena_mask<<9)|
          ((u32)(bombs>3?3:bombs)<<13)|((u32)weapon<<15)|((u32)difficulty<<17);
    u8 i=5;p=(p<<5)|checksum(p);
    while(i){i--;code[i]=alphabet[p&31];p>>=5;}code[5]=0;
}
static u8 password_apply(void){
    u8 i,w,l;u32 p=0,raw;
    for(i=0;i<5;i++)p=(p<<5)|pass_digits[i];raw=p>>5;
    if((p&31)!=checksum(raw) || (raw>>18))return 0;
    w=raw&7;l=(raw>>5)&15;if(w>4 || !l || l>9)return 0;
    world=w;gun=(raw>>3)&3;lives=l;arena_mask=(raw>>9)&15;bombs=(raw>>13)&3;
    weapon=(raw>>15)&3;difficulty=(raw>>17)&1;health=shield=100;practice=0;
    improved=0;score=0;selected=0;return 1;
}
static void start_title(void){
    game_mode=TITLE;clear_objects();prepare_scene(SC_TITLE);player_dir=0;
    centred(15,"SEGA MASTER SYSTEM");
    blank_line();insert(2,"HIGH SCORE ");score_digits(13,high_score);text_line(2,line);
    centred(22,difficulty?"RELAXED: 5 LIVES / LESS DAMAGE":"NORMAL: 3 LIVES / ARCADE DAMAGE");
    previous=keys;practice_select=0;
}
static void new_game(u8 practise){
    world=0;sector=0;selected=0;arena_mask=0;score=0;health=shield=100;
    lives=difficulty?5:3;gun=0;bombs=2;weapon=BLASTER;improved=0;practice=practise;
    if(practice){world=practice_select;gun=3;bombs=3;lives=5;weapon=MISSILE;start_boss();}
    else start_map();
}
static void start_map(void){
    game_mode=MAP;clear_objects();prepare_scene(SC_MAP);player_dir=8;
    blank_line();insert(2,"WAR PLAN W");line[12]='1'+world;insert(15,world_names[world]);text_line(0,line);
    centred(16,arena_mask==15?"GUARDIAN UNLOCKED - SELECT G":"FOUR SECTORS / ONE GUARDIAN");
    centred(18,"LEFT/RIGHT SELECT  1 LAUNCH");centred(20,"2 FLIGHT MANUAL");
    password_make();blank_line();insert(6,"PASSWORD: ");insert(16,code);text_line(22,line);
    blank_line();insert(6,"SECTORS: ");
    line[15]=(arena_mask&1)?'*':'1';line[17]=(arena_mask&2)?'*':'2';line[19]=(arena_mask&4)?'*':'3';line[21]=(arena_mask&8)?'*':'4';line[24]=(arena_mask==15)?'G':'-';text_line(2,line);
    previous=keys;
}
static void start_arena(void){
    u8 i,tier;game_mode=ARENA;sector=selected;clear_objects();prepare_scene(3+world);
    reset_player(128,94);stage_time=(150+20*world)*30;
    if(difficulty)stage_time+=1800;
    centred(0,world_names[world]);notify("CLEAR THE METEORS AND ALIENS");
    tier=world/2+sector/2;if(tier>3)tier=3;
    for(i=0;i<2+sector/2;i++)spawn(ROCK,24+rnd()%210,20+rnd()%128,(s8)(rnd()%25)-12,(s8)(rnd()%21)-10,2,tier);
    for(i=0;i<2+(world>2?2:world);i++)spawn((i&1)?ENEMY_B:ENEMY_A,24+rnd()%208,20+rnd()%110,(s8)(rnd()%21)-10,(s8)(rnd()%21)-10,1,0);
    /* Every sector offers a visible guaranteed gun token on entry. */
    spawn(TOKEN,128,69,0,0,1,0);token_kind=0;token_clock=0;
}
static void start_boss(void){
    u8 i;game_mode=BOSS;clear_objects();prepare_scene(12+world);reset_player(128,139);
    boss_hp=boss_max=boss_health[world];boss_stage=0;boss_flash=0;boss_x=128;boss_y=64;
    for(i=0;i<4;i++)boss_parts[i]=4;
    stage_time=180*30;centred(0,boss_names[world]);sound_start(5);
    notify(world==4?"EGG MACHINE - WATCH ITS CRUSH":"GUARDIAN APPROACHING");
}
static void start_tunnel(void){
    game_mode=TUNNEL;clear_objects();prepare_scene(SC_TUNNEL);reset_player(128,126);
    stage_time=24*30;health=health>70?health:70;shield=shield>60?shield:60;
    centred(0,"HYPERSPACE - DODGE THE DEBRIS");notify("DPAD MOVES / 1 FIRES / 2 BOMB");
}
static void start_mission(void){
    game_mode=MISSION;clear_objects();prepare_scene(SC_MISSION);reset_player(24,120);
    stage_time=40*30;mission_fuel=100;token_kind=7;
    centred(0,"SPECIAL MISSION - GRAVITY WELL");notify("COLLECT X / F REFUELS / EXIT NE");
    spawn(TOKEN,60,98,0,0,1,0);spawn(TOKEN,111,70,0,0,1,0);spawn(TOKEN,183,40,0,0,1,0);
}
static void start_gameover(void){
    game_mode=GAMEOVER;clear_objects();prepare_scene(SC_TITLE);centred(12,"GAME OVER");
    blank_line();insert(8,"SCORE ");score_digits(14,score);text_line(14,line);
    centred(19,"1 RETRY   2 TITLE");sound_start(5);
}
static void start_ending(void){
    game_mode=ENDING;clear_objects();prepare_scene(SC_END);player_dir=0;
    blank_line();insert(8,"SCORE ");score_digits(14,score);text_line(8,line);
    centred(11,practice?"GUARDIAN PRACTICE COMPLETE":"ALL FIVE WORLDS LIBERATED");
    centred(14,"ORIGINAL GAME: BLOODHOUSE 1993");centred(16,"INDEPENDENT SMS FAN REMAKE");sound_start(3);
}
static void show_manual(u8 back){
    menu_return=back;game_mode=MANUAL;clear_objects();prepare_scene(SC_MANUAL);
    centred(7,"UP THRUST   LEFT/RIGHT ROTATE");centred(9,"DOWN SHIELD    BUTTON 1 FIRE");
    centred(11,"BUTTON 2 SMART / MEGA BOMB");centred(13,"DOWN + 2 CHANGE WEAPON");
    centred(15,"G GUN  H ENERGY  S SHIELD  X LIFE");centred(16,"* SMART  B MEGA  E STEERING");
    centred(18,"P POINTS   F BONUS-MISSION FUEL");centred(20,"CONSOLE PAUSE: PAUSE / RESUME");
    centred(22,"1 OR 2 RETURN");centred(23,"DOWN: MUSIC ON / OFF");previous=keys;
}
static void password_show(void){
    u8 i;game_mode=PASSWORD;clear_objects();prepare_scene(SC_PASSWORD);
    for(i=0;i<5;i++)pass_digits[i]=0;pass_position=0;pass_error=0;
    centred(8,"ENTER THE FIVE WAR-PLAN SYMBOLS");centred(10,"UP/DOWN CHANGE  LEFT/RIGHT MOVE");
    centred(15,"1 CONTINUE   2 CANCEL");previous=keys;
}
static void finish_stage(u8 is_boss){
    u8 i;if(game_mode==CLEAR)return;game_mode=CLEAR;clear_boss=is_boss;clear_wait=90;
    for(i=0;i<SHOTS;i++)shots[i].life=0;
    if(is_boss){add_score(3000+world*1000);sound_start(2);explosion(boss_x,boss_y);}
    else{arena_mask|=1<<sector;add_score(500);sound_start(3);}
    notify(is_boss?"GUARDIAN DESTROYED - WARP READY":"SECTOR SECURED - COLLECT TOKENS");
}
static void damage_player(u8 damage){
    if(death_time || invulnerable)return;
    if(shield_active){if(shield>4)shield-=4;else shield=0;contact_wait=10;sound_start(5);return;}
    if(difficulty)damage=(damage+1)>>1;
    sound_start(4);invulnerable=45;
    if(health>damage)health-=damage;
    else{
        health=0;explosion((u8)(player_x>>4),(u8)(player_y>>4));death_time=75;
        if(lives)lives--;if(!lives){start_gameover();return;}
        if(gun && !practice)gun--;
    }hud_dirty=1;
}
static void damage_rock(u8 index,u8 damage){
    Actor *a=&actors[index];u8 size,x,y; s8 vx,vy;
    if(a->tier>=damage){a->tier-=damage;add_score(10);return;}
    size=a->size;x=PX(a);y=PY(a);vx=a->vx;vy=a->vy;a->kind=0;
    add_score((size+1)*40);explosion(x,y);sound_start(2);
    if(game_mode==ARENA && size){
        spawn(ROCK,x-5,y-4,vx-7,vy+6,size-1,0);spawn(ROCK,x+5,y+4,vx+7,vy-6,size-1,0);
    }else if(game_mode==ARENA && (rnd()&3)!=0)spawn(TOKEN,x,y,vx>>2,vy>>2,1,0);
}
static void collect_token(void){
    switch(token_kind){
    case 0:if(gun<3)gun++;else add_score(300);notify("GUN UPGRADED");break;
    case 1:health=100;notify("ENERGY RESTORED");break;
    case 2:shield=100;notify("SHIELD RECHARGED");break;
    case 3:if(bombs<9)bombs++;notify("SMART BOMB COLLECTED");break;
    case 4:add_score(500);notify("500 BONUS POINTS");break;
    case 5:improved=1;notify("FLIGHT CONTROLS IMPROVED");break;
    case 6:bombs=bombs>7?9:bombs+2;notify("MEGA BOMB - TWO CHARGES");break;
    case 7:if(lives<9)lives++;notify("EXTRA LIFE");break;
    case 8:mission_fuel=100;stage_time=stage_time>1200?1500:stage_time+300;notify("MISSION FUEL RESTORED");break;
    }add_score(50);sound_start(3);hud_dirty=1;
}
static void smart_bomb(void){
    u8 i,n=0,list[ACTORS];Actor *a;
    if(!bombs){notify("NO BOMBS - COLLECT * OR B");sound_start(5);return;}
    bombs--;sound_start(2);invulnerable=45;
    /* Snapshot active slots, so newborn rock fragments are not hit twice. */
    for(i=0;i<ACTORS;i++)if(actors[i].kind && actors[i].kind!=EXPLOSION && actors[i].kind!=TOKEN)list[n++]=i;
    for(i=0;i<n;i++){
        a=&actors[list[i]];if(a->kind==ROCK)damage_rock(list[i],4);
        else if(a->kind){explosion(PX(a),PY(a));a->kind=0;add_score(100);}
    }
    for(i=PLAYER_SHOTS;i<SHOTS;i++)shots[i].life=0;
    if(game_mode==BOSS && !(world==4 && boss_stage==1)){
        if(boss_hp>6)boss_hp-=6;else boss_hp=0;boss_flash=6;
    }
    notify("SMART BOMB DETONATED");
}
static void shot_make(u8 x,u8 y,u8 angle,u8 owner,u8 mode,u8 damage){
    u8 i,first=owner?PLAYER_SHOTS:0,last=owner?SHOTS:PLAYER_SHOTS;Shot *s;s16 vx,vy;
    for(i=first;i<last;i++)if(!shots[i].life)break;if(i==last)return;s=&shots[i];
    s->x=QX(x);s->y=QX(y);vx=dx16[angle]*(owner?2:6);vy=dy16[angle]*(owner?2:6);
    if(!owner){vx+=player_vx/2;vy+=player_vy/2;}
    /* E upgrades allow 4 px/tick ship speed; inherited velocity must not
       overflow an int8_t projectile and reverse its direction. */
    if(vx>120)vx=120;if(vx<-120)vx=-120;if(vy>120)vy=120;if(vy<-120)vy=-120;
    s->vx=vx;s->vy=vy;
    s->owner=owner;s->mode=mode;s->damage=damage;s->life=owner?75:(mode==FLAMER?10:32);
}
static void fire_player(void){
    u8 x=(u8)(player_x>>4),y=(u8)(player_y>>4),d=player_dir;
    shot_make(x+(dx16[d]>>1),y+(dy16[d]>>1),d,0,weapon,(weapon==MISSILE?3:(gun==3?2:1)));
    if((weapon==BLASTER && gun>=2) || weapon==FLAMER){
        shot_make(x,y,(d+15)&15,0,weapon,gun==3?2:1);shot_make(x,y,(d+1)&15,0,weapon,gun==3?2:1);
    }
    reload=(weapon==MISSILE?7:(weapon==FLAMER?3:(gun==0?6:(gun==1?4:5))));
    sound_start(1);
}
static void player_tick(void){
    s16 yy;u8 x,y; s8 limit=improved?64:48;
    if(invulnerable)invulnerable--;if(contact_wait)contact_wait--;
    if(death_time){
        death_time--;shield_active=0;
        if(!death_time){health=100;shield=60;reset_player(128,128);hud_dirty=1;}
        return;
    }
    shield_active=(keys&DOWN) && shield;
    if(game_mode==TUNNEL){
        player_dir=0;player_vx=(keys&LEFT)?-40:((keys&RIGHT)?40:0);
        player_vy=(keys&UP)?-40:((keys&DOWN)?40:0);shield_active=0;
    }else{
        turn_clock++;if(turn_clock>=(improved?1:2)){
            turn_clock=0;if(keys&LEFT)player_dir=(player_dir+15)&15;if(keys&RIGHT)player_dir=(player_dir+1)&15;
        }
        if((keys&UP) && (game_mode!=MISSION || mission_fuel)){
            player_vx+=acceleration[player_dir]*(improved?2:1);player_vy+=acceleration[(player_dir+12)&15]*(improved?2:1);
            if(game_mode==MISSION && !(stage_ticks&1) && mission_fuel)mission_fuel--;
        }else if(!(stage_ticks&3)){player_vx-=sign(player_vx);player_vy-=sign(player_vy);}
        if(game_mode==MISSION){if(!(stage_ticks&1))player_vy+=2;}
        if(player_vx>limit)player_vx=limit;if(player_vx<-(s8)limit)player_vx=-(s8)limit;
        if(player_vy>limit)player_vy=limit;if(player_vy<-(s8)limit)player_vy=-(s8)limit;
    }
    player_x=(player_x+player_vx)&4095;yy=(s16)player_y+player_vy;
    if(game_mode==TUNNEL || game_mode==MISSION){
        if(player_x<QX(12))player_x=QX(12);if(player_x>QX(243))player_x=QX(243);
        if(yy<QX(12)){yy=QX(12);player_vy=0;}
        if(yy>QX(153)){yy=QX(153);player_vy=0;if(game_mode==MISSION)damage_player(10);}
    }else{if(yy<0)yy+=Y_WRAP;if(yy>=Y_WRAP)yy-=Y_WRAP;}
    player_y=yy;
    if(shield_active){if(!(stage_ticks&1) && shield)shield--;}
    else if(shield<100 && !(stage_ticks&7))shield++;
    if(difficulty && health<100 && !(stage_ticks&63))health++;
    if(reload)reload--;if((keys&FIRE) && !reload)fire_player();
    if(pressed&BUTTON2){
        if(keys&DOWN){weapon=(weapon+1)&3;notify(weapon_names[weapon]);sound_start(3);}
        else smart_bomb();
    }
    if(game_mode==MISSION && (keys&FIRE)){
        x=(u8)(player_x>>4);y=(u8)(player_y>>4);
        if(near(x,y,235,26,19)){add_score(mission_fuel*10);start_map();}
    }
}
static void move_actor(Actor *a){
    s16 yy;a->x=(a->x+a->vx)&4095;yy=(s16)a->y+a->vy;
    if(yy<0)yy+=Y_WRAP;if(yy>=Y_WRAP)yy-=Y_WRAP;a->y=yy;
}
static void enemy_tick(Actor *a,u8 index){
    u8 bh=(a->kind==FIGHTER)?0:enemy_behaviour[world][a->kind==ENEMY_B];
    u8 x=PX(a),y=PY(a),tx=(u8)(player_x>>4),ty=(u8)(player_y>>4),dir;
    s8 ax=sign((s8)(tx-x)),ay=sign((s16)ty-y);
    if(bh==0 || bh==2 || bh==6){
        if(!((stage_ticks+index)&3)){
            a->vx+=ax*(bh==6?3:2);a->vy+=ay*(bh==6?3:2);
            if(a->vx>32)a->vx=32;if(a->vx<-32)a->vx=-32;
            if(a->vy>32)a->vy=32;if(a->vy<-32)a->vy=-32;
        }
    }else if(bh==1){a->vx=18;a->vy=wave[(stage_ticks+index*9)&63]>>1;}
    else if(bh==4){if(x<12 || x>244)a->vx=-a->vx;if(y<12 || y>156)a->vy=-a->vy;}
    else if(bh==5){a->vx=wave[(stage_ticks+index*7)&63]>>1;a->vy=6;}
    else if(bh==3 && !((stage_ticks+index*11)&63))spawn(MINE,x,y,0,0,0,0);
    if(!((stage_ticks+index*13)&(world>=3?31:63))){
        dir=aim(x,y,tx,ty);shot_make(x,y,dir,1,BLASTER,1);
    }
    move_actor(a);a->age++;
}
static void actor_tick(void){
    u8 i,x,y,px=(u8)(player_x>>4),py=(u8)(player_y>>4),r;Actor *a;
    rock_count=enemy_count=0;col_count=draw_count=0;
    for(i=0;i<ACTORS;i++){
        a=&actors[i];if(!a->kind)continue;draw_id[draw_count++]=i;
        if(a->kind==EXPLOSION){if(!--a->ttl)a->kind=0;continue;}
        if(a->kind==TOKEN){
            move_actor(a);if(!--a->ttl){a->kind=0;continue;}
            if(!death_time && near(PX(a),PY(a),px,py,13)){a->kind=0;collect_token();}
            continue;
        }
        if(a->kind==ROCK){
            rock_count++;move_actor(a);
            if(game_mode==TUNNEL){
                a->age++;if(a->age>42)a->size=2;else if(a->age>22)a->size=1;
                if(a->age>65){a->kind=0;continue;}
                if(!(a->age&7)){a->vx+=sign(a->vx)*2;a->vy+=sign(a->vy)*2;}
            }
        }else if(a->kind==MINE){
            if(game_mode==TUNNEL){move_actor(a);a->age++;if(a->age>65){a->kind=0;continue;}}
            else if(!--a->ttl){explosion(PX(a),PY(a));a->kind=0;continue;}
        }else{
            if(!(world==4 && a->kind==ENEMY_A))enemy_count++;
            enemy_tick(a,i);
        }
        x=PX(a);y=PY(a);r=(a->kind==ROCK?(a->size==2?14:(a->size==1?10:7)):11);
        if(game_mode!=CLEAR && !death_time && !contact_wait && near(x,y,px,py,r)){
            if(shield_active){
                contact_wait=12;if(shield>4)shield-=4;else shield=0;
                if(a->kind==ROCK)damage_rock(i,2);
                else if(!(world==4 && a->kind==ENEMY_A)){a->kind=0;explosion(x,y);add_score(100);}
                sound_start(5);
            }else damage_player(a->kind==MINE?24:16);
        }
        if(game_mode==GAMEOVER)return;
        if(a->kind==ROCK || a->kind==ENEMY_A || a->kind==ENEMY_B || a->kind==FIGHTER){
            col_x[col_count]=PX(a);col_y[col_count]=PY(a);
            col_r[col_count]=(a->kind==ROCK?(a->size==2?12:(a->size==1?8:5)):8);
            col_id[col_count++]=i;
        }
    }
}
static void boss_tick(void){
    u8 phase=(u8)(stage_ticks>>1)&63,i,dir;
    if(boss_flash)boss_flash--;
    if(world==0){
        boss_x=128+(wave[phase]>>1);boss_y=65;boss_stage=(stage_ticks%120)>=60;
        if(!(stage_ticks&15)){
            dir=aim(boss_x,boss_y,(u8)(player_x>>4),(u8)(player_y>>4));
            shot_make(boss_x-22,boss_y,dir,1,BLASTER,1);shot_make(boss_x+22,boss_y,(dir+1)&15,1,BLASTER,1);
        }
    }else if(world==1){
        boss_x=128+wave[phase]*2;boss_y=75+wave[(phase+16)&63];boss_stage=1;
        for(i=0;i<4;i++){
            boss_part_x[i]=boss_x+wave[(phase+10*i)&63];boss_part_y[i]=boss_y+20+i*13;
            if(boss_part_y[i]>155)boss_part_y[i]=155;
            if(boss_parts[i])boss_stage=0;
        }
        if(!(stage_ticks&31))shot_make(boss_x,boss_y,aim(boss_x,boss_y,(u8)(player_x>>4),(u8)(player_y>>4)),1,MISSILE,1);
        if(boss_stage && !(stage_ticks&255)){for(i=0;i<4;i++)if(!boss_parts[i]){boss_parts[i]=2;break;}}
    }else if(world==2){
        boss_x=128+wave[phase]*3;boss_y=73+wave[(phase+16)&63];boss_stage=(phase<16 || phase>47)?4:12;
        for(i=0;i<4;i++){
            boss_part_x[i]=128+wave[(phase+64-4*(i+1))&63]*3;
            boss_part_y[i]=73+wave[(phase+16+64-4*(i+1))&63];
        }
        if(!(stage_ticks&23))shot_make(boss_x,boss_y,aim(boss_x,boss_y,(u8)(player_x>>4),(u8)(player_y>>4)),1,BLASTER,1);
    }else if(world==3){
        boss_stage=boss_hp>64?0:(boss_hp>32?1:2);
        boss_x=128+wave[phase]*2;boss_y=70+wave[(phase+16)&63];
        if(!boss_stage && !(stage_ticks&15)){
            shot_make(boss_x,boss_y,aim(boss_x,boss_y,(u8)(player_x>>4),(u8)(player_y>>4)),1,BLASTER,1);
        }else if(boss_stage==1 && !(stage_ticks&15)){
            for(i=0;i<4;i++)shot_make(boss_x,boss_y,(phase+i*4)&15,1,BLASTER,1);
        }else if(boss_stage==2 && !(stage_ticks&15)){
            dir=aim(boss_x,boss_y,(u8)(player_x>>4),(u8)(player_y>>4));shot_make(boss_x,boss_y,dir,1,MISSILE,1);
        }
    }else{
        if(!boss_stage){
            boss_x=128+wave[phase]*2;boss_y=65+((stage_ticks%120)>80?wave[(u8)stage_ticks&63]*2:0);
            if(boss_y<30 || boss_y>138)boss_y=65;
            if(!(stage_ticks&15)){
                dir=aim(boss_x,boss_y,(u8)(player_x>>4),(u8)(player_y>>4));
                shot_make(boss_x,boss_y+20,dir,1,(stage_ticks&32)?MISSILE:BLASTER,1);
            }
        }else{
            boss_x=128+wave[phase]*2;boss_y=(stage_ticks&64)?145:23;
            if(!(stage_ticks&7)){
                dir=aim(boss_x,boss_y,(u8)(player_x>>4),(u8)(player_y>>4));
                shot_make(boss_x,boss_y,dir,1,BLASTER,1);
            }
            if(shield_active && !contact_wait && near(boss_x,boss_y,(u8)(player_x>>4),(u8)(player_y>>4),23)){
                boss_hp=boss_hp>6?boss_hp-6:0;contact_wait=18;boss_flash=5;
                if(shield>8)shield-=8;else shield=0;add_score(200);sound_start(4);
            }
            if(!(stage_ticks&127))spawn(TOKEN,64+(rnd()&127),80,0,0,1,0);
        }
    }
    if(near(boss_x,boss_y,(u8)(player_x>>4),(u8)(player_y>>4),world==4&&!boss_stage?26:20))damage_player(24);
    if(!boss_hp && game_mode==BOSS){
        if(world==4 && !boss_stage){boss_stage=1;boss_hp=boss_max=36;notify("PROFESSOR: SHIELD RAM AT EDGES");sound_start(2);}
        else finish_stage(1);
    }
}
static u8 boss_hit(Shot *s){
    u8 x=(u8)(s->x>>4),y=(u8)(s->y>>4),i,damage=s->damage;
    if(world==1){
        for(i=0;i<4;i++)if(boss_parts[i] && near(x,y,boss_part_x[i],boss_part_y[i],11)){
            boss_parts[i]=boss_parts[i]>damage?boss_parts[i]-damage:0;add_score(30);explosion(x,y);return 1;
        }
    }
    if(world==2){
        for(i=0;i<4;i++)if(near(x,y,boss_part_x[i],boss_part_y[i],13)){
            if(boss_hp>damage)boss_hp-=damage;else boss_hp=0;boss_flash=2;return 1;
        }
    }
    if(!near(x,y,boss_x,boss_y,world==4&&!boss_stage?23:19))return 0;
    if((world==0 && !boss_stage) || (world==1 && !boss_stage) || (world==4 && boss_stage==1)){
        sound_start(5);return 1;
    }
    if(boss_hp>damage)boss_hp-=damage;else boss_hp=0;boss_flash=2;add_score(20);return 1;
}
static void shot_tick(void){
    u8 i,j,x,y,r,target;Shot *s;Actor *a;s16 yy;
    shot_count=0;
    for(i=0;i<SHOTS;i++){
        s=&shots[i];if(!s->life)continue;s->life--;if(!s->life)continue;
        if(s->mode==MISSILE && !(stage_ticks&3)){
            target=255;x=(u8)(s->x>>4);y=(u8)(s->y>>4);
            if(s->owner)target=aim(x,y,(u8)(player_x>>4),(u8)(player_y>>4));
            else if(game_mode==BOSS)target=aim(x,y,boss_x,boss_y);
            else for(j=0;j<ACTORS;j++)if(actors[j].kind==ROCK || actors[j].kind==ENEMY_A || actors[j].kind==ENEMY_B){target=aim(x,y,PX(&actors[j]),PY(&actors[j]));break;}
            if(target!=255){s->vx=(s->vx+dx16[target]*4)>>1;s->vy=(s->vy+dy16[target]*4)>>1;}
        }
        if(s->mode==BOUNCER){
            if(s->x<QX(5) || s->x>QX(251))s->vx=-s->vx;
            if(s->y<QX(5) || s->y>QX(162))s->vy=-s->vy;
        }
        s->x=(s->x+s->vx)&4095;yy=(s16)s->y+s->vy;
        if(yy<0)yy+=Y_WRAP;if(yy>=Y_WRAP)yy-=Y_WRAP;s->y=yy;
        x=(u8)(s->x>>4);y=(u8)(s->y>>4);
        if(s->owner){
            if(!death_time && near(x,y,(u8)(player_x>>4),(u8)(player_y>>4),7)){s->life=0;damage_player(12);}
        }else{
            for(j=0;j<col_count;j++){
                r=col_r[j];
                if((u8)(x-col_x[j]+r)<(u8)(r+r) && (u8)(y-col_y[j]+r)<(u8)(r+r)){
                    a=&actors[col_id[j]];
                    if(a->kind==ROCK || a->kind==ENEMY_A || a->kind==ENEMY_B || a->kind==FIGHTER){
                        s->life=0;
                        if(a->kind==ROCK)damage_rock(col_id[j],s->damage);
                        else if(!(world==4 && a->kind==ENEMY_A)){
                            if(a->hp>s->damage)a->hp-=s->damage;
                            else{u8 xx=PX(a),yy2=PY(a);a->kind=0;explosion(xx,yy2);add_score(150);sound_start(2);if((rnd()&1))spawn(TOKEN,xx,yy2,0,0,1,0);}
                        }
                        break;
                    }
                }
            }
            if(s->life && game_mode==BOSS && boss_hit(s))s->life=0;
        }
        if(game_mode==GAMEOVER)return;
        if(s->life)shot_id[shot_count++]=i;
    }
}
static void gameplay_tick(void){
    u8 x,y,i;stage_ticks++;
    if(message_time){message_time--;if(!message_time)hud_dirty=1;}
    if(boss_flash && game_mode!=BOSS)boss_flash--;
    if(++token_clock>=60){token_clock=0;if(game_mode==MISSION)token_kind=token_kind==7?8:7;else token_kind=(token_kind+1)&7;}
    perf[0]=stamp();player_tick();perf[1]=stamp();if(game_mode==GAMEOVER || game_mode==MAP)return;
    actor_tick();perf[2]=stamp();if(game_mode==GAMEOVER)return;
    shot_tick();perf[3]=stamp();if(game_mode==GAMEOVER)return;
    if(game_mode==BOSS){boss_tick();if(game_mode!=BOSS)return;}
    if(game_mode==ARENA){
        if(stage_time){stage_time--;if(!stage_time){notify("ALIEN MOTHERSHIP - FIGHTER HORDE");sound_start(5);}}
        else if(!(stage_ticks&63))for(i=0;i<3;i++)spawn(FIGHTER,rnd(),20+(rnd()%120),(s8)(rnd()%17)-8,8,1,0);
        if(!rock_count && !enemy_count && stage_ticks>20)finish_stage(0);
    }else if(game_mode==TUNNEL){
        if(!(stage_ticks&7)){
            x=108+(rnd()%41);y=64+(rnd()%41);
            spawn((rnd()&7)==0?MINE:ROCK,x,y,sign((s16)x-128)*(6+(rnd()&7)),sign((s16)y-84)*(6+(rnd()&7)),0,rnd()&1);
        }
        if(!(stage_ticks&127))spawn(TOKEN,32+(rnd()%192),30+rnd()%100,0,6,1,0);
        if(stage_time)stage_time--;else if(world==2 || world==4)start_mission();else start_map();
    }else if(game_mode==MISSION){
        if(!(stage_ticks&63))spawn(TOKEN,35+(rnd()%180),20+(rnd()%108),0,0,1,0);
        if(stage_time)stage_time--;else{notify("MISSION COMPLETE");start_map();}
    }
    if(game_mode==CLEAR){
        if(clear_wait)clear_wait--;
        if(!clear_wait || ((pressed&FIRE) && clear_wait<60)){
            if(clear_boss){
                health=health>70?100:health+30;shield=100;
                if(practice){world++;if(world>=5)start_ending();else start_boss();}
                else {world++;arena_mask=0;selected=0;if(world>=5)start_ending();else start_tunnel();}
            }else {selected=(sector+1)%4;start_map();}
        }
    }
}
static void bar(u8 *dst,u8 col,u8 value,u8 max,u8 base,u8 cells){
    u16 filled=(u16)value*cells*8/max;u8 i,n;
    for(i=0;i<cells;i++){n=filled>=8?8:(u8)filled;filled=filled>=8?filled-8:0;dst[(col+i)*2]=base+n;dst[(col+i)*2+1]=0x10;}
}
static void make_hud(void){
    blank_line();insert(0,"SCORE ");score_digits(6,score);insert(14,"W");line[15]='1'+world;line[16]='-';line[17]='1'+sector;
    insert(21,"LIFE ");line[26]='0'+lives;encode_line(hud[0],line,1);
    blank_line();line[0]='H';line[10]='S';line[21]='B';line[22]='0'+bombs;line[25]='G';line[26]='0'+gun;
    encode_line(hud[1],line,1);bar(hud[1],1,health,100,HP_BAR,7);bar(hud[1],11,shield,100,SH_BAR,7);
    blank_line();line[0]='T';number3(1,stage_time/30);insert(6,weapon_names[weapon]);insert(17,"ROCK ");number2(22,rock_count);insert(26,"ALIEN");line[31]=enemy_count>9?'+':'0'+enemy_count;
    if(game_mode==BOSS){
        blank_line();insert(0,boss_names[world]);encode_line(hud[0],line,1);bar(hud[0],24,boss_hp,boss_max?boss_max:1,BOSS_BAR,7);
        blank_line();
        if(world==0)insert(0,boss_stage?"SHUTTERS OPEN - FIRE AT CORE":"WAIT FOR THE SHUTTERS TO OPEN");
        if(world==1)insert(0,boss_stage?"EYE EXPOSED - SHOOT ITS CORE":"SHOOT THE REGENERATING TAIL");
        if(world==2)insert(0,"SHOOT FROM BEHIND / HIT THE TAIL");
        if(world==3)insert(0,boss_stage==0?"BLADES: KEEP MOVING":(boss_stage==1?"PLATE: AVOID ITS BURSTS":"BALL: DODGE HOMING MISSILES"));
        if(world==4)insert(0,boss_stage?"IMMUNE: SHIELD RAM TOP / BOTTOM":"EGG MACHINE - AVOID THE CRUSH");
    }
    if(game_mode==TUNNEL){blank_line();line[0]='T';number3(1,stage_time/30);insert(6,"HYPERSPACE - KEEP MOVING");}
    if(game_mode==MISSION){blank_line();insert(0,"FUEL ");number3(5,mission_fuel);insert(10,"EXIT NE + 1  T");number3(24,stage_time/30);}
    if(message_time){blank_line();insert(0,message);}
    if(pause_active){blank_line();insert(7,"PAUSED - PRESS PAUSE");}
    encode_line(hud[2],line,1);hud_dirty=0;
}
static void draw_boss(void){
    u8 f=(stage_ticks>>3)&1,i;
    if(world==0){
        meta(boss_x,boss_y-25,B1_HOUSING_PAT,32,16);meta(boss_x,boss_y+25,B1_HOUSING_PAT,32,16);
        meta(boss_x-29,boss_y,B1_PILLAR_PAT,8,32);meta(boss_x+29,boss_y,B1_PILLAR_PAT,8,32);
        meta(boss_x-(boss_stage?23:8),boss_y,B1_DOOR_PAT,16,32);meta(boss_x+(boss_stage?23:8),boss_y,B1_DOOR_PAT,16,32);
        meta(boss_x,boss_y,B1_CORE_PAT+((stage_ticks>>3)&3)*4,16,16);
        meta(boss_x-24,boss_y-25,B1_TURRET_PAT,16,16);meta(boss_x+24,boss_y+25,B1_TURRET_PAT,16,16);
    }else if(world==1){
        meta(boss_x,boss_y,B2_EYE_PAT+((stage_ticks>>4)&3)*16,32,32);
        for(i=0;i<4;i++)if(boss_parts[i])meta(boss_part_x[i],boss_part_y[i],B2_ARM_PAT+((stage_ticks+i*8)>>3&3)*4,16,16);
    }else if(world==2){
        meta(boss_x,boss_y,B3_HEAD_PAT+f*16,32,32);
        /* Reverse ordering every other frame distributes SMS scanline overflow. */
        for(i=0;i<4;i++){
            u8 n=f?i:3-i;
            meta(boss_part_x[n],boss_part_y[n],(n==3?B3_TAIL_PAT:B3_SEG_PAT)+f*12,24,24);
        }
    }else if(world==3){
        meta(boss_x,boss_y,boss_stage==0?B4_BLADES_PAT+f*16:(boss_stage==1?B4_PLATE_PAT:B4_BALL_PAT+f*16),32,32);
    }else{
        if(!boss_stage){meta(boss_x,boss_y,B5_EGG_PAT+f*24,32,48);meta(boss_x,boss_y+10,B5_HATCH_PAT,16,16);}
        else meta(boss_x,boss_y,B5_PROF_PAT+f*16,32,32);
    }
}
static void draw_game(void){
    u8 i,n,pat,cursor,x=(u8)(player_x>>4),y=(u8)(player_y>>4);Actor *a;Shot *s;
    sprites_begin();
    if(game_mode==MAP){
        meta(node_x[selected],node_y[selected]-23,SPR_PLAYER,16,16);
        if(stage_ticks&8)meta(node_x[selected],node_y[selected],SPR_SHIELD,16,16);
        return;
    }
    if(game_mode==TITLE || game_mode==ENDING || game_mode==GAMEOVER){
        meta(215+wave[(stage_ticks>>1)&63]/2,118+wave[(stage_ticks>>1)+16&63]/2,SPR_PLAYER,16,16);return;
    }
    if(game_mode==PASSWORD){meta(92+pass_position*16,119,SPR_PLAYER,16,16);return;}
    if(game_mode==MANUAL)return;
    if(!death_time && (!(invulnerable&2) || shield_active)){
        meta(x,y,SPR_PLAYER,16,16);
        if(shield_active)meta(x,y,SPR_SHIELD,16,16);
        else if((keys&UP) && game_mode!=TUNNEL)meta(x-dx16[player_dir]*10/16,y-dy16[player_dir]*10/16,SPR_FLAME,8,16);
    }
    if(game_mode==BOSS)draw_boss();
    for(i=0;i<shot_count;i++){
        s=&shots[shot_id[i]];if(s->life)meta((u8)(s->x>>4),(u8)(s->y>>4),s->owner?SPR_ORB:SPR_SHOT,8,8);
    }
    cursor=draw_count?(u8)stage_ticks%draw_count:0;
    for(i=0;i<draw_count;i++){
        n=draw_id[cursor];if(++cursor>=draw_count)cursor=0;
        a=&actors[n];if(!a->kind)continue;
        x=PX(a);y=PY(a);
        if(a->kind==ROCK){
            pat=SPR_ROCK+a->tier*18+(a->size==2?6:(a->size==1?2:0));
            meta(x,y,pat,a->size==2?24:(a->size==1?16:8),a->size==2?24:(a->size==1?16:8));
        }else if(a->kind==TOKEN)meta(x,y,SPR_TOKEN,16,16);
        else if(a->kind==EXPLOSION)meta(x,y,SPR_EXPL+((10-a->ttl)>>1)*4,16,16);
        else if(a->kind==MINE)meta(x,y,SPR_MINE,8,16);
        else meta(x,y,(a->kind==ENEMY_B?SPR_ENEMY_B:SPR_ENEMY_A)+((stage_ticks>>3)&1)*4,16,16);
    }
    if(game_mode==MISSION)meta(235,26,SPR_SHIELD,16,16);
}
static void animation_flush(void){
    u16 off;u8 ci,cell,fl;
    ROM_PAGE=ANIM_BANK;
    if(hero_frame!=player_dir){vdp_copy(SPR_PLAYER*32,ROM_PTR+ANIM_PLAYER+(u16)player_dir*128,128);hero_frame=player_dir;}
    else if(token_frame!=token_kind){vdp_copy(SPR_TOKEN*32,ROM_PTR+ANIM_TOKENS+(u16)token_kind*128,128);token_frame=token_kind;}
    else if((keys&UP) && game_mode>=ARENA && game_mode<=CLEAR){
        fl=(player_dir>>1)&7;if(flame_frame!=fl){vdp_copy(SPR_FLAME*32,ROM_PTR+ANIM_FLAME+(u16)fl*64,64);flame_frame=fl;}
    }
    if(game_mode==BOSS){
        hit_colour=boss_flash?0x3f:0x16;
        if(hit_colour!=hit_palette){vdp_copy(0xc01d,&hit_colour,1);hit_palette=hit_colour;}
    }
    if(game_mode==ARENA || game_mode==TUNNEL){
        ci=rock_stream/9;cell=rock_stream%9;
        off=ANIM_ROCKS_GREY+(u16)ci*2304+(u16)rock_frame*576+(u16)cell*64;
        vdp_copy((SPR_ROCK+ci*18+cell*2)*32,ROM_PTR+off,64);
        if(++rock_stream>=36){rock_stream=0;rock_frame=(rock_frame+1)&3;}
    }
}
static void title_tick(void){
    stage_ticks++;player_dir=(stage_ticks>>3)&15;
    if((pressed&(LEFT|RIGHT)) && !(keys&DOWN)){
        difficulty^=1;centred(22,difficulty?"RELAXED: 5 LIVES / LESS DAMAGE":"NORMAL: 3 LIVES / ARCADE DAMAGE");sound_start(3);
    }
    if(keys&DOWN){
        if(pressed&LEFT)practice_select=practice_select?practice_select-1:4;
        if(pressed&RIGHT)practice_select=(practice_select+1)%5;
        blank_line();insert(2,"PRACTICE ");line[11]='1'+practice_select;insert(14,boss_names[practice_select]);text_line(22,line);
    }
    if(pressed&FIRE)new_game((keys&DOWN)!=0);
    else if(pressed&BUTTON2)show_manual(TITLE);
    else if(pressed&UP)password_show();
}
static void menu_tick(void){
    u8 i,repeat;stage_ticks++;
    if(game_mode==MAP){
        if(pressed&LEFT){selected=selected?selected-1:4;sound_start(3);}
        if(pressed&RIGHT){selected=(selected+1)%5;sound_start(3);}
        if(pressed&FIRE){
            if(selected==4){if(arena_mask==15)start_boss();else centred(16,"CLEAR SECTORS 1 2 3 AND 4 FIRST");}
            else if(arena_mask&(1<<selected))centred(16,"SECTOR ALREADY SECURED");else start_arena();
        }else if(pressed&BUTTON2)show_manual(MAP);
    }else if(game_mode==MANUAL){
        if(pressed&DOWN){music_enabled^=1;centred(23,music_enabled?"MUSIC ON":"MUSIC OFF");}
        if(pressed&(FIRE|BUTTON2)){if(menu_return==MAP)start_map();else start_title();}
    }else if(game_mode==PASSWORD){
        repeat=(stage_ticks&7)==0?keys:pressed;
        if(repeat&UP)pass_digits[pass_position]=(pass_digits[pass_position]+1)&31;
        if(repeat&DOWN)pass_digits[pass_position]=(pass_digits[pass_position]+31)&31;
        if(pressed&LEFT)pass_position=pass_position?pass_position-1:4;
        if(pressed&RIGHT)pass_position=(pass_position+1)%5;
        blank_line();for(i=0;i<5;i++)line[11+i*2]=alphabet[pass_digits[i]];text_line(13,line);
        if(pressed&FIRE){if(password_apply()){selected=0;start_map();}else{pass_error=1;centred(17,"INVALID CODE - CHECK THE SYMBOLS");sound_start(5);}}
        if(pressed&BUTTON2)start_title();
    }else if(game_mode==GAMEOVER){if(pressed&FIRE)new_game(0);else if(pressed&BUTTON2)start_title();}
    else if(game_mode==ENDING){player_dir=(stage_ticks>>3)&15;if(pressed&(FIRE|BUTTON2))start_title();}
}
/* Amiga StarDust soundtrack: title, one in-game tune per world, guardian
   themes (the egg machine and the professor get their own) and alternating
   hyperspace-tunnel tunes. CLEAR, MANUAL and PASSWORD keep whatever is playing. */
static void select_music(void){
    u8 t;
    switch(game_mode){
    case TITLE:t=MUS_TITLE;break;
    case ARENA:t=MUS_WORLD1+world;break;
    case BOSS:
        if(world==2)t=MUS_BOSS3;
        else if(world==4)t=boss_stage?MUS_FINAL:MUS_BOSS5;
        else t=MUS_BOSS;
        break;
    case TUNNEL:t=(world&1)?MUS_TUNNEL_A:MUS_TUNNEL_B;break;
    case CLEAR:case MANUAL:case PASSWORD:return;
    default:t=MUS_MENU;
    }
    music_play(t);
}
void main(void){
    rng_state=0xace1;difficulty=0;health=shield=100;lives=3;boss_max=1;
    hw_init();start_title();last_vblank=vblank_counter;
    for(;;){
        u8 pi;
        keys=joy_read();pressed=keys&~previous;previous=keys;logic_frames++;
        rng_state^=keys; /* player input makes repeated campaigns diverge */
        if(pause_request){pause_request=0;if(game_mode>=ARENA && game_mode<=CLEAR){pause_active^=1;hud_dirty=1;music_pause(pause_active);if(pause_active)sound_mute();}}
        if(!pause_active){
            if(game_mode==TITLE)title_tick();
            else if(game_mode==MAP || game_mode>=GAMEOVER)menu_tick();
            else gameplay_tick();
            select_music();
            sfx_tick();
        }
        if(game_mode>=ARENA && game_mode<=CLEAR && (!(logic_frames&7) || (hud_dirty && !(logic_frames&3))))make_hud();
        perf[4]=stamp();draw_game();perf[5]=stamp();
        /* Two-VBlank cadence: 30 Hz NTSC / 25 Hz PAL. If a heavy scene
           runs late, wait for a fresh transfer window instead of uploading
           patterns and SAT during active display. The whole transfer fits
           in blank when it begins within the first eight raster lines. */
        while((u16)(vblank_counter-last_vblank)<2 || VCOUNT<192 || VCOUNT>200){__asm halt __endasm;}
        last_vblank=vblank_counter;transfer_start=VCOUNT;
        perf[6]=stamp();if(!pause_active)animation_flush();sprites_flush();
        if(game_mode>=ARENA && game_mode<=CLEAR){
            vdp_copy(0x3d40+(u16)hud_phase*64,hud[hud_phase],64);if(++hud_phase>=3)hud_phase=0;
        }
        transfer_end=VCOUNT;perf[7]=stamp();
        for(pi=0;pi<8;pi++)done_perf[pi]=perf[pi];
    }
}
