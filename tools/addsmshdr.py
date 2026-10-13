#!/usr/bin/env python3
"""Pad a raw SMS binary and write the real Sega header at $7FF0."""
from pathlib import Path
import argparse
from build_rom import header

def main():
    ap=argparse.ArgumentParser();ap.add_argument('infile');ap.add_argument('outfile');ap.add_argument('--kbytes',type=int,default=512)
    a=ap.parse_args();sizes={32:12,64:14,128:15,256:0,512:1,1024:2,2048:3,4096:4}
    if a.kbytes not in sizes:raise SystemExit('Supported sizes: 32,64,128,256,512,1024,2048,4096 KiB')
    data=bytearray(Path(a.infile).read_bytes());size=a.kbytes*1024
    if len(data)>size:raise SystemExit('Binary exceeds selected cartridge size')
    data.extend(bytes([255])*(size-len(data)));checksum=header(data,sizes[a.kbytes]);Path(a.outfile).write_bytes(data)
    print(f'{a.outfile}: {len(data)} bytes, Sega checksum ${checksum:04x}')
if __name__=='__main__':main()
