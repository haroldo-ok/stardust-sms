# Credits and provenance

## Original inspiration

**StarDust — Bloodhouse, 1993.** This independent fan adaptation takes its rotating/inertial asteroid combat, coloured meteor armour, token ideas, five-world structure and guardian themes from the original game's documented design. It is not an official port and contains no original Amiga executable, graphics or samples.

## Music

The soundtrack is converted from the original StarDust Amiga music modules (`p4x.*`, The Player 4.x, from `Stardust.lha`) into Master System PSG register streams by `tools/convert_music.py`. No Amiga samples are stored in the cartridge: only note pitches, volumes and drum hits re-voiced for the PSG. The music remains the work of its original authors and rights holders; it is not covered by this project's MIT license.

Conversion uses libxmp (https://github.com/libxmp/libxmp) at conversion time only; it is not linked into the cartridge or the build.

Design references:

- Instructions: https://www.lemonamiga.com/doc/stardust/1535
- Hints: https://www.lemonamiga.com/doc/stardust/1534

## Implementation and artwork

- Custom Z80 startup, IM-1 interrupt and console-pause NMI handling.
- Custom C engine and assembly VDP/font/metasprite routines.
- Procedural meshes, displaced-sphere rendering, volumetric space scenes and embossed UI.
- PSG sound effects and the original menu tune; the stream player for the converted Amiga music.
- Hardware palettes, 4-bit planar tile encoding and bank packing implemented in the project.

Original project code, original generated art and documentation: MIT license, `LICENSE`. The converted music in `assets/sms/music.bin` is excluded (see Music above).

## Third-party components

### DejaVu fonts

`DejaVuSans-Bold.ttf` and `DejaVuSansMono-Bold.ttf` are included for text/logo rendering. Their Bitstream/DejaVu notices and permissions are preserved verbatim in `assets/fonts/LICENSE.txt`.

### libretro API

The API declarations in `tools/libretro.h` retain the upstream MIT license notice. This header is used by the separate QA frontend, not by the cartridge game.

### SDCC

Cartridge compiler: SDCC 4.5.0, https://sdcc.sourceforge.net/ . Runtime libraries use their upstream linking exception; see the installed SDCC library license files. No emulator code is embedded in the cartridge.

### QA emulators (not bundled)

- Genesis Plus GX: https://github.com/ekeeke/Genesis-Plus-GX
  - Tested revision: `49c584764893b0505ac7f768a754f97330fa4392`
- Gearsystem: https://github.com/drhelius/Gearsystem
  - Tested revision: `692494c8d3e322faeea204fd54f582f00d77f03a`

Both are separate tools, governed by their own upstream licenses. `tools/build_tools.sh` downloads their sources and builds the tested revisions; neither core is distributed in this source package.
