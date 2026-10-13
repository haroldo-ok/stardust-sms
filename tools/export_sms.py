#!/usr/bin/env python3
"""Bake software-prerendered 3D art to REAL Sega Master System Mode-4 data.

SMS specifics: 32 ONE-byte CRAM entries; 4 bitplanes per tile row; one sprite
palette; 8x16 even-aligned sprite patterns. Sprite patterns 0..127, backgrounds
128..447, name table $3800, SAT $3F00.  Large ROM does not enlarge VRAM.

Each 16 KiB Sega-mapper resource bank:
  0: background palette (16) + sprite palette (16)
 32: sprite patterns (4096)
4128: background patterns (10240)
14368: name table (1536)
Remaining 480 bytes reserved. All data and source persist in assets/sms/.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
import json, math
import numpy as np
from PIL import Image, ImageFont, ImageDraw, ImageFilter
import art_helpers as H
import scene3d as S
import models as M
from render_assets import render_mesh_sprite

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'assets/sms'; PREV=ROOT/'assets/preview'
OUT.mkdir(parents=True,exist_ok=True)
PAL_SMS=np.array([0x00,0x00,0x15,0x2a,0x3f,0x05,0x0b,0x1f,
                  0x12,0x26,0x3c,0x24,0x39,0x16,0x01,0x1d],np.uint8)
PAL_RGB=np.array([H.sms_to_rgb(int(v)) for v in PAL_SMS])
BG_FIXED=[0x00,0x10,0x15,0x2a,0x3f,0x03,0x3c,0x0f]
BG_BASE=128; BG_COUNT=320; FONT_COUNT=64
HP_BASE=192; SH_BASE=201; BOSS_BAR_BASE=210; ART_BASE=219
N_ART=448-ART_BASE
SIZES={'small':(8,8),'med':(16,16),'big':(24,24)}
TINT_ORDER=['grey','blue','purple','gold']
TINT_INDICES=[[1,2,3,4],[1,11,12,4],[1,8,9,4],[5,6,7,4]]
COMMON={'player':0,'shield':4,'shot':8,'orb':10,'flame':12,'token':14,'expl':18}
ROCK_BASE=38; ENEMY_A=110; ENEMY_B=118; MINE=126
ENEMIES=[('drone','trilon'),('blade','bomber'),('thorn','plate'),
         ('speeder','drone'),('plate','bomber')]
BOSSES=[ [('b1_housing',1),('b1_pillar',1),('b1_door',1),('b1_core',4),('b1_turret',4)],
         [('b2_eye',4),('b2_arm',4)],
         [('b3_head',2),('b3_seg',2),('b3_tail',2)],
         [('b4_blades',2),('b4_plate',1),('b4_ball',2)],
         [('b5_egg',2),('b5_hatch',1),('b5_prof',2)] ]


def encode_tile(t):
    """SMS row-interleaved planar format, NOT packed chunky nibbles."""
    t=np.asarray(t,np.uint8); out=bytearray()
    for y in range(8):
        for plane in range(4):
            v=0
            for x in range(8): v |= ((int(t[y,x])>>plane)&1) << (7-x)
            out.append(v)
    return bytes(out)


def decode_tile(raw):
    a=np.frombuffer(raw,np.uint8).reshape(8,4)
    t=np.zeros((8,8),np.uint8)
    for p in range(4):
        for x in range(8): t[:,x] |= ((a[:,p]>>(7-x))&1)<<p
    return t


def sprite_idx(im,valid=None):
    rgb=np.clip(S.tone_map(np.nan_to_num(im[...,:3].astype(np.float32)),exposure=1.3,gamma=1.0)*1.9-.10,0,1)
    ids=list(range(1,16)) if valid is None else valid
    # No dithering on tiny, shaded sprites: silhouette and highlights matter.
    if valid is not None and valid in TINT_INDICES:
        lum=(im[...,:3]*np.array([.22,.67,.11])).sum(-1)
        visible=im[...,3]>.65
        bright=max(float(np.percentile(lum[visible],97)),.05) if visible.any() else 1.0
        shade=np.clip(lum/bright,0,1)**.85
        levels=np.array([0,.28,.62,1.0],np.float32)
        idx=np.array(valid,np.uint8)[abs(shade[...,None]-levels).argmin(-1)]
    else:
        idx=H.quantize(rgb,PAL_RGB,ids,dither=.15)
    idx[im[...,3]<0.35]=0
    return idx


def sprite_blob(idx):
    h,w=idx.shape; cols=(w+7)//8; rows=(h+15)//16
    padded=np.zeros((rows*16,cols*8),np.uint8); padded[:h,:w]=idx
    out=bytearray()
    for cy in range(rows):
        for cx in range(cols):
            cell=padded[cy*16:cy*16+16,cx*8:cx*8+8]
            out+=encode_tile(cell[:8])+encode_tile(cell[8:])
    return bytes(out)


def token_image(base,char):
    im=base.astype(np.float32).copy()
    font=ImageFont.truetype(H.BODY_FONT,10)
    canvas=Image.new('L',(16,16)); d=ImageDraw.Draw(canvas)
    bb=d.textbbox((0,0),char,font=font)
    d.text(((16-bb[2]+bb[0])//2-bb[0],(16-bb[3]+bb[1])//2-bb[1]),char,font=font,fill=255)
    m=np.asarray(canvas,np.float32)/255
    if char=='H':
        # Render a small embossed heart silhouette in the token's recessed face.
        yy,xx=np.mgrid[0:16,0:16]; x=(xx-7.5)/4; y=-(yy-8)/4
        m=(((x*x+y*y-1)**3-x*x*y*y*y)<0).astype(np.float32)
    glyph=H.emboss_3d(m,bevel=0.5,ambient=0.32)
    al=glyph[...,3:4]
    im[...,:3]=im[...,:3]*(1-al)+glyph[...,:3]*al
    im[...,3]=np.maximum(im[...,3],m)
    return im


def common_patterns(sprites,tokens):
    buf=bytearray(4096)
    def put(pat,key,valid=None):
        data=sprite_blob(sprite_idx(sprites[key],valid)); buf[pat*32:pat*32+len(data)]=data
    put(0,'player_00',[1,2,3,4,10,11,12,14,15])
    put(4,'shield_00',[1,4,10,11,12])
    # Both projectile types are 3D rendered luminous spheres; a sphere is
    # direction-independent and still legible at SMS resolution.
    shot,_=render_mesh_sprite(M.build_orb(color=(1.0,0.83,0.18)),8,8,fit=0.70)
    orb,_=render_mesh_sprite(M.build_orb(color=(1.0,0.18,0.08)),8,8,fit=0.78)
    sprites['shot_sms']=shot; sprites['orb_sms']=orb
    put(8,'shot_sms',[2,4,5,6,7]); put(10,'orb_sms',[2,4,6,7,13])
    put(12,'flame_00',[4,5,6,7,13])
    tok=sprite_blob(sprite_idx(tokens[0])); buf[14*32:18*32]=tok
    for f in range(5): put(18+f*4,f'expl_big_{f:02}',[2,4,5,6,7,13])
    return buf


def logo(img,text,y,size=34):
    font=ImageFont.truetype(H.TITLE_FONT,size)
    can=Image.new('L',(256,60));d=ImageDraw.Draw(can)
    bb=d.textbbox((0,0),text,font=font); w=bb[2]-bb[0]
    if w>246:
        font=ImageFont.truetype(H.TITLE_FONT,int(size*246/w));bb=d.textbbox((0,0),text,font=font);w=bb[2]-bb[0]
    d.text(((256-w)//2-bb[0],3-bb[1]),text,font=font,fill=255)
    m=np.asarray(can,np.float32)/255
    # Extruded metallic lettering, with a gold rim and a specular bevel.
    for dy,dx in [(3,3),(2,2),(1,1)]:
        mm=np.roll(np.roll(m,dy,0),dx,1)
        img[y:y+60]=img[y:y+60]*(1-mm[...,None])+np.array([.30,.15,.08])*mm[...,None]
    rgba=H.emboss_3d(m,bevel=.6,ambient=.25)
    rgb=S.tone_map(rgba[...,:3],exposure=1.5,gamma=.8)
    img[y:y+60]=img[y:y+60]*(1-m[...,None])+rgb*m[...,None]
    return img


def font_tile(char):
    font=ImageFont.truetype(H.BODY_FONT,9)
    im=Image.new('L',(8,8));d=ImageDraw.Draw(im)
    bb=d.textbbox((0,0),char,font=font)
    d.text(((8-bb[2]+bb[0])//2-bb[0],(8-bb[3]+bb[1])//2-bb[1]),char,font=font,fill=255)
    mask=np.asarray(im,np.float32)/255
    rgba=H.emboss_3d(mask,bevel=.6,ambient=.3)
    lum=S.tone_map(rgba[...,:3],exposure=1.8,gamma=.7).mean(-1)
    idx=np.ones((8,8),np.uint8)
    idx[(mask>.25)&(lum<=.43)]=2
    idx[(mask>.25)&(lum>.43)&(lum<=.63)]=3
    idx[(mask>.25)&(lum>.63)]=4
    return idx


def ui_tiles():
    tiles=[font_tile(chr(i)) for i in range(32,96)]
    for col in [5,6,7]:
        for n in range(9):
            t=np.zeros((8,8),np.uint8)
            t[1:7,:]=1; t[1,:]=3; t[6,:]=2
            t[2:6,:n]=col
            if n: t[2,:n]=4; t[5,:n]=2
            tiles.append(t)
    assert len(tiles)==91
    return tiles


def choose_bg_palette(img):
    fixed=list(BG_FIXED)
    C=H.kmeans_palette(img.reshape(-1,3),24,seed=13,iters=10)
    # Quantize palette before pixels. Using unquantized k-means centres here
    # would produce a preview that the real hardware cannot reproduce.
    candidates=[H.to_sms(c) for c in C]
    for c in candidates:
        if c not in fixed: fixed.append(c)
        if len(fixed)==16: break
    if len(fixed)<16:
        all_rgb=np.array([H.sms_to_rgb(v) for v in range(64)])
        for c in np.argsort(((all_rgb[:,None,:]-C[None,:,:])**2).sum(-1).min(1)):
            if int(c) not in fixed: fixed.append(int(c))
            if len(fixed)==16: break
    return fixed


def tile_dictionary(cells,pal,n):
    """Weighted medoid vector quantization of ACTUAL palette-colour tiles.

    It is not legal to place 700 unique tiles in the SMS's 16KB VRAM.  This
    dictionary minimizes error over the entire scene rather than keeping
    only the first rows, and previews reconstruct the actual final tilemap.
    """
    uniq,inv,counts=np.unique(np.array(cells).reshape(len(cells),64),axis=0,return_inverse=True,return_counts=True)
    if len(uniq)<=n: return list(uniq.reshape(-1,8,8)),inv,0
    colors=np.array([H.sms_to_rgb(v) for v in pal],np.float32)
    X=colors[uniq].reshape(len(uniq),192)
    # Edge detail, bright stars and specular surfaces deserve more weight.
    weights=counts.astype(np.float32)*(0.55+X.mean(1)*1.1)
    rng=np.random.default_rng(43)
    C=[X[int(np.argmax(weights))]]; dmin=((X-C[0])**2).sum(1)
    for k in range(1,n):
        p=dmin*weights; tot=p.sum()
        idx=int(rng.choice(len(X),p=p/tot)) if tot>1e-9 else k%len(X)
        C.append(X[idx]);dmin=np.minimum(dmin,((X-X[idx])**2).sum(1))
    C=np.array(C,np.float32); xn=(X*X).sum(1)
    for _ in range(9):
        dist=xn[:,None]+(C*C).sum(1)[None,:]-2*(X@C.T)
        lab=dist.argmin(1)
        for k in range(n):
            sel=lab==k
            if sel.any(): C[k]=(X[sel]*weights[sel,None]).sum(0)/weights[sel].sum()
    # Select a real tile for each centre so the 3D microtexture is retained.
    dist=xn[:,None]+(C*C).sum(1)[None,:]-2*(X@C.T)
    med=dist.argmin(0); chosen=uniq[med].reshape(n,8,8)
    CX=X[med]; dd=xn[:,None]+(CX*CX).sum(1)[None,:]-2*(X@CX.T)
    match=dd.argmin(1)
    err=float(np.average(dd[np.arange(len(X)),match],weights=weights)/192)
    return list(chosen),match[inv],err


def nt_text(nt,row,text,col=None):
    if col is None: col=max(0,(32-len(text))//2)
    for i,ch in enumerate(text[:32-col]): nt[row,col+i]=128+max(0,min(63,ord(ch)-32))


def bake_bg(name,img,hud=True,labels=None):
    img=np.nan_to_num(img[...,:3].astype(np.float32)).copy()
    if name=='title': img=logo(img,'STARDUST',25,35)
    if name=='manual': img=logo(img,'FLIGHT MANUAL',15,25)
    if name=='password': img=logo(img,'CONTINUE',20,28)
    if hud: img[168:]=H.panel_art(0,0,256,24)
    pal=choose_bg_palette(img); rgb=np.array([H.sms_to_rgb(v) for v in pal])
    idx=H.quantize(img,rgb,list(range(16)),dither=.34)
    cells=[idx[y*8:y*8+8,x*8:x*8+8] for y in range(24) for x in range(32)]
    art,assign,err=tile_dictionary(cells,pal,N_ART)
    tiles=ui_tiles()+art
    while len(tiles)<BG_COUNT: tiles.append(np.zeros((8,8),np.uint8))
    nt=(np.asarray(assign,dtype=np.uint16).reshape(24,32)+ART_BASE)
    if labels:
        for row,text in labels: nt_text(nt,row,text)
    # Clean embossed UI rows are not allowed to inherit random art tiles.
    if hud: nt[21:]=128
    blob=b''.join(encode_tile(t) for t in tiles)
    final=np.zeros((192,256,3),np.uint8)
    for y in range(24):
        for x in range(32): final[y*8:y*8+8,x*8:x*8+8]=(rgb[tiles[int(nt[y,x])-BG_BASE]]*255).astype(np.uint8)
    Image.fromarray(final).resize((768,576),Image.Resampling.NEAREST).save(PREV/f'screen_{name}.png')
    return bytes(pal),blob,nt.astype('<u2').tobytes(),err


def add_map_nodes(img):
    img=img.copy(); coords=[(46,66),(106,49),(171,68),(202,123),(109,124)]
    # Raised pipes linking spherical war-plan nodes.
    for (x0,y0),(x1,y1) in zip(coords,coords[1:]):
        line=Image.new('RGB',(256,192));d=ImageDraw.Draw(line)
        d.line((x0,y0+1,x1,y1+1),fill=(15,30,50),width=4)
        d.line((x0,y0,x1,y1),fill=(50,100,145),width=2)
        a=np.asarray(line,np.float32)/255; mask=a.sum(-1)>0
        img[mask,:3]=a[mask]
    tints=[(.24,.40,.7),(.45,.20,.1),(.15,.5,.22),(.5,.25,.65),(.6,.43,.1)]
    for i,((x,y),tint) in enumerate(zip(coords,tints)):
        rock,_=S.render_ball(96,96,S.Camera((0,0,4),(0,0,0),ortho=1.25,aspect=1),S.ValueNoise(16,32+i),
                           radius=1,disp=.015,freq=2.5,octaves=3,tint=tint,
                           lights=[S.Light((-.55,.6,.7),(1,1,1),1.8,spec=1.0)],ambient=(.28,.28,.34),
                           rim=.25,spec_strength=.9,texture='rock',dark=.05,albedo_var=.1)
        im=S.downsample(rock,4);rgb=S.tone_map(im[...,:3],exposure=1.6,gamma=.85);a=im[...,3:4]
        img[y-12:y+12,x-12:x+12,:3]=img[y-12:y+12,x-12:x+12,:3]*(1-a)+rgb*a
    return img


def main():
    z=np.load(ROOT/'assets/cache/sprites.npz'); sprites={k:z[k].astype(np.float32) for k in z.files}
    z=np.load(ROOT/'assets/cache/bg.npz'); bgs={k:z[k].astype(np.float32) for k in z.files}
    assert all(np.isfinite(im).all() for im in bgs.values()),'invalid background render'
    tokens=[token_image(sprites['token_00'],c) for c in ['G','H','S','*','P','E','B','X','F']]
    common=common_patterns(sprites,tokens)
    layouts={}; arenas=[]; bosses=[]
    for world in range(5):
        pat=common.copy(); off=ROCK_BASE
        for ci,tint in enumerate(TINT_ORDER):
            for size in ['small','med','big']:
                data=sprite_blob(sprite_idx(sprites[f'rock_{tint}_{size}_00'],TINT_INDICES[ci]))
                pat[off*32:off*32+len(data)]=data;off+=len(data)//32
        assert off==110
        for name,base in zip(ENEMIES[world],[ENEMY_A,ENEMY_B]):
            for f in range(2):
                data=sprite_blob(sprite_idx(sprites[f'{name}_{f:02}']))
                pat[(base+4*f)*32:(base+4*f)*32+len(data)]=data
        pat[MINE*32:(MINE+2)*32]=sprite_blob(sprite_idx(sprites['mine_00']))
        assert len(pat)==4096
        arenas.append(bytes(pat))
        pat=common.copy();off=38
        for name,nf in BOSSES[world]:
            im=sprites[f'{name}_00'];h,w=im.shape[:2]
            if name=='b1_pillar':
                # Narrow structural columns also respect the eight-per-line
                # sprite limit. This is a resampling of the shaded 3D model.
                im=np.asarray(Image.fromarray((np.clip(im,0,1)*255).astype(np.uint8)).resize((8,32),Image.Resampling.LANCZOS),np.float32)/255
                w=8;h=32
            stride=((w+7)//8)*((h+15)//16)*2
            layouts[name]={'pat':off,'w':w,'h':h,'frames':nf,'stride':stride}
            for f in range(nf):
                frame=im if name=='b1_pillar' else sprites[f'{name}_{f:02}']
                data=sprite_blob(sprite_idx(frame));assert len(data)==stride*32
                assert off+stride<=128,(name,off,stride)
                pat[off*32:(off+stride)*32]=data;off+=stride
        assert len(pat)==4096
        bosses.append(bytes(pat))

    anim=bytearray();anim_offsets={}
    def append(name,data):
        anim_offsets[name]=len(anim);anim.extend(data)
    append('player',b''.join(sprite_blob(sprite_idx(sprites[f'player_{i:02}'],[1,2,3,4,10,11,12,14,15])) for i in range(16)))
    append('shield',b''.join(sprite_blob(sprite_idx(sprites[f'shield_{i:02}'],[1,4,10,11,12])) for i in range(2)))
    append('flame',b''.join(sprite_blob(sprite_idx(sprites[f'flame_{i:02}'],[4,5,6,7,13])) for i in range(8)))
    append('tokens',b''.join(sprite_blob(sprite_idx(im)) for im in tokens))
    for ci,tint in enumerate(TINT_ORDER):
        data=bytearray()
        for f in range(4):
            for size in ['small','med','big']:
                data.extend(sprite_blob(sprite_idx(sprites[f'rock_{tint}_{size}_{f:02}'],TINT_INDICES[ci])))
        append('rocks_'+tint,bytes(data))
    assert len(anim)<=16384,len(anim)
    (OUT/'bank_17.bin').write_bytes(bytes(anim)+bytes(16384-len(anim)))

    bgs['bg_map']=add_map_nodes(bgs['bg_map'])
    mission=bgs['bg_world3'].copy()
    mission[...,:3]*=.72
    bgs['bg_mission']=mission
    specs=[(2,'title','title',common,False,[(17,'UNOFFICIAL 3D FAN REMAKE'),(19,'1 START   2 FLIGHT MANUAL'),(21,'LEFT/RIGHT: NORMAL / RELAXED'),(23,'UP: CODE   DOWN+1: BOSSES')])]
    for i in range(5): specs.append((3+i,f'world{i+1}',f'world{i+1}',arenas[i],True,None))
    specs += [(8,'map','map',common,False,[(0,'WAR PLAN'),(18,'LEFT/RIGHT SELECT  1 LAUNCH'),(20,'CLEAR 4 SECTORS TO OPEN GUARDIAN')]),
              (9,'tunnel','tunnel',arenas[1],True,None),
              (10,'mission','mission',arenas[2],True,None),
              (11,'end','end',common,False,[(2,'THE PROFESSOR IS DEFEATED'),(4,'THE GALAXY IS FREE'),(19,'1 RETURN TO TITLE'),(22,'THANK YOU FOR PLAYING')])]
    for i in range(5):specs.append((12+i,f'boss{i+1}',f'world{i+1}',bosses[i],True,None))
    manual=bgs['bg_title'].copy();manual[...,:3]*=.32;bgs['bg_manual']=manual
    passwd=bgs['bg_map'].copy();passwd[...,:3]*=.6;bgs['bg_password']=passwd
    specs += [(18,'manual','manual',common,False,None),(19,'password','password',common,False,None)]
    metadata={}
    for bank,name,bg,sp,hud,labels in specs:
        pal,tiles,nt,err=bake_bg(name,bgs['bg_'+bg],hud,labels)
        data=pal+PAL_SMS.tobytes()+bytes(sp)+tiles+nt
        assert len(data)==15904,(name,len(data))
        (OUT/f'bank_{bank:02}.bin').write_bytes(data+bytes(16384-len(data)))
        metadata[name]={'bank':bank,'patterns':320,'mse':err,'sprite_patterns':128}
        print(f'{name:10s} bank {bank:2d}, 320 BG patterns, tile error {err:.5f}',flush=True)

    # Final hardware-palette sprites for visual QA, not just floating previews.
    names=['player_00','rock_grey_big_00','rock_blue_med_00','rock_gold_big_00',
           'blade_00','bomber_00','thorn_00','b2_eye_00','b3_head_00','b4_blades_00','b5_egg_00','b5_prof_00']
    can=Image.new('RGB',(6*112,2*132),(12,14,24));d=ImageDraw.Draw(can)
    for n,key in enumerate(names):
        valid=None
        if key.startswith('rock_'): valid=TINT_INDICES[TINT_ORDER.index(key.split('_')[1])]
        idx=sprite_idx(sprites[key],valid);a=(idx>0)[...,None]
        rgb=np.where(a,PAL_RGB[idx]*255,np.array([12,14,24])).astype(np.uint8)
        im=Image.fromarray(rgb);im.thumbnail((96,96));im=im.resize((im.width*max(1,96//max(im.size)),im.height*max(1,96//max(im.size))),Image.Resampling.NEAREST)
        x=n%6*112;y=n//6*132;can.paste(im,(x+(112-im.width)//2,y));d.text((x,y+100),key.replace('_00',''),fill='white')
    can.save(PREV/'sms_sprite_sheet.png')
    # Catalogue and constants shared with the C engine.
    metadata['boss_layouts']=layouts;metadata['animation_offsets']=anim_offsets
    metadata['sprite_palette']=PAL_SMS.tolist()
    (OUT/'manifest.json').write_text(json.dumps(metadata,indent=2))
    defines=['/* Generated by tools/export_sms.py. Do not hand-edit. */','#ifndef ART_H','#define ART_H',
             '#define FONT_BASE 128','#define HP_BAR 192','#define SH_BAR 201','#define BOSS_BAR 210',
             '#define BG_OFFSET 4128','#define MAP_OFFSET 14368','#define ANIM_BANK 17',
             '#define SC_TITLE 2','#define SC_MAP 8','#define SC_TUNNEL 9','#define SC_MISSION 10',
             '#define SC_END 11','#define SC_MANUAL 18','#define SC_PASSWORD 19']
    for name,off in anim_offsets.items():defines.append(f'#define ANIM_{name.upper()} {off}')
    for name,pat in COMMON.items():defines.append(f'#define SPR_{name.upper()} {pat}')
    defines+=['#define SPR_ROCK 38','#define SPR_ENEMY_A 110','#define SPR_ENEMY_B 118','#define SPR_MINE 126']
    for name,desc in layouts.items():
        for key,v in desc.items(): defines.append(f'#define {name.upper()}_{key.upper()} {v}')
    defines.append('#endif')
    (ROOT/'src/art.h').write_text('\n'.join(defines)+'\n')
    # Arena definitions: sector count is deliberately four per world, with
    # progressive rock armour, different enemies, then one distinct guardian.
    levels=[]
    for w in range(5):
        for sector in range(4): levels.append({'world':w+1,'sector':sector+1,'initial_big_rocks':2+sector//2,
                'initial_enemies':2+min(w,2),'armour_tier':min(3,w//2+sector//2),'time_seconds':150+20*w,
                'enemies':ENEMIES[w]})
    (OUT/'levels.json').write_text(json.dumps(levels,indent=2))
    print('Exported',len(specs)+1,'resource banks; all SMS tile data validated.')

if __name__=='__main__': main()
