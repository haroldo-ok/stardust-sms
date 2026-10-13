#!/usr/bin/env bash
# Rebuild the independently licensed emulator cores used for QA.
# Build dependencies: git, make, gcc, g++. SDCC is needed for the cartridge.
set -euo pipefail
DEST="${SMS_TOOLS_DIR:-/tmp/tools}"
mkdir -p "$DEST"
if [ ! -d "$DEST/gpgx/.git" ]; then
  git clone https://github.com/ekeeke/Genesis-Plus-GX.git "$DEST/gpgx"
fi
git -C "$DEST/gpgx" checkout 49c584764893b0505ac7f768a754f97330fa4392
make -C "$DEST/gpgx" -f Makefile.libretro -j2
if [ ! -d "$DEST/gearsystem/.git" ]; then
  git clone https://github.com/drhelius/Gearsystem.git "$DEST/gearsystem"
fi
git -C "$DEST/gearsystem" checkout 692494c8d3e322faeea204fd54f582f00d77f03a
make -C "$DEST/gearsystem/platforms/libretro" -j2
printf '\nGenesis Plus GX: %s\nGearsystem: %s\n' "$DEST/gpgx/genesis_plus_gx_libretro.so" "$DEST/gearsystem/platforms/libretro/gearsystem_libretro.so"
printf 'Use GENPLUSGX_CORE and GEARSYSTEM_CORE if installing outside /tmp/tools.\n'
