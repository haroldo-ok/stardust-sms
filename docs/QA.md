# Release QA — Stardust SMS

Date: **2026-10-12**. Status: **PASS — 139 automated assertions**.

## Exact cartridge

- File: `Stardust_SMS.sms`
- Size: **524,288 bytes (512 KiB)**; allowance: 4 MiB.
- Fixed code/constants: **23,026 / 32,752 bytes**.
- Global work RAM: **1,362 bytes**, plus stack, within 8 KiB.
- Standard Sega mapper; SMS Export header; checksum **`$D7EE`**.
- SHA-256: `bd5226d5cd84059659917781d853cdbd9af527dac9d519470f3a97dfac33c533`.
- Music: 13 PSG streams converted from the Amiga modules, banks 20–23 (`assets/sms/music.json`).

## Completion evidence

| Core / scenario | Result |
|---|---|
| Genesis Plus GX, NTSC, full **Normal** campaign | Ending reached at emulator frame **45,180**. All 20 sectors, all five guardians, four tunnels, and both gravity/fuel missions covered. The pilot retries after game-over; this is not a deathless/first-attempt run. |
| Genesis Plus GX, guardian practice | All five guardians and final professor defeated; ending at **8,040**. |
| Gearsystem, independent guardian practice | All five guardians and final professor defeated; ending at **8,040**. Soundtrack follows the game state in every steady sample. |
| Genesis Plus GX, PAL | 1,800-frame boot/map/gameplay smoke; 256 × 192 video, 49.70 Hz core timing and advancing game logic. |
| Gearsystem, independent NTSC gameplay | Boot, controls, gun token, combat, score, rendering and RAM advancement verified. |

**Campaign and guardian pilots use controller input only.** No RAM pokes, save-state injections or cartridge-side test hooks are used for completion runs. Ordinary controls include movement, fire, weapon selection, bombs and shields. Guardian practice is the explicit player-accessible title option; the campaign is separate and `practice=0`.

## Directed automated checks

- Valid reset/IRQ/NMI vectors, Sega signature, size/region and whole-cartridge checksum.
- All 18 resource banks match the packed ROM; 6-bit CRAM values; all background name-table indices stay within the VRAM budget.
- Native 256 × 192 nonblank graphics and no more than 32 simultaneous colours.
- SMS1/315-5124 address-mask quirks: **R5 = `$7F`, R6 = `$03`**. State inspection verifies the actual VDP registers, not just source constants.
- Gameplay pattern/SAT transfers start within VBlank and finish before active display in sampled gameplay. Late frames wait for a fresh blank instead of uploading into active display.
- Ship movement, automatic firing, actual enemies, meteor splitting/combat, score and real-input G pickup.
- Blaster/bouncer/missile/flamer selection through Down + Button 2.
- Maximum-speed E-upgraded projectiles do not overflow signed velocity and fly backwards.
- Console-pause NMI freezes simulation while interrupts continue; a second pause resumes play.
- All nine token outcomes: G, heart, S, smart bomb, points, E, mega bomb, X and F.
- Valid campaign-code restore; invalid code rejection.
- Real lethal collision reaches game-over.
- A pending respawn is not lost when a tunnel hands off to a bonus mission.
- 44.1 kHz stereo frontend PCM capture contains nonzero PSG music and effects.
- Music banks 20–23 match `assets/sms/music.bin`; the title plays the title theme and the first sector the world-1 theme; NTSC and PAL are detected for the music tempo.
- In both completion runs, every steady one-second trace sample has the track `select_music()` must pick for its mode, world and guardian phase (samples adjacent to a scene change are skipped, as the scene loader runs before the track switch). The campaign hears all 13 tracks; guardian practice hears all four guardian themes.
- Conversion check (`tools/convert_music.py`): every stream is decoded by a model of the Z80 player and must reproduce the converted PSG state frame for frame, through one loop.
- Development checks, not part of `make test`: Genesis Plus GX audio of the title matches the offline PSG render (chroma similarity 0.98 over 25 s, no tempo drift on NTSC); a PSG write log shows square channel 2 restored by the music after a shot effect; audio is silent while paused and resumes afterwards. No human listening review is claimed.

**Fixture distinction:** individual token, decoder, collision, overflow and transition tests use documented emulator-side RAM fixtures to isolate an edge case. The cartridge contains no QA shortcuts, and these fixtures are not used to claim campaign completion.

## Final visual review

`Stardust_SMS_Screenshots.png` / `docs/screenshots.png` contains actual captures of the title, map, combat and all five guardians (including both final-boss forms). `docs/warp_tunnel.png` shows an actual tunnel. These are hardware-palette renders, not floating-point asset previews. Artwork is made from original procedural 3D renders and embossed UI, then converted into SMS patterns.

The SMS1 SAT/pattern masking issue discovered during visual review is fixed in this exact cartridge. Older development screenshots are not release evidence.

## Reproduce

```sh
bash tools/build_tools.sh
make test
```

`tools/test_rom.py` performs the 139 automated assertions and writes `tests/QA_report.json`. Additional independent guardian practice:

```sh
build/smsrun /tmp/tools/gearsystem/platforms/libretro/gearsystem_libretro.so \
  Stardust_SMS.sms --frames 20000 --pilot bosses --symbols tests/symbols.noi \
  --trace --ram-at 19000 --outdir tests/gearsystem_bosses
```

Pinned emulator revisions are listed in `docs/CREDITS.md`. Full traces/logs for the release completion runs are included in the source archive.

## Limits / not claimed

- **No physical SMS or flash-cartridge test has been performed.**
- Heavy scenes can run below the 30 Hz NTSC / 25 Hz PAL target; the VBlank guard prioritizes correct uploads rather than a false locked-FPS claim.
- Real eight-sprites-per-scanline limits can cause overlap flicker. The compositor rotates actor ordering and prioritizes the player and guardian.
- This is an independent SMS adaptation, not an exact Amiga binary/asset port. The music is a four-channel PSG rearrangement of the Amiga modules: drums are re-voiced, bass is transposed up by octaves into the PSG range, and when four tonal voices sound at once the quietest is dropped.

## Source-archive rebuild verification

The delivered source archive was extracted to a fresh directory and rebuilt with SDCC 4.5.0. The rebuilt cartridge is **byte-for-byte identical** to the delivered ROM, with the SHA-256 above. This check used the bundled baked artwork and music banks and did not depend on files outside the archive.
