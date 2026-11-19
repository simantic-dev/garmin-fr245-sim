#!/usr/bin/env bash
# Fetch Garmin's own FR245 v3.10 firmware (not in this repo), then run it on pyrite and write PNG frames to out/frames/.
# Usage: ./run.sh      SIM=/path/to/sim picks a sim binary built with the MK28FN2M0VMI15 chip.
set -euo pipefail
cd "$(dirname "$0")"
SIM="${SIM:-sim}"
[ -f out/fr245.elf ] || python3 scripts/garmin_fr245_image.py out
rm -rf out/frames && mkdir -p out/frames
"$SIM" run --scenario sim/scenario.yaml 2>&1 | tee out/run.log
ls out/frames | wc -l | xargs echo "frames written to out/frames:"
python3 scripts/ble_phone.py out/ble.pcap
python3 scripts/demo_gif.py docs/screens/demo.gif
