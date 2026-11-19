#!/usr/bin/env bash
# Fetch Garmin's own FR245 v3.10 firmware (not in this repo), then run it on pyrite and write PNG frames to out/frames/.
# Usage: ./run.sh [--first-boot]   (default: preload out/factory_nor.bin, made once by scripts/make_factory_flash.sh;
#        --first-boot runs the ~55 s flash format instead)
# Usage: IRQ=0 ./run.sh drops the IRQ panel.   SIM=/path/to/sim picks a sim binary built with the MK28FN2M0VMI15 chip.
set -euo pipefail
cd "$(dirname "$0")"
SIM="${SIM:-sim}"
[ -f out/fr245.elf ] || python3 scripts/garmin_fr245_image.py out
SCEN=sim/scenario.yaml
if [ "${1:-}" = "--first-boot" ]; then SCEN=sim/scenario_firstboot.yaml
else [ -f out/factory_nor.bin ] || scripts/make_factory_flash.sh; fi
rm -rf out/frames && mkdir -p out/frames
# QuadSPI0 SFAR and IPCR are traced; qspi_summary.py reduces them to one line per virtual second, so run.log stays small
# IRQ=0 skips the interrupt panel data. Otherwise --trace-interrupts is aggregated live by irq_bins.py (100 ms bins) into
# out/irq_rates.json, a temporary input for demo_gif.py (git-ignored); the raw trace (~1 GB) is never written.
IRQ_FLAGS=(); IRQ_PIPE=cat
if [ "${IRQ:-1}" = 1 ]; then IRQ_FLAGS=(--trace-interrupts); IRQ_PIPE="python3 scripts/irq_bins.py out/irq_rates.json"; fi
"$SIM" run --scenario "$SCEN" --trace-memory 0x400da100:4 --trace-memory 0x400da008:4 ${IRQ_FLAGS[@]+"${IRQ_FLAGS[@]}"} 2>&1 | $IRQ_PIPE | python3 scripts/qspi_summary.py | tee out/run.log
ls out/frames | wc -l | xargs echo "frames written to out/frames:"
python3 scripts/ble_phone.py out/ble.pcap
rm -f out/irq_rates.json.tmp; python3 scripts/demo_gif.py docs/screens/demo.gif mp4   # also docs/screens/demo.mp4 and demo_vertical.mp4 (needs ffmpeg)
python3 scripts/watch_render.py                          # round per-screen PNGs, hero.png, hero.gif
