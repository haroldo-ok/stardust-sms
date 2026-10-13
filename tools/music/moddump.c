/* Dump per-tick channel state of a module via libxmp, plus raw samples. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <xmp.h>
int main(int argc,char**argv){
    if(argc<3){fprintf(stderr,"usage: moddump mod outdir [wav]\n");return 1;}
    xmp_context c=xmp_create_context();
    if(xmp_load_module(c,argv[1])<0){fprintf(stderr,"load failed %s\n",argv[1]);return 2;}
    struct xmp_module_info mi; xmp_get_module_info(c,&mi);
    struct xmp_module *m=mi.mod;
    if(argc>4){char*p=argv[4];while(*p){int k=strtol(p,&p,10);if(k>=0&&k<m->smp&&m->xxs[k].data)memset(m->xxs[k].data,0,m->xxs[k].len*((m->xxs[k].flg&1)?2:1));if(*p==',')p++;else break;}}
    char path[1024]; snprintf(path,sizeof path,"%s/info.txt",argv[2]);
    FILE*f=fopen(path,"w");
    fprintf(f,"name %s\ntype %s\nchn %d\npat %d\nlen %d\nrst %d\nspd %d\nbpm %d\nins %d\nsmp %d\n",m->name,m->type,m->chn,m->pat,m->len,m->rst,m->spd,m->bpm,m->ins,m->smp);
    for(int i=0;i<m->len;i++)fprintf(f,"%d ",m->xxo[i]);fprintf(f,"\n");
    for(int i=0;i<m->smp;i++){
        struct xmp_sample*s=&m->xxs[i];
        fprintf(f,"sample %d len %d lps %d lpe %d flg %d name %s\n",i,s->len,s->lps,s->lpe,s->flg,s->name);
        char sp[1024];snprintf(sp,sizeof sp,"%s/s%02d.raw",argv[2],i);
        FILE*g=fopen(sp,"wb"); if(s->data&&s->len)fwrite(s->data,(s->flg&1)?2:1,s->len,g); fclose(g);
    }
    for(int i=0;i<m->ins;i++){
        struct xmp_instrument*in=&m->xxi[i];
        fprintf(f,"ins %d nsm %d vol %d",i,in->nsm,in->vol);
        if(in->nsm) fprintf(f," sid %d vol %d fin %d xpo %d",in->sub[0].sid,in->sub[0].vol,in->sub[0].fin,in->sub[0].xpo);
        fprintf(f," name %s\n",in->name);
    }
    fclose(f);
    snprintf(path,sizeof path,"%s/ticks.txt",argv[2]);
    f=fopen(path,"w");
    FILE*wav=argc>3?fopen(argv[3],"wb"):NULL;
    xmp_start_player(c,44100,XMP_FORMAT_MONO);
    xmp_set_player(c,XMP_PLAYER_INTERP,XMP_INTERP_LINEAR);
    struct xmp_frame_info fi; long long t=0; long nsamp=0;
    if(wav){char hdr[44]={0};fwrite(hdr,1,44,wav);}
    int prevframe=-1;
    while(xmp_play_frame(c)==0){
        xmp_get_frame_info(c,&fi);
        if(fi.loop_count>0)break;
        if(t>15LL*60*1000000)break;
        fprintf(f,"T %lld %d %d %d %d %d %d %d",t,fi.pos,fi.pattern,fi.row,fi.frame,fi.speed,fi.bpm,fi.volume);
        for(int ch=0;ch<m->chn;ch++){
            struct xmp_channel_info*ci=&fi.channel_info[ch];
            fprintf(f," | %u %u %d %d %d %d %d %d %d %d %d",ci->period,ci->position,ci->note,ci->instrument,ci->sample,ci->volume,
              ci->event.note,ci->event.ins,ci->event.vol,ci->event.fxt,ci->event.fxp);
        }
        fprintf(f,"\n");
        if(wav){fwrite(fi.buffer,1,fi.buffer_size,wav);nsamp+=fi.buffer_size/2;}
        t+=fi.frame_time;
    }
    xmp_get_frame_info(c,&fi);
    fprintf(f,"END %lld %d %d %d\n",t,fi.pos,fi.row,fi.loop_count);
    fclose(f);
    if(wav){
        int sr=44100;unsigned int ds=nsamp*2,rs=36+ds;unsigned char h[44];
        memcpy(h,"RIFF",4);memcpy(h+4,&rs,4);memcpy(h+8,"WAVEfmt ",8);unsigned int v=16;memcpy(h+16,&v,4);
        unsigned short s=1;memcpy(h+20,&s,2);s=1;memcpy(h+22,&s,2);memcpy(h+24,&sr,4);v=sr*2;memcpy(h+28,&v,4);s=2;memcpy(h+32,&s,2);s=16;memcpy(h+34,&s,2);
        memcpy(h+36,"data",4);memcpy(h+40,&ds,4);fseek(wav,0,SEEK_SET);fwrite(h,1,44,wav);fclose(wav);
    }
    xmp_end_player(c);xmp_release_module(c);xmp_free_context(c);
    return 0;
}
