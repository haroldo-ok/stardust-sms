/* smsrun: original, reproducible headless libretro integration-test frontend.
 * Requires a separately built Genesis Plus GX libretro core (not bundled).
 * gcc -O2 -o smsrun smsrun.c -ldl -lm
 * Script: frame:udlrabsp (a=SMS 2, b=SMS 1, s=console pause).
 * --poke frame:0xRAM:byte,... is ONLY an emulator-side test fixture, never a
 * cartridge cheat. --pilot uses real controller input, with no RAM writes.
 */
#include "libretro.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdarg.h>
#include <dlfcn.h>
#include <math.h>
#include <sys/stat.h>
#define MAX_EVENTS 8192
#define MAX_VARS 256
static struct {long frame;unsigned keys;} events[MAX_EVENTS];
static struct {long frame;unsigned addr,value;} pokes[MAX_EVENTS];
static int nevents,npokes;
static unsigned buttons,pixel_format=RETRO_PIXEL_FORMAT_0RGB1555;
static const void *video;static unsigned vw,vh;static size_t vpitch;
static FILE *wav;static uint32_t wav_bytes;static unsigned wav_rate=44100;
static bool pal,quiet=true;
static const char *save_dir=".";
static struct {char *key,*value;} variables[MAX_VARS];static unsigned nvars;
static unsigned char *ram;static size_t ram_size;
static int sym_mode=-1,sym_world,sym_mask,sym_selected,sym_gun,sym_health,sym_shield,sym_weapon,sym_bombs;
static int sym_px,sym_py,sym_dir,sym_actors,sym_bx,sym_by,sym_bstage,sym_parts,sym_logic,sym_music=-1;
static const char *pilot;
static unsigned pilot_mode=255,pilot_turn,pilot_steps,menu_wait,pilot_goal;
static void log_callback(enum retro_log_level level,const char *fmt,...){
    if(quiet && level<RETRO_LOG_WARN)return;
    va_list ap;va_start(ap,fmt);vfprintf(stderr,fmt,ap);va_end(ap);
}
static const char *get_var(const char *key){
    if(!strcmp(key,"genesis_plus_gx_region_detect"))return pal?"pal":"ntsc-u";
    if(!strcmp(key,"genesis_plus_gx_system_hw"))return "master system";
    if(!strcmp(key,"genesis_plus_gx_bios"))return "disabled";
    if(!strcmp(key,"genesis_plus_gx_overscan"))return "disabled";
    for(unsigned i=0;i<nvars;i++)if(!strcmp(key,variables[i].key))return variables[i].value;
    return NULL;
}
static bool environment(unsigned cmd,void *data){
    switch(cmd){
    case RETRO_ENVIRONMENT_GET_CAN_DUPE:*(bool*)data=true;return true;
    case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:pixel_format=*(enum retro_pixel_format*)data;return true;
    case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:*(const char**)data=".";return true;
    case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:*(const char**)data=save_dir;return true;
    case RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY:*(const char**)data=".";return true;
    case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:((struct retro_log_callback*)data)->log=log_callback;return true;
    case RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:*(bool*)data=false;return true;
    case RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION:*(unsigned*)data=0;return true;
    case RETRO_ENVIRONMENT_GET_LANGUAGE:*(unsigned*)data=RETRO_LANGUAGE_ENGLISH;return true;
    case RETRO_ENVIRONMENT_GET_INPUT_BITMASKS:return true;
    case RETRO_ENVIRONMENT_GET_VARIABLE:{struct retro_variable*v=data;v->value=get_var(v->key);return v->value!=NULL;}
    case RETRO_ENVIRONMENT_SET_VARIABLES:{
        const struct retro_variable*v=data;
        for(;v->key && nvars<MAX_VARS;v++){
            const char*s=strchr(v->value,';');if(!s)continue;s++;while(*s==' ')s++;
            size_t len=strcspn(s,"|");variables[nvars].key=strdup(v->key);variables[nvars].value=strndup(s,len);nvars++;
        }return true;
    }
    case RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:
    case RETRO_ENVIRONMENT_SET_CONTROLLER_INFO:
    case RETRO_ENVIRONMENT_SET_GEOMETRY:
    case RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO:
    case RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL:
    case RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME:
    case RETRO_ENVIRONMENT_SET_MESSAGE:return true;
    default:return false;
    }
}
static void video_cb(const void *data,unsigned w,unsigned h,size_t pitch){if(data){video=data;vw=w;vh=h;vpitch=pitch;}}
static void input_poll(void){}
static int16_t input_state(unsigned port,unsigned device,unsigned index,unsigned id){
    (void)index;if(port || device!=RETRO_DEVICE_JOYPAD)return 0;
    if(id==RETRO_DEVICE_ID_JOYPAD_MASK)return (int16_t)buttons;
    return id<16?((buttons>>id)&1):0;
}
static size_t audio_batch(const int16_t *data,size_t frames){
    if(wav){fwrite(data,4,frames,wav);wav_bytes+=(uint32_t)frames*4;}
    return frames;
}
static void audio_sample(int16_t l,int16_t r){int16_t d[2]={l,r};audio_batch(d,1);}
static void le32(FILE*f,uint32_t n){for(int i=0;i<4;i++)fputc((n>>(i*8))&255,f);}
static void le16(FILE*f,uint16_t n){fputc(n&255,f);fputc(n>>8,f);}
static void wav_header(void){
    rewind(wav);fwrite("RIFF",1,4,wav);le32(wav,36+wav_bytes);fwrite("WAVEfmt ",1,8,wav);le32(wav,16);
    le16(wav,1);le16(wav,2);le32(wav,wav_rate);le32(wav,wav_rate*4);le16(wav,4);le16(wav,16);
    fwrite("data",1,4,wav);le32(wav,wav_bytes);
}
static void dump_video(const char*fn){
    if(!video)return;FILE*f=fopen(fn,"wb");if(!f)return;fprintf(f,"P6\n%u %u\n255\n",vw,vh);
    for(unsigned y=0;y<vh;y++)for(unsigned x=0;x<vw;x++){
        uint32_t v;unsigned r,g,b;const uint8_t*p=(const uint8_t*)video+y*vpitch;
        if(pixel_format==RETRO_PIXEL_FORMAT_XRGB8888){v=((const uint32_t*)p)[x];r=(v>>16)&255;g=(v>>8)&255;b=v&255;}
        else {v=((const uint16_t*)p)[x];
            if(pixel_format==RETRO_PIXEL_FORMAT_RGB565){r=(v>>11)&31;g=(v>>5)&63;b=v&31;r=(r<<3)|(r>>2);g=(g<<2)|(g>>4);b=(b<<3)|(b>>2);}
            else{r=(v>>10)&31;g=(v>>5)&31;b=v&31;r=(r<<3)|(r>>2);g=(g<<3)|(g>>2);b=(b<<3)|(b>>2);}
        }fputc(r,f);fputc(g,f);fputc(b,f);
    }fclose(f);
}
static unsigned parse_keys(const char*s){
    unsigned b=0;for(;*s;s++)switch(*s){
    case 'u':b|=1<<RETRO_DEVICE_ID_JOYPAD_UP;break;
    case 'd':b|=1<<RETRO_DEVICE_ID_JOYPAD_DOWN;break;
    case 'l':b|=1<<RETRO_DEVICE_ID_JOYPAD_LEFT;break;
    case 'r':b|=1<<RETRO_DEVICE_ID_JOYPAD_RIGHT;break;
    case 'a':b|=1<<RETRO_DEVICE_ID_JOYPAD_A;break;
    case 'b':b|=1<<RETRO_DEVICE_ID_JOYPAD_B;break;
    case 's':b|=1<<RETRO_DEVICE_ID_JOYPAD_START;break;
    case 'x':b|=1<<RETRO_DEVICE_ID_JOYPAD_SELECT;break;
    }return b;
}
static void parse_script(const char*s,bool poke){
    char*copy=strdup(s),*save,*t=strtok_r(copy,",",&save);
    for(;t;t=strtok_r(NULL,",",&save)){
        char*c=strchr(t,':');if(!c)continue;*c++=0;
        if(poke && npokes<MAX_EVENTS){char*v=strchr(c,':');if(!v)continue;*v++=0;pokes[npokes].frame=atol(t);pokes[npokes].addr=strtoul(c,NULL,0);pokes[npokes++].value=strtoul(v,NULL,0);}
        else if(!poke && nevents<MAX_EVENTS){events[nevents].frame=atol(t);events[nevents++].keys=parse_keys(c);}
    }free(copy);
}
static unsigned rd8(int addr){return addr>=0xc000 && addr<0xe000?ram[addr-0xc000]:0;}
static unsigned rd16(int addr){return rd8(addr)|(rd8(addr+1)<<8);}
static void load_symbols(const char *path){
    FILE*f=fopen(path,"r");if(!f){perror(path);exit(1);}char n[256];unsigned a;
    char text[512];
    while(fgets(text,sizeof text,f)){
        if(sscanf(text,"DEF %255s %x",n,&a)!=2)continue;
#define SYM(name,var) if(!strcmp(n,"_" name))var=(int)a
        SYM("game_mode",sym_mode);SYM("world",sym_world);SYM("arena_mask",sym_mask);SYM("selected",sym_selected);
        SYM("gun",sym_gun);SYM("weapon",sym_weapon);SYM("bombs",sym_bombs);SYM("health",sym_health);SYM("shield",sym_shield);SYM("player_x",sym_px);SYM("player_y",sym_py);
        SYM("player_dir",sym_dir);SYM("actors",sym_actors);SYM("boss_x",sym_bx);SYM("boss_y",sym_by);SYM("boss_stage",sym_bstage);
        SYM("boss_parts",sym_parts);SYM("logic_frames",sym_logic);SYM("music_track",sym_music);
#undef SYM
    }fclose(f);
}
static unsigned controller_pilot(long frame){
    if(!ram || sym_mode<0)return 0;
    unsigned mode=rd8(sym_mode),w=rd8(sym_world),px=rd16(sym_px)>>4,py=rd16(sym_py)>>4,dir=rd8(sym_dir);
    if(mode!=pilot_mode){pilot_mode=mode;menu_wait=0;pilot_steps=0;fprintf(stderr,"pilot f=%ld mode=%u world=%u hp=%u gun=%u mask=%u\n",frame,mode,w+1,rd8(sym_health),rd8(sym_gun),rd8(sym_mask));}
    pilot_steps++;
    unsigned fire=1<<RETRO_DEVICE_ID_JOYPAD_B,down=1<<RETRO_DEVICE_ID_JOYPAD_DOWN,up=1<<RETRO_DEVICE_ID_JOYPAD_UP;
    unsigned left=1<<RETRO_DEVICE_ID_JOYPAD_LEFT,right=1<<RETRO_DEVICE_ID_JOYPAD_RIGHT;
    if(mode==0){if(frame<90)return 0;return pilot_steps%24<12?(fire|(!strcmp(pilot,"bosses")?down:0)):0;}
    if(mode==1){
        unsigned mask=rd8(sym_mask),sel=rd8(sym_selected),goal=4;
        for(unsigned i=0;i<4;i++)if(!(mask&(1<<i))){goal=i;break;}
        return pilot_steps%24<12?(sel==goal?fire:right):0;
    }
    if(mode==6)return pilot_steps>90?fire:0;
    if(mode==7)return pilot_steps>120?fire:0;
    if(mode==8 || mode>=9)return 0;
    /* The four weapons are selected through DOWN+2, not RAM mutation.
       Missiles suit guardians; spread blasters suit asteroid sectors. */
    if((mode==3 && !(w==4 && rd8(sym_bstage)==1) && rd8(sym_weapon)!=2)
       || (mode==2 && rd8(sym_weapon)!=0)){
        return pilot_steps%16<8?(down|(1<<RETRO_DEVICE_ID_JOYPAD_A)):0;
    }
    /* Use the real bomb inventory instead of hoarding nine charges while
       dying. A brief, released Button-2 pulse cannot open the weapon chord. */
    if((mode==2 || (mode==3 && !(w==4 && rd8(sym_bstage)==1)))
       && pilot_steps>120 && pilot_steps%240<8 && rd8(sym_bombs)>1)
        return 1<<RETRO_DEVICE_ID_JOYPAD_A;
    unsigned tx=128,ty=64;double best=1e9;
    if(mode==3){
        tx=rd8(sym_bx);ty=rd8(sym_by);
        if(w==1)for(unsigned i=0;i<4;i++)if(rd8(sym_parts+i)){double p=(rd8(sym_bx)-px)*(double)(rd8(sym_bx)-px);(void)p;break;}
    }else if(mode==4){
        unsigned k=fire;if((pilot_steps/80)&1)k|=left;else k|=right;
        if((pilot_steps/180)&1)k|=up;else k|=down;return k;
    }else if(mode==5){tx=235;ty=26;}
    else{
        /* Aiming and steering are controller inputs only; no invulnerability
           or score writes. Token pursuit teaches the upgrade path as well. */
        for(unsigned i=0;i<32;i++){
            int a=sym_actors+i*12;unsigned kind=rd8(a+6);if(!(kind==1 || kind==2 || kind==3 || kind==5))continue;
            if(w==4 && kind==2)continue; /* invulnerable Orbit Platers: dodge, do not chase */
            unsigned x=rd16(a)>>4,y=rd16(a+2)>>4;int dx=(int)x-(int)px;if(dx>128)dx-=256;if(dx<-128)dx+=256;
            int dy=(int)y-(int)py;double d=dx*dx+dy*dy;
            if(kind==5){if(rd8(sym_gun)<2 || rd8(sym_health)<70)d*=.4;else d*=3;}
            if(d<best){best=d;tx=x;ty=y;}
        }
    }
    int dx=(int)tx-(int)px,dy=(int)ty-(int)py;if(dx>128)dx-=256;if(dx<-128)dx+=256;
    double angle=atan2((double)dx,(double)-dy);int target=((int)lround(angle*8.0/3.141592653589793)+16)&15;
    int turn=(target-(int)dir+16)&15;unsigned k=fire;
    if(turn>8)k|=left;else if(turn)k|=right;
    double d=dx*dx+dy*dy;
    if(mode==3 && w==4 && rd8(sym_bstage)==1){
        /* Accelerate, then coast with shields into the edge-bound professor. */
        if(d<1700 && rd8(sym_shield)>5)k|=down;else if(turn<2 || turn>14)k|=up;
    }else if(d<625 && rd8(sym_shield)>20)k|=down;
    else if(d>2400 && (turn<2 || turn>14))k|=up;
    if((frame%2400)==1200 && rd8(sym_health)<30)k|=1<<RETRO_DEVICE_ID_JOYPAD_A;
    return k;
}
#define LOAD(name) __typeof__(&name) p_##name=(__typeof__(&name))dlsym(core,#name)
int main(int argc,char**argv){
    if(argc<3){fprintf(stderr,"usage: smsrun core.so rom.sms --frames N --outdir DIR [--script ...] [--ram-at ...] [--audio ...] [--poke ...] [--pal] [--pilot campaign|bosses --symbols ...]\n");return 1;}
    long frames=600,dump=0;const char*out=".",*ram_at=NULL,*audio=NULL,*symbols=NULL;bool trace=false,save_state=false;
    for(int i=3;i<argc;i++){
        if(!strcmp(argv[i],"--frames") && i+1<argc)frames=atol(argv[++i]);
        else if(!strcmp(argv[i],"--dump-every") && i+1<argc)dump=atol(argv[++i]);
        else if(!strcmp(argv[i],"--outdir") && i+1<argc)out=argv[++i];
        else if(!strcmp(argv[i],"--script") && i+1<argc)parse_script(argv[++i],false);
        else if(!strcmp(argv[i],"--poke") && i+1<argc)parse_script(argv[++i],true);
        else if(!strcmp(argv[i],"--ram-at") && i+1<argc)ram_at=argv[++i];
        else if(!strcmp(argv[i],"--audio") && i+1<argc)audio=argv[++i];
        else if(!strcmp(argv[i],"--symbols") && i+1<argc)symbols=argv[++i];
        else if(!strcmp(argv[i],"--pilot") && i+1<argc)pilot=argv[++i];
        else if(!strcmp(argv[i],"--pal"))pal=true;
        else if(!strcmp(argv[i],"--trace"))trace=true;
        else if(!strcmp(argv[i],"--state"))save_state=true;
        else if(!strcmp(argv[i],"-v"))quiet=false;
    }
    mkdir(out,0755);save_dir=out;
    if(symbols)load_symbols(symbols);
    void*core=dlopen(argv[1],RTLD_NOW);if(!core){fprintf(stderr,"dlopen: %s\n",dlerror());return 1;}
    LOAD(retro_init);LOAD(retro_deinit);LOAD(retro_run);LOAD(retro_load_game);LOAD(retro_unload_game);
    LOAD(retro_serialize_size);LOAD(retro_serialize);
    LOAD(retro_get_system_info);LOAD(retro_get_system_av_info);LOAD(retro_get_memory_data);LOAD(retro_get_memory_size);
    LOAD(retro_set_environment);LOAD(retro_set_video_refresh);LOAD(retro_set_audio_sample);LOAD(retro_set_audio_sample_batch);
    LOAD(retro_set_input_poll);LOAD(retro_set_input_state);LOAD(retro_set_controller_port_device);
    p_retro_set_environment(environment);p_retro_set_video_refresh(video_cb);p_retro_set_audio_sample(audio_sample);p_retro_set_audio_sample_batch(audio_batch);
    p_retro_set_input_poll(input_poll);p_retro_set_input_state(input_state);p_retro_init();p_retro_set_controller_port_device(0,RETRO_DEVICE_JOYPAD);
    FILE*r=fopen(argv[2],"rb");if(!r){perror(argv[2]);return 1;}fseek(r,0,SEEK_END);long size=ftell(r);rewind(r);void*data=malloc(size);fread(data,1,size,r);fclose(r);
    struct retro_game_info game={argv[2],data,(size_t)size,NULL};if(!p_retro_load_game(&game)){fprintf(stderr,"ROM rejected\n");return 2;}
    struct retro_system_av_info av;p_retro_get_system_av_info(&av);struct retro_system_info info;p_retro_get_system_info(&info);
    fprintf(stderr,"core=%s video=%ux%u hz=%.2f rate=%.0f\n",info.library_name,av.geometry.base_width,av.geometry.base_height,av.timing.fps,av.timing.sample_rate);
    ram=p_retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM);ram_size=p_retro_get_memory_size(RETRO_MEMORY_SYSTEM_RAM);
    if(audio){wav=fopen(audio,"wb");if(!wav){perror(audio);return 1;}wav_rate=(unsigned)av.timing.sample_rate;wav_header();}
    FILE*tr=NULL;if(trace){char fn[512];snprintf(fn,sizeof fn,"%s/trace.csv",out);tr=fopen(fn,"w");fprintf(tr,"frame,mode,world,health,gun,mask,logic,bstage,music\n");}
    for(long f=0;f<frames;f++){
        if(pilot)buttons=controller_pilot(f);
        for(int i=0;i<nevents;i++)if(events[i].frame==f)buttons=events[i].keys;
        for(int i=0;i<npokes;i++)if(pokes[i].frame==f && ram && pokes[i].addr>=0xc000 && pokes[i].addr<0xe000)ram[pokes[i].addr-0xc000]=(uint8_t)pokes[i].value;
        p_retro_run();
        if(dump && f%dump==0){char fn[512];snprintf(fn,sizeof fn,"%s/frame_%06ld.ppm",out,f);dump_video(fn);}
        if(tr && f%60==0)fprintf(tr,"%ld,%u,%u,%u,%u,%u,%u,%u,%u\n",f,rd8(sym_mode),rd8(sym_world),rd8(sym_health),rd8(sym_gun),rd8(sym_mask),rd16(sym_logic),rd8(sym_bstage),sym_music>=0?rd8(sym_music):255u);
        if(ram_at){char*copy=strdup(ram_at),*save,*s=strtok_r(copy,",",&save);for(;s;s=strtok_r(NULL,",",&save))if(atol(s)==f){
            char fn[512];snprintf(fn,sizeof fn,"%s/ram_%06ld.bin",out,f);FILE*o=fopen(fn,"wb");if(o){fwrite(ram,1,ram_size,o);fclose(o);}
            if(save_state){size_t z=p_retro_serialize_size();void*buf=calloc(1,z);
                if(p_retro_serialize(buf,z)){snprintf(fn,sizeof fn,"%s/state_%06ld.bin",out,f);o=fopen(fn,"wb");if(o){fwrite(buf,1,z,o);fclose(o);}}free(buf);}
        }free(copy);}
    }
    if(wav){wav_header();fclose(wav);}if(tr)fclose(tr);
    p_retro_unload_game();p_retro_deinit();dlclose(core);free(data);
    printf("ran %ld frames, audio bytes %u\n",frames,wav_bytes);return 0;
}
