.PHONY: all art render music test clean
all:
	python3 tools/build_rom.py
art:
	OPENBLAS_NUM_THREADS=1 python3 tools/build_rom.py --art
render:
	OPENBLAS_NUM_THREADS=1 python3 tools/build_rom.py --render
# Re-convert the Amiga modules: make music AMIGA=/path/to/Stardust (needs libxmp-dev)
music:
	python3 tools/convert_music.py $(AMIGA)
	python3 tools/build_rom.py
test: all
	python3 tools/test_rom.py
clean:
	rm -rf build
