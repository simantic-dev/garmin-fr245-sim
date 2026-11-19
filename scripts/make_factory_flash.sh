#!/usr/bin/env bash
# Run the first boot (the firmware formats the 32 MiB QuadSPI NOR, ~55 s virtual) and dump the formatted
# array to out/factory_nor.bin. run.sh preloads it so later runs skip the format. Generated locally, git-ignored.
set -euo pipefail
cd "$(dirname "$0")/.."
SIM="${SIM:-sim}"
[ -f out/fr245.elf ] || python3 scripts/garmin_fr245_image.py out
"$SIM" MK28FN2M0VMI15 run --elf out/fr245.elf --board sim/overlay.board --timeout 70 \
  --dump-mem out/factory_nor.bin@0x68000000+0x2000000 >out/factory_flash.log 2>&1 || true
[ "$(stat -c %s out/factory_nor.bin 2>/dev/null || stat -f %z out/factory_nor.bin)" = 33554432 ]
echo "wrote out/factory_nor.bin"
