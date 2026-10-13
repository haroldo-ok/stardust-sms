#!/usr/bin/env python3
"""Reproducible SMS emulator QA, plus targeted RAM-side unit fixtures.

The campaign and boss-practice pilots use CONTROLLER INPUT ONLY. The tests for
individual pickups, code validation and game-over use explicit emulator RAM
fixtures to hit edge cases; no test/cheat hooks are present in the cartridge.

GENPLUSGX_CORE=/path/core.so GEARSYSTEM_CORE=/path/core.so python3 tools/test_rom.py
"""
from pathlib import Path
import subprocess, os, json, hashlib, re, csv, wave, struct
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
TEST=ROOT/'tests/release'; TEST.mkdir(parents=True,exist_ok=True)
ROM=ROOT/'Stardust_SMS.sms'; HARNESS=ROOT/'build/smsrun'
CORE=Path(os.environ.get('GENPLUSGX_CORE','/tmp/tools/gpgx/genesis_plus_gx_libretro.so'))
GEAR=Path(os.environ.get('GEARSYSTEM_CORE','/tmp/tools/gearsystem/platforms/libretro/gearsystem_libretro.so'))
SYMS={m.group(1):int(m.group(2),16) for m in re.finditer(r'^DEF _(\w+) 0x([0-9A-Fa-f]+)$',(ROOT/'tests/symbols.noi').read_text(),re.M)}
RESULTS=[]

def check(condition,label,detail=None):
    if not condition:raise AssertionError(label+': '+str(detail))
    RESULTS.append({'test':label,'passed':True,'detail':detail})
    print('PASS:',label,detail if detail is not None else '',flush=True)

def ram(case,frame):return (TEST/case/f'ram_{frame:06}.bin').read_bytes()
def value(data,name,n=1):
    off=SYMS[name]-0xc000
    return int.from_bytes(data[off:off+n],'little')
def state(data):
    return {name:value(data,name,4 if name=='score' else (2 if name in ['stage_time','stage_ticks','logic_frames','vblank_counter'] else 1)) for name in
        ['game_mode','world','practice','arena_mask','health','shield','lives','gun','bombs','weapon','improved','mission_fuel','boss_hp','boss_stage','score','stage_ticks','logic_frames','vblank_counter']}
def run(case,frames,*,script=None,pokes=None,dump=0,snaps=None,audio=False,pilot=None,pal=False,core=CORE,save_state=False):
    path=TEST/case;path.mkdir(exist_ok=True)
    for pattern in ['frame_*.ppm','ram_*.bin','state_*.bin']:
        for old in path.glob(pattern):old.unlink()
    cmd=[str(HARNESS),str(core),str(ROM),'--frames',str(frames),'--outdir',str(path),'--symbols',str(ROOT/'tests/symbols.noi'),'--trace']
    if script:cmd+=['--script',script]
    if pokes:cmd+=['--poke',','.join(pokes)]
    if dump:cmd+=['--dump-every',str(dump)]
    if snaps:cmd+=['--ram-at',','.join(map(str,snaps))]
    if audio:cmd+=['--audio',str(path/'audio.wav')]
    if save_state:cmd+=['--state']
    if pilot:cmd+=['--pilot',pilot]
    if pal:cmd+=['--pal']
    with (path/'run.log').open('w') as log:subprocess.run(cmd,check=True,stdout=log,stderr=log)
    return path

MUSIC=dict((m.group(1),int(m.group(2))) for m in re.finditer(r'^#define (MUS_\w+) (\d+)$',(ROOT/'src/music.h').read_text(),re.M))
def expected_music(mode,world,bstage):
    """Track that select_music() in src/game.c must pick; None = keep current."""
    if mode==0:return MUSIC['MUS_TITLE']
    if mode==2:return MUSIC['MUS_WORLD1']+world
    if mode==3:return MUSIC['MUS_BOSS3'] if world==2 else ((MUSIC['MUS_FINAL'] if bstage else MUSIC['MUS_BOSS5']) if world==4 else MUSIC['MUS_BOSS'])
    if mode==4:return MUSIC['MUS_TUNNEL_A'] if world&1 else MUSIC['MUS_TUNNEL_B']
    if mode in (6,9,10):return None
    return MUSIC['MUS_MENU']
def check_music_trace(case,trace):
    # skip boot and the samples next to a scene change (the scene loader runs
    # with the new mode already set, before the main loop selects the track)
    steady=[t for p,t,n in zip(trace,trace[1:],trace[2:]) if (p['mode'],p['world'],p['bstage'])==(t['mode'],t['world'],t['bstage'])==(n['mode'],n['world'],n['bstage'])]
    rows=[t for t in steady if expected_music(int(t['mode']),int(t['world']),int(t['bstage'])) is not None]
    bad=[t['frame'] for t in rows if int(t['music'])!=expected_music(int(t['mode']),int(t['world']),int(t['bstage']))]
    check(not bad,'soundtrack follows the game state '+case,{'samples':len(rows),'mismatches':bad})
    return {int(t['music']) for t in trace}

def poke(frame,name,v,n=1,offset=0):
    return [f'{frame}:0x{SYMS[name]+offset+i:04x}:{(v>>(i*8))&255}' for i in range(n)]
def actor(frame,index,*,x,y,kind,size=1,tier=0,vx=0,vy=0):
    vals=struct.pack('<HHbbBBBBBB',x*16,y*16,vx,vy,kind,size,tier,4,180,0)
    return [f'{frame}:0x{SYMS["actors"]+index*12+i:04x}:{b}' for i,b in enumerate(vals)]
def safe_arena_fixture(frame):
    p=[]
    for i in range(32):p+=poke(frame,'actors',0,offset=i*12+6)
    p+=actor(frame,0,x=8,y=18,kind=1,size=2,tier=3)
    for name,v,n in [('player_x',128*16,2),('player_y',80*16,2),('player_vx',0,1),('player_vy',0,1),('player_dir',0,1),('death_time',0,1),('invulnerable',255,1)]:p+=poke(frame,name,v,n)
    return p

def check_pixels(path):
    frames=sorted(path.glob('frame_*.ppm'))
    check(bool(frames),'video submitted '+path.name)
    checked=[]
    for f in frames[1:]:
        a=np.asarray(Image.open(f));colors=len(np.unique(a.reshape(-1,3),axis=0))
        if colors>1:
            check(a.shape==(192,256,3),'native 256x192 '+path.name,f.name)
            check(colors<=32,'hardware palette limit '+path.name,colors)
            checked.append(f.name)
            break
    check(bool(checked),'nonblank Mode-4 image '+path.name)


def main():
    b=ROM.read_bytes();h=0x7ff0
    check(len(b)==524288 and len(b)<=4194304,'cartridge fits 4 MiB allowance',len(b))
    check(b[h:h+8]==b'TMR SEGA' and b[h+15]==0x41,'Sega Export / 512 KiB header')
    chk=(sum(b[:h])+sum(b[h+16:]))&65535
    check(int.from_bytes(b[h+10:h+12],'little')==chk,'Sega checksum',hex(chk))
    check(b[0]==0xc3 and b[0x38]==0xc3 and b[0x66]==0xf5,'Z80 boot / IM-1 / pause vectors')
    for bank in range(2,20):
        d=(ROOT/'assets/sms'/f'bank_{bank:02}.bin').read_bytes()
        check(b[bank*16384:(bank+1)*16384]==d,'mapped bank '+str(bank))
        if bank==17:continue
        check(all(v<64 for v in d[:32]),'6-bit CRAM '+str(bank))
        nt=np.frombuffer(d[14368:15904],dtype='<u2')
        check(((nt&511)>=128).all() and ((nt&511)<=447).all(),'VRAM tile budget '+str(bank))
    music=(ROOT/'assets/sms/music.bin').read_bytes()
    first=int(re.search(r'#define MUSIC_FIRST_BANK (\d+)',(ROOT/'src/music.h').read_text()).group(1))
    check(b[first*16384:first*16384+len(music)]==music,'music banks '+str(first)+'..'+str(first+len(music)//16384-1),len(music))
    check(SYMS['vblank_counter']==0xc000,'work-RAM starts at $C000')
    (ROOT/'build').mkdir(exist_ok=True)
    subprocess.run(['gcc','-O2','-o',str(HARNESS),str(ROOT/'tools/smsrun.c'),'-ldl','-lm'],check=True)
    if not CORE.exists():raise SystemExit('Build Genesis Plus GX using tools/build_tools.sh or set GENPLUSGX_CORE.')
    script='120:b,160:,240:b,280:,300:ub,450:urb,900:lb,1350:b'
    path=run('smoke',1800,script=script,dump=300,snaps=[100,300,400,800,1200,1600],audio=True,save_state=True)
    check(value(ram('smoke',100),'music_track')==MUSIC['MUS_TITLE'],'title plays the Amiga title theme')
    check(value(ram('smoke',300),'music_track')==MUSIC['MUS_WORLD1'],'sector plays the world-1 in-game theme')
    check(value(ram('smoke',300),'music_is_pal')==0,'NTSC region detected for music tempo')
    check(value(ram('smoke',300),'game_mode')==2,'controller starts campaign sector')
    check(value(ram('smoke',300),'enemy_count')>0,'actual enemies initialized')
    check(value(ram('smoke',800),'gun')>=1,'gun token collected with controller input')
    check(value(ram('smoke',1200),'score',4)>0,'weapons damage rocks and enemies')
    d=ram('smoke',1200)
    check(value(d,'logic_frames',2)>400,'Z80 game loop advances at playable cadence',value(d,'logic_frames',2))
    check(value(d,'sat_count')<=63,'SAT terminator and sprite cap')
    check(192<=value(d,'transfer_start')<=203,'pattern/SAT transfers start inside VBlank')
    check(value(d,'transfer_start')<=value(d,'transfer_end')<=255,'pattern/SAT transfers finish before active display')
    check_pixels(path)
    # Parse the pinned Genesis Plus GX raw state: signature, 8 KiB RAM,
    # IO[16], VDP SAT[1024], VRAM[65536], CRAM[128], VSRAM[128], regs[32].
    st=(path/'state_001200.bin').read_bytes()
    off=16+8192+16+1024;regs=st[off+65536+256:off+65536+256+32]
    check(regs[1]==0x62 and regs[5]==0x7f and regs[6]==3,'SMS1/SMS2 SAT and sprite-generator address masks')
    vram=st[off:off+16384]
    check(vram[0x3f80:0x3fc0]!=vram[0x3f00:0x3f40],'hardware SAT X/pattern table is distinct from Y table')
    with wave.open(str(path/'audio.wav')) as w:
        check(w.getnchannels()==2 and w.getframerate()==44100,'PSG audio format')
        a=np.frombuffer(w.readframes(w.getnframes()),np.int16).astype(np.int32)
        check(int(np.abs(a).max())>100 and float(np.std(a))>20,'audible music and effects',{'peak':int(np.abs(a).max()),'rms':float(np.sqrt((a.astype(float)**2).mean()))})
    path=run('pal',1800,script=script,pal=True,dump=600,snaps=[1600])
    check('hz=49.70' in (path/'run.log').read_text(),'PAL 50 Hz VDP and interrupts')
    check(value(ram('pal',1600),'logic_frames',2)>500,'PAL gameplay loop')
    check(value(ram('pal',1600),'music_is_pal')==1,'PAL region detected for music tempo')
    check_pixels(path)
    if GEAR.exists():
        path=run('gearsystem',1800,script=script,core=GEAR,dump=600,snaps=[1200,1600])
        check(value(ram('gearsystem',1200),'logic_frames',2)>400,'independent Gearsystem Z80 execution')
        check(value(ram('gearsystem',1200),'score',4)>0,'independent Gearsystem gameplay')
        check_pixels(path)
    # Isolate the weapons with one off-axis rock that cannot be accidentally cleared.
    base='120:b,160:,240:b,280:,300:ub,430:,600:da,620:d,650:b,800:da,820:d,850:b,1000:da,1020:d,1050:b,1200:da,1220:d,1250:b'
    run('weapons',1350,script=base,pokes=safe_arena_fixture(450),snaps=[680,880,1080,1280])
    for f,w in [(680,1),(880,2),(1080,3),(1280,0)]:check(value(ram('weapons',f),'weapon')==w,'DOWN + 2 weapon '+str(w))
    # Full-speed E-upgraded thrust must not wrap +128 to -128 in a shot.
    p=safe_arena_fixture(450)+poke(600,'improved',1)+poke(600,'player_dir',4)
    p+=poke(600,'player_vx',64)+poke(600,'player_vy',0)
    run('boosted_shot',700,script='120:b,160:,240:b,280:,600:ub,680:',pokes=p,snaps=[640])
    d=ram('boosted_shot',640);off=SYMS['shots']-0xc000
    velocities=[struct.unpack_from('<b',d,off+i*10+4)[0] for i in range(14) if d[off+i*10+6] and d[off+i*10+7]==0]
    check(bool(velocities) and all(0<v<=120 for v in velocities),'boosted projectiles preserve forward direction',velocities)
    # Console pause stops simulation, not interrupts, and resumes on a second NMI.
    run('pause',1100,script='120:b,160:,240:b,280:,600:s,620:,900:s,920:',pokes=safe_arena_fixture(450),snaps=[700,820,1050])
    d1,d2,d3=[ram('pause',f) for f in [700,820,1050]]
    check(value(d1,'pause_active')==1 and value(d1,'stage_ticks',2)==value(d2,'stage_ticks',2),'console pause freezes gameplay')
    check(value(d2,'vblank_counter',2)>value(d1,'vblank_counter',2),'interrupts remain live while paused')
    check(value(d3,'pause_active')==0 and value(d3,'stage_ticks',2)>value(d2,'stage_ticks',2),'console pause resumes')
    # All nine token outcomes, with real proximity/collision/collection logic.
    pu=safe_arena_fixture(450)
    for name,v in [('health',40),('shield',20),('gun',0),('bombs',0),('lives',3),('improved',0),('mission_fuel',0)]:pu+=poke(450,name,v)
    snaps=[]
    for k in range(9):
        f=600+k*100;pu+=poke(f,'token_kind',k)+poke(f,'token_clock',0)
        pu+=actor(f,27,x=128,y=80,kind=5);snaps.append(f+50)
    run('tokens',1500,script='120:b,160:,240:b,280:',pokes=pu,snaps=snaps)
    expectations=[('gun',1),('health',100),('shield',100),('bombs',1),('score',None),('improved',1),('bombs',3),('lives',4),('mission_fuel',100)]
    for i,(name,v) in enumerate(expectations):
        d=ram('tokens',snaps[i]);actual=value(d,name,4 if name=='score' else 1)
        check(actual==v if v is not None else actual>=500,'token '+['G','heart','S','*','P','E','B','X','F'][i],actual)
    # Decoder is reached by the actual password menu's FIRE input.
    payload=2|(2<<3)|(5<<5)|(15<<9)|(1<<13)|(3<<15)|(1<<17)
    packed=(payload<<5)|((payload^(payload>>5)^(payload>>10)^(payload>>15)^23)&31)
    digits=[(packed>>(5*(4-i)))&31 for i in range(5)]
    p=[]
    for i,v in enumerate(digits):p+=poke(500,'pass_digits',v,offset=i)
    run('password_good',800,script='120:u,140:,520:b,540:',pokes=p,snaps=[700])
    d=ram('password_good',700)
    check(value(d,'game_mode')==1 and value(d,'world')==2 and value(d,'arena_mask')==15,'valid campaign code restores world and sectors')
    check(value(d,'gun')==2 and value(d,'weapon')==3 and value(d,'lives')==5,'code restores loadout and lives')
    p=[]
    for i in range(5):p+=poke(500,'pass_digits',0,offset=i)
    run('password_bad',800,script='120:u,140:,520:b,540:',pokes=p,snaps=[700])
    check(value(ram('password_bad',700),'game_mode')==10 and value(ram('password_bad',700),'pass_error')==1,'invalid code rejected safely')
    # Actual collision -> final death -> game-over, rather than writing mode.
    p=safe_arena_fixture(450)
    p+=actor(600,0,x=128,y=80,kind=1,size=2,tier=3)
    p+=poke(600,'health',1)+poke(600,'lives',1)+poke(600,'shield',0)+poke(600,'invulnerable',0)
    run('gameover',850,script='120:b,160:,240:b,280:',pokes=p,snaps=[780])
    check(value(ram('gameover',780),'game_mode')==7 and value(ram('gameover',780),'lives')==0,'lethal collision reaches game-over')
    # A pending death must resolve when the tunnel hands off to a bonus mission.
    p=safe_arena_fixture(450)+poke(450,'world',2)+poke(450,'game_mode',4)
    p+=poke(450,'health',0)+poke(450,'death_time',50)+poke(450,'stage_time',1,2)
    run('transition_respawn',700,script='120:b,160:,240:b,280:',pokes=p,snaps=[620])
    check(value(ram('transition_respawn',620),'game_mode')==5 and value(ram('transition_respawn',620),'health')>0,'pending respawn survives level transition')
    # Two complete, input-only playthroughs. No --poke, no cartridge debug hook.
    for case,pilot,frames in [('boss_practice','bosses',20000),('campaign','campaign',100000)]:
        path=run(case,frames,pilot=pilot,dump=1200,snaps=[frames-100])
        d=ram(case,frames-100)
        check(value(d,'game_mode')==8 and value(d,'world')==5,'input-only '+case+' reaches ending',state(d))
        check(value(d,'boss_hp')==0,'final professor defeated '+case)
        trace=list(csv.DictReader((path/'trace.csv').open()))
        boss_worlds={int(t['world']) for t in trace if int(t['mode'])==3}
        heard=check_music_trace(case,trace)
        if case=='boss_practice':
            need={MUSIC[k] for k in ['MUS_BOSS','MUS_BOSS3','MUS_BOSS5','MUS_FINAL']}
            check(need<=heard,'all four guardian themes heard',sorted(heard))
        else:
            check(set(MUSIC.values())<=heard,'every soundtrack piece heard in the campaign',sorted(heard))
        check(boss_worlds==set(range(5)),'all five distinct guardian encounters '+case,sorted(boss_worlds))
        if case=='campaign':
            check(value(d,'practice')==0,'full campaign, not practice')
            missions={int(t['world']) for t in trace if int(t['mode'])==5}
            check(missions=={2,4},'both gravity bonus missions',sorted(missions))
            tunnels={int(t['world']) for t in trace if int(t['mode'])==4}
            check(tunnels=={1,2,3,4},'all four inter-world warp tunnels',sorted(tunnels))
            for w in range(5):check(any(int(t['world'])==w and int(t['mask'])==15 for t in trace),'four sectors cleared in world '+str(w+1))
            check(value(d,'improved')==1 and value(d,'score',4)>20000,'progression and power-up persistence')
        check_pixels(path)
    report={'date':'2026-10-12','rom':ROM.name,'sha256':hashlib.sha256(b).hexdigest(),
            'rom_bytes':len(b),'physical_hardware_tested':False,'cores':['Genesis Plus GX']+(['Gearsystem'] if GEAR.exists() else []),
            'tests':RESULTS,'assertions_passed':len(RESULTS),
            'notes':'Campaign and guardian practice completed with controller-only pilots; targeted edge cases use documented emulator-side RAM fixtures.'}
    (ROOT/'tests/QA_report.json').write_text(json.dumps(report,indent=2))
    print('ALL',len(RESULTS),'ASSERTIONS PASSED. SHA256',report['sha256'],flush=True)

if __name__=='__main__':main()
