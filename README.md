## Run Garmin Forerunner 245 firmware in a simulator

```sh
./run.sh    # downloads Garmin's v3.10 firmware, runs 80 virtual s (about 90 s wall), writes PNG frames to out/frames/
```

![boot logo, language screen, scrolled screen, back, redraw](docs/screens/contact-sheet.png)

Garmin's unmodified Forerunner 245 v3.10 firmware (NXP Kinetis K28, MK28FN2M0VMI15) running on pyrite, the Simantic
simulator. The display is rendered from the pixels the firmware clocks out of FlexIO; each frame is a PNG.

**Timeline of the scenario** (virtual time; buttons are active-low, pressed for 300 ms):

| Time | Event | Screen |
| --- | --- | --- |
| 4.82 s | boot | [Garmin logo](docs/screens/1-boot-logo-4.8s.png) |
| 12.9 s | | [language screen, "English"](docs/screens/2-language-12.9s.png) |
| 16.0 s | PTC11 | no visible change |
| 17.8 s | PTD10 | [list scrolls down](docs/screens/3-scrolled-after-PTD10.png) |
| 19.6 s | PTD1 | [scrolls back](docs/screens/4-back-after-PTD1.png) |
| 21.4 s | PTA20 | [screen redraws](docs/screens/5-redraw-after-PTA20.png) |
| 23.2 s | PTA22 | no visible change |

```mermaid
flowchart LR
  fw["MK28FN2M0VMI15<br/>FR245 v3.10 (unmodified)"]
  hub(["sensor hub"]) --- fw
  fg(["MAX17048 fuel gauge, I2C3 0x36"]) --- fw
  pmic(["MAX20303 PMIC, I2C3 0x28"]) --- fw
  btn(["5 buttons: PTC11 PTD10 PTD1 PTA20 PTA22"]) --- fw
  disp(["MIP display on FlexIO0"]) --- fw
  link(["host link, LPUART3"]) --- fw
```

All parts around the MCU are Python peers in `peers/`, wired in `sim/overlay.board`; the scenario is `sim/scenario.yaml`.

**Needs** Python 3 and a pyrite `sim` build that includes the `MK28FN2M0VMI15` chip. That chip is not in a release yet, so
point `SIM=/path/to/sim ./run.sh` at a build that has it.

**The firmware is not in this repo.** `scripts/garmin_fr245_image.py` downloads
`https://download.garmin.com/software/Forerunner245_310.gcd` from Garmin, checks its sha256
(`ffc802fd505cb62fe680dd50935654ef8177c8a0c74d20de3a6b32a4d185ff43`), unpacks the application stream and writes `out/fr245.elf`
(internal flash at 0x3000, QuadSPI code alias at 0x04617000, entry 0x31F1). `out/` is git-ignored.

Peer tests: `python3 -m pytest peers`.

## Reaching "Pair with phone?"

With the QuadSPI NOR backed by the array (pyrite branch `agent/fr245-boot-3744`), the firmware formats its 32 MiB
flash filesystem on first boot (about 63 s of virtual time, erase times from the shared NOR model), then the language
screen answers PTD10 at 75 s: [English selected](docs/screens/6-english-selected-75s.png), then
[Pair with phone? Yes / No](docs/screens/7-pair-with-phone-75s.png). The scenario runs 80 s virtual (about 90 s wall).
PTA20 (START) pressed at 70 s showed no change; which key is select is not confirmed.

## Known gaps

- The host-link reply on LPUART3 is unknown, so `garmin_link_peer.py` only logs. The firmware retries about 3 times before
  the UI appears.
- PTC11 and PTA22 change nothing visible on the language screen.
- The QuadSPI base address was fitted from pointers in the image, not read from documentation.
- The display peer's pixel framing and line packing were derived from observed waveforms and the firmware's packer, not
  from a panel datasheet; the panel is unidentified.
- Fuel gauge, PMIC and sensor hub peers are scripted register models; timing is not measured against a watch.
- No radio, GPS, heart-rate models. The flash filesystem is the shared NOR model with an erased (0xFF) array; its size (32 MiB) and timing are not the FR245 part's.
