#!/usr/bin/env python3
"""Compile the real Z80 cartridge and append Sega-mapper asset and music pages.
Requires SDCC 4.2+, Python 3. Resource banks are shipped with the source.
Use --art to rebake software-rendered caches; --render also rebuilds 3D art.
"""
from pathlib import Path
import subprocess, shutil, argparse, json, hashlib, re
ROOT=Path(__file__).resolve().parents[1]

def run(args,cwd=ROOT):
    print('+',' '.join(map(str,args)),flush=True)
    subprocess.run(list(map(str,args)),cwd=cwd,check=True)

def read_ihx(path):
    data=bytearray(32768); written=set(); upper=0
    for line in path.read_text().splitlines():
        if not line.startswith(':'): continue
        b=bytes.fromhex(line[1:]);assert sum(b)&255==0,'Intel HEX checksum error'
        n,addr,kind=b[0],int.from_bytes(b[1:3],'big'),b[3]
        if kind==0:
            addr+=upper
            if addr+n>0x7ff0:raise ValueError(f'Fixed code exceeds cartridge header: ${addr+n:04X}')
            data[addr:addr+n]=b[4:4+n];written.update(range(addr,addr+n))
        elif kind==4:upper=int.from_bytes(b[4:6],'big')<<16
    return data,max(written)+1

def header(data,size_code=1):
    h=0x7ff0
    data[h:h+16]=b'TMR SEGA'+b'\0\0\0\0'+bytes([0x93,0x19,0x00,0x40|size_code])
    checksum=(sum(data[:h])+sum(data[h+16:]))&65535
    data[h+10:h+12]=checksum.to_bytes(2,'little')
    return checksum

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--art',action='store_true');ap.add_argument('--render',action='store_true')
    ap.add_argument('--output',default='Stardust_SMS.sms');a=ap.parse_args()
    if a.render: run(['python3','render_assets.py','--only','all'],ROOT/'tools')
    if a.art or a.render:run(['python3','export_sms.py'],ROOT/'tools')
    if not shutil.which('sdcc'):raise SystemExit('Install SDCC: sudo apt-get install sdcc')
    work=ROOT/'build';work.mkdir(exist_ok=True)
    for name in ['crt0','vdp','music']:run(['sdasz80','-plosgff',work/(name+'.rel'),ROOT/'src'/(name+'.s')])
    common=['sdcc','-mz80','--std-c99','--sdcccall','1','--opt-code-speed','--max-allocs-per-node','10000','-I'+str(ROOT/'src')]
    for name in ['platform','game']:run(common+['-c',ROOT/'src'/(name+'.c'),'-o',work/(name+'.rel')])
    run(common+['--no-std-crt0','--code-loc','0x0200','--data-loc','0xc000',work/'crt0.rel',work/'vdp.rel',work/'music.rel',work/'platform.rel',work/'game.rel','-o',work/'game.ihx'])
    data,used=read_ihx(work/'game.ihx')
    for bank in range(2,20):
        blob=(ROOT/'assets/sms'/f'bank_{bank:02}.bin').read_bytes();assert len(blob)==16384
        data.extend(blob)
    # Music banks follow the art banks (see tools/convert_music.py, src/music.h).
    music=(ROOT/'assets/sms/music.bin').read_bytes();assert len(music)%16384==0
    first=int(re.search(r'#define MUSIC_FIRST_BANK (\d+)',(ROOT/'src/music.h').read_text()).group(1))
    assert len(data)==first*16384,'music banks must follow the art banks'
    data.extend(music)
    assert len(data)<=512*1024
    # 512 KiB standard Sega mapper cartridge. No fake padding to claim 4 MiB.
    data.extend(bytes([0xff])*(512*1024-len(data)))
    chk=header(data)
    dest=ROOT/a.output;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
    (ROOT/'tests/build_info.json').write_text(json.dumps({'rom_bytes':len(data),'fixed_code_bytes':used,
                'sha256':hashlib.sha256(data).hexdigest(),'sega_checksum':chk,'mapper':'Sega','region':'SMS Export (4)',
                'resource_banks':18,'music_banks':len(music)//16384,'max_cartridge_bytes':4194304},indent=2))
    (ROOT/'tests/linker.map').write_text((work/'game.map').read_text())
    (ROOT/'tests/symbols.noi').write_text((work/'game.noi').read_text())
    print(f'ROM: {dest}\nFixed code + constants: {used} / 32752 bytes\nCart: {len(data)} bytes\nChecksum: ${chk:04x}')
if __name__=='__main__':main()
