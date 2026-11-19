## Run Garmin Forerunner 245 firmware in a simulator

![Garmin FR245 boot and use, with the firmware's UART traffic and BLE packets](docs/screens/demo.gif)

Stock Garmin firmware, unmodified, booted from a formatted ("factory") flash. Left: the display pixels the firmware clocks out, with the pressed button lit. Right: the firmware's real traffic on the same simulated clock: I2C writes to the MAX17048 fuel gauge and MAX20303 PMIC, the sensor hub SPI messages (summarised, e.g. `hub>K28 accel batch 25 samples z=+1.00 g`), the radio UART, the GPS UART handshake, BLE adverts on the simulated air (one row per second) and the button presses. GPS is parked (see below). Dead time is skipped; the clock shows the real simulated time. A person's pace is scripted in `sim/overlay.board` (`btn`: one press every 2.5 s). `./run.sh` regenerates it (`scripts/demo_gif.py`).

Built with pyrite commit `5f59b385874894cb237ff0fc13b0569dd0f3a9c3` (core clock 120 MHz).

```sh
./run.sh    # downloads Garmin's v3.10 firmware, runs 96 virtual s (about 80 s wall, Apple M5), writes PNG frames to out/frames/
```

![the watch face the setup wizard ends on](docs/screens/hero.png)

Garmin's unmodified Forerunner 245 v3.10 firmware (NXP Kinetis K28, MK28FN2M0VMI15) running on pyrite, the Simantic
simulator. The display is rendered from the pixels the firmware clocks out of FlexIO; each frame is a PNG.

**Timeline of the scenario** (virtual time, warm boot from the factory flash; buttons are active-low, 300 ms; one press every 2.5 s):

| Time | Event | Screen |
| --- | --- | --- |
| 2.75 s | boot | [Garmin logo](docs/screens/01-boot-logo-3s.png) |
| 5.9 s | | [language screen](docs/screens/02-language-6s.png) |
| 7.5 s | PTD10 (select English) | [Pair with phone? Yes / No](docs/screens/03-pair-with-phone-10s.png); BLE advertising starts |
| 10.0 s | PTD10 (Yes) | [Download Garmin Connect Mobile](docs/screens/04-download-garmin-connect-mobile-12s.png) |
| 13.0 s | PTD1 (back) | [Pair with phone? again](docs/screens/05-pair-with-phone-back-14s.png) |
| 16.0 s | PTA20 (next) | [No highlighted](docs/screens/06-pair-no-highlighted-17s.png) |
| 18.5 s | PTD10 (No) | [Distance: Miles](docs/screens/07-distance-units-20s.png) |
| 21.0 to 33.5 s | PTD10 | [Time Format](docs/screens/08-time-format-23s.png), [Gender](docs/screens/09-gender-26s.png), [Birth Year](docs/screens/10-birth-year-30s.png) |
| 36.0 to 46.0 s | PTD10 | [Height](docs/screens/11-height-37s.png), [Weight](docs/screens/12-weight-42s.png) |
| 48.8 s | | [Set Time: Use GPS / Manual](docs/screens/13-set-time-use-gps-50s.png) |
| 51.0 s | PTA20 | [Manual highlighted](docs/screens/14-set-time-manual-53s.png) |
| 53.5 to 71.0 s | PTD10 | [Set Hours](docs/screens/15-set-hours-55s.png), [Minutes](docs/screens/16-set-minutes-58s.png), AM/PM, [Year](docs/screens/17-set-year-67s.png), [Month](docs/screens/18-set-month-73s.png) |
| 73.5 to 78.5 s | PTD10 | [Day](docs/screens/19-set-day-75s.png) |
| 78.8 s | | [watch face](docs/screens/20-watch-face-80s.png) (clock, 0.0 mi) |
| 82.0 s | PTD1 | no visible change |
| 84.5 s | PTD10 | [Run glance](docs/screens/21-run-glance-86s.png) (GPS red: no fix, parked) |
| 87.0 s | PTD1 | back to the watch face |
| 89.5 s | PTD10 | Run glance again |
| 92.0 s | PTA22 | Tip bubble "Hold for activity settings, training, and more." |

The numeric fields (birth year 1978, height 5'10", weight 170, time 1:00 AM, 1 Jan 2019) are the firmware's defaults, accepted with PTD10. Which button is which is a guess from behaviour: PTD10 selects and moves on, PTD1 goes back, PTA20 moves the highlight down, PTA22 is unconfirmed.

**Boot against a real watch**

| | Real watch ([video](https://www.youtube.com/shorts/SEK3FTuwlyA), approximate) | Sim, warm boot (factory flash) | Sim, `--first-boot` |
| --- | --- | --- | --- |
| Logo | about instant | 2.75 s | 54.0 s |
| Usable (first screen that takes buttons) | about 15 s to the watch face | 5.9 s (language screen) | 57.2 s |
| Watch face | about 15 s | 78.8 s, after the scripted setup wizard | not run that far |

The sim's watch face time is the end of a 70 s scripted setup wizard, so it is not comparable with the video; the language screen at 5.9 s is the comparable number. The video figures are read off the video by hand, not measured by us.

Why the logo is not instant: about 1 s of the 2.75 s is the firmware waiting for the RTC oscillator. Measured with `--trace-memory 0x4003d000:32`: RTC_CR is written 0x500 (OSCE and the 16 pF load capacitor set) at 0.027 s (pc 0xC43E0), the next RTC access is at 1.027 s (pc 0xC43F2: read SR, then RTC register writes), and the MAX17048/MAX20303 init starts at 1.128 s. Presumably a cold part needs this time for the 32.768 kHz crystal to start (not checked against the reference manual); the sim keeps the wait because the firmware requests it. The rest is the firmware's own init up to the first draw.

`./run.sh --first-boot` skips the preloaded flash: the firmware finds no filesystem and formats the 32 MiB QuadSPI NOR (erase and program, 1 s to 54 s of virtual time, 54 one-second QSPI lines in the log), then draws the logo at 54.0 s and the language screen at 57.2 s. `scripts/make_factory_flash.sh` runs that once and dumps the array to `out/factory_nor.bin`, which the default run preloads. The button script in `sim/overlay.board` is timed for the warm boot, so on a first boot its first presses land while the flash is still formatting.

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

## Setup wizard and the sensor hub

The wizard runs end to end on the stock firmware: language, Pair with phone (Yes shows "Download Garmin Connect Mobile", then "Go to mobile app to add device" after about 8 s; PTD1 goes back), units, time format, gender, birth year, height, weight, Set Time. On Set Time, Manual gives Set Hours, Minutes, AM/PM, Year, Month, Day and then the watch face. Use GPS would wait for a fix forever (GPS is parked).

The sensor hub (`peers/spi/garmin_sensor_hub_spi.py`) is accepted at 2.23 s (the K28's hello, answered with hub id 0x0100 and a version string). The K28 then configures the accelerometer (3.15 s: 25 Hz, 1 s batches, 8 g range), and a batch of 25 samples follows every second from 4.15 s. The samples are a stand-in (flat wrist, +1 g on Z, small noise).

## Bluetooth (advertising goes over the simulated air)

The radio is a CYW20719 on LPUART0 (reset PTA26). With `cyw20719_wiced.py` the firmware (v3.10) completes BLE init: register
app, 0x42, nine 0x37 add-service, 0x16 name "Forerunner 245", 0x12, 0x14, 0x08, then the GATT table build from the 14-entry
table in the image (0x29 add service, 0x2b add characteristic). Replies need a non-zero u16 handle at event bytes [9..10], or
the table builder sends nothing more. After that the BLE manager idles waiting for a connection (its 1 Hz routine sees
connection handle 0xffff).

The firmware sends no "set advertising data" or "enable advertising" command. Advertising is one 400-byte configuration
command (opcode byte 0x08, built at flat address 0x2233c0; mode 0 = off, mode 1 = on) that the radio turns into advertising.
Mode 1 carries flags 0x06, a 16-bit service list with 0xFE1F (Garmin) and manufacturer data (company 0x0087, then
07 00 0c 04 01 and a 4-byte unit id, ff ff ff ff here); the name comes from the earlier 0x16 command. In this run mode 0 is sent at
5.76 s and mode 1 at 7.53 s, and no mode 0 follows (the previous first-boot run saw 60.5, 63.5 and 80.0 s).

### Over the air to a simulated phone

`scripts/ble_phone.py out/ble.pcap` is the phone. The scenario's BLE medium joins the radio (`dut.cyw`) to a second
endpoint (`dut.phone`, a listening radio) and writes every advertisement to `out/ble.pcap` (BLE LL with PHDR, opens in
Wireshark); the script decodes it:

```
[   7.5255s] ch37 ADV_IND  00:00:00:00:00:00  flags=0x06  uuids=0xFE1F  company=0x0087 mfg=0c0401ffffffff  name="Forerunner" (shortened)
   ... until 95.9459s: 4083 advertisements
```

Advertising runs from 7.53 s to the end of the run, through the Pair with phone, Download Garmin Connect Mobile and Go to mobile app screens and the rest of the wizard (the watch never connects).

Real firmware: the unmodified v3.10 image builds and sends the 0x16 name and the 0x08 config. The peer decodes them
(offsets from the builder at 0x2233c0), so the on/off times (off 5.76 s, on 7.53 s) are the firmware's own.
The peer now speaks when the DUT enables the LPUART0 receiver (about 3.06 s; the sim passes `CTRL[RE]` to the peer as
`on_rx_enable`), once: 0x1b4a then 0x24. No timer, and the firmware needed no repeat.

Stand-ins:

- The CYW20719's WICED protocol is not implemented (see the peer's header); handles, app id and the 0x24 body are guesses.
- The phone is a passive receiver plus a pcap decoder, not a scanner: it never sends SCAN_REQ, so the full name
  "Forerunner 245" (in the scan response, from the 0x16 command) is never requested. flags, the UUID list and
  manufacturer data leave 13 of the 31 AdvData bytes, so the ADV_IND carries "Forerunner" as a shortened name.
- The advertising address is all zeros (the radio's BD address is not known) and the interval is the link layer's default.
- The unit id in the manufacturer data is the firmware's ff ff ff ff.

Open: a scanning/connecting central, and whether the Initializing screen leaves.

## What is independently verified

| Claim | Source | Result |
| --- | --- | --- |
| Company ID 0x0087 = Garmin International | Bluetooth SIG `company_identifiers.yaml` | match |
| UUID 0xFE1F = Garmin International | Bluetooth SIG `member_uuids.yaml` | match |
| K28, CYW20719 and MAX20303 chips | [iFixit FR245 Music teardown](https://www.ifixit.com/Teardown/Garmin+Forerunner+245+Music+Teardown/150396) | match, Music variant |
| LPUART3 framing: DLE / id / size / data / checksum / DLE ETX, two's-complement checksum | [pygarmin physical protocol](https://pygarmin.readthedocs.io/en/stable/physical_protocol.html) | framing matches, packet meaning unknown |
| GATT UUIDs the firmware registers (below) | [Gadgetbridge Garmin protocol](https://www.gadgetbridge.org/internals/specifics/garmin-protocol) | match, see below |
| Adv byte layout, timing, GATT handles, first-boot UI | simulation only | not verified against a watch |

### Service and characteristic UUIDs, firmware vs Gadgetbridge

From one run's radio log (K28 to CYW commands 0x37 add service, 0x29 add GATT service, 0x2b add characteristic). The 0x37 commands carry the full 16 bytes (little endian). 0x29 and 0x2b carry a 16-bit id plus a base index; the base `6a4e____-667b-11e3-949a-0800200c9a66` is inferred from the 0x37 entry `6a4e3e10-...`, which uses the same base, so for those the 16-bit id is what was compared.

| UUID registered by the firmware | Gadgetbridge list | Result |
| --- | --- | --- |
| 6a4e2800-667b-11e3-949a-0800200c9a66 (service) | 6a4e2800 | match |
| 6a4e8022-667b-11e3-949a-0800200c9a66 (service) | 6a4e8022 | match |
| chars 6a4e2803, 2810, 2820, 2811, 2821, 2812, 2822 (all under service 2800) | same seven | match (7 of 7) |
| chars 6a4e4c80, 6a4ecd28 | same two | match |
| service 6a4e2500 with chars 2501, 2502, 2503, 2505 | not listed | in firmware only |
| 6a4e3e10-667b-11e3-949a-0800200c9a66 (0x37) | not listed | in firmware only |
| eight 0x37 UUIDs on other bases: 7905f431-b5ce-4e99-a40f-4b1e122d00d0, 9fbf120d-6301-42d9-8c58-25e699a21dbd, 69d1d8f3-45e1-49a8-9821-9bbdfdaad9d9, 22eac6e9-24d6-4bb5-be44-b36ace7c7bfb, 89d3502b-0f36-433a-8ef4-c502ad55f8dc, 9b3c81d8-57b1-4a8a-b8df-0e56f7ca51c2, 2f7cabce-808d-411f-9a0c-bb92ba96c102, c6b2f38c-23ab-46d8-a6ab-a3a870bbd5d7 | not Garmin's; these look like Apple's ANCS and AMS service and characteristic UUIDs (recalled from Apple's public documentation, not re-checked here) | not in Gadgetbridge's Garmin list, unverified |

No mismatches: every UUID on Gadgetbridge's list is registered by the firmware.

### How to check on a real watch

Put a Forerunner 245 (Music) in pairing mode and scan with nRF Connect. The advertisement should show flags 0x06, the 16-bit service 0xFE1F, manufacturer data with company 0x0087 and a name starting "Forerunner". Compare each field with the first packets in `docs/ble.pcap` (open it in Wireshark, or `python3 scripts/ble_phone.py docs/ble.pcap`). Fields that differ (address, interval, unit id, shortened name) are simulation stand-ins listed under Stand-ins above.

## Known gaps

- The host-link reply on LPUART3 is unknown, so `garmin_link_peer.py` only logs. The firmware retries about 3 times before
  the UI appears.
- PTC11 and PTA22 change nothing visible on the language screen.
- The QuadSPI base address was fitted from pointers in the image, not read from documentation.
- The display peer's pixel framing and line packing were derived from observed waveforms and the firmware's packer, not
  from a panel datasheet; the panel is unidentified.
- No heart-rate model.
- The flash filesystem is the shared NOR model (32 MiB, shared erase and program times, not the FR245 part's).

## What is real and what is a stand-in

| Part | Status |
| --- | --- |
| Garmin FR245 v3.10 firmware, K28 core, clocks (120 MHz), QuadSPI, FlexIO, LPUARTs, SPI, I2C | the real image on the pyrite model |
| Display | pixels decoded from the FlexIO waveform the firmware clocks out; the panel itself is not modelled |
| Sensor hub | stand-in Python peer: protocol read off the firmware, timings are guesses |
| Accelerometer | stand-in: 25 Hz, flat wrist, +1 g on Z with small noise, via the hub |
| MAX17048 fuel gauge | stand-in; the firmware only writes it (never reads VCELL or SOC) in these runs |
| MAX20303 PMIC | stand-in register model: 4 reads at init, writes after |
| GPS (Sony CXD5603) | parked by decision: the handshake is answered, no fix is fed; the firmware's GPS start is gated on `CPE.BIN` (see GPS below) |
| BLE radio (CYW20719) | stand-in: WICED protocol not implemented; adverts are real firmware output over a simulated air, the phone is a passive receiver |
| Buttons | scripted GPIO, which button is which is a guess |

## GPS (LPUART3, Sony CXD5603): decoded so far

Peer: `peers/uart/sony_cxd5603_gnss.py`. Read off the firmware (RX parser 0xAC874, command queue 0xAC3D4, ACK check 0xACA58), not invented.

- Frame: `10 id len payload cksum 10 03`, DLE doubled in the body. Id 0x7b wraps `u32 data_len | u16 inner_id | data`. Inner 0xBD5 carries `u16 sub | u16 0 | u32 size | data`.
- The queue sends a message, waits 3000 ms for the ACK, resends once, then moves on (the 3.0 s spacing).
- ACK = 0xBD5 sub 8, data `u16 inst_id | u16 ack_sub | u32 data_size | u32 status`. The firmware compares inst_id with the sent id, ack_sub with 0xFFFF (0x0A and 0xBD5: first u16 of the sent data) and data_size with the sent data length. Status is only printed.
- Sent and ACKed: 0x2F `00`, 0xBBD `01000000`, 0x0A `6c00`. With these ACKs the queue stops waiting 3 s per message; the next requests follow within milliseconds (0xBD5 sub 9, 0xF9, 0x0A `ff01`).
- RX 0xBBC (u32) stores the value the 0xBBD "set" is compared against (0xAE85C, read by 0xAE6A8); 0xBBD is sent only when it differs.
- Sub 1 solved: the firmware sends the 32-byte config with bit 0 set in words 2, 3, 4 (12|1, 160|1, 4|1). 0xAE8D8 memcmps the reply with its own copy at 0x2002576c = {115200, 0x201, 12, 160, 4, 100, 0, 0x20001} (found by probing the memcmp result at 0xAE90E). The peer answers with the sent config, those flags cleared (MODELED SIMPLIFICATION: which words carry the flag). A match calls 0xAE880(1), which starts the GPS (0xAB464) and the queue advances at once.
- TX 0x30 `00080700` = baud 460800; the chip answers id 0x31 with the same u32 (0xAF87C). The firmware then sends id 0x83 (same u32) and polls 0x0A `3a00` every 0.7 s; an ACK of that with status 1 reaches 0xAF87C(0x3A) (0xACB52-0xACB9A) and ends the poll. The peer does both.
- 0x2F `xx` is the firmware's own GPS-task state (0 init, 10 and 2 = reset, 20 = running; 0xAE6F4, handler 0xAB74-0xAC42). After the 0x3A ack the firmware requests state 10 and resets 0.22 s later, then repeats the init every 11 s; it never reaches state 20, so no GPS-state-machine TX (BD5 sub 0x17, 0x1E, 0x14, 0x1D; 0xAAC3C) is sent. Cause not found yet.
- RX BD5 subs 19 and 26 (0xAD014) are a 32-byte header plus 84-byte chunks (36 u16 each) into a 1024-u16 buffer, probably assistance data; 0x7D/0x7E are a chunked transport (0xABEAC); neither is the position stream.
- Setup wizard (PTD10 select, PTA20 next): language, Pair with phone, units, time format, gender, birth year, height, weight, then "Set Time: Use GPS / Manual". Use GPS shows "Wait for GPS" (a red arc) and the hint "GPS signal is stronger outside"; it waits for a fix. Nothing is fed yet, so it waits forever. Firmware strings name the inputs: "Send initial position to Sony: lat, lon", "inject_time: date, time", "inject_phone_position", Sony CEP files (0xAEE8C-0xAEFFC, 0xAB544).
- Product data: plain frame id 0xFF (Garmin Pid_Product_Data), `u16 product_id | u16 sw_version | NUL-terminated name`, reaches 0xAA564 through the HAL queue (0xA5748 -> 0xA6B94 -> 0xA687C) and stores sw_version x 100 at 0x200253b8. The peer sends it on every 0xF9 (MODELED SIMPLIFICATION: id 5603, version 402, name `CXD5603GF` are not read from a chip). Measured with `--trace-memory 0x200253b8:4`: 0x9d08 written by pc 0xAA58C at 4.87 s. The 0xCCD7A poll then ends at once (one read at 5.72 s) instead of after 9.999 s, so the mode-10 request moves from 10.7 s to 5.74 s. That is all it changes: the 11 s reset loop is not caused by the version.
- Reset loop cause: id 0x23 is NOT a wire message. 0xACE58(0x23, mode 1) is a loopback: mode 1 hands the message to the local HAL dispatcher 0xA5758, whose entry 0x23 (0xA57A6) posts event 0x29 to the RTOS queue 0x2002519c (0xA8F30). It is dispatched at 13.07 s to 0x17EC14 (jump table at 0x17EC24: 0x29 is the "start GPS" handler 0x17EC64; 0x21/0x22 clear and 0x2B sets the wanted flag 0x2002AE32). That handler returns without calling HAL start (0xA46C4 -> vtable 0xA43F1 -> 0xAB498, which sets state 0x20025418 to 7 then 8) because 0x10ACC0 returns 0: it is a file-exists check on `0:/GARMIN/REMOTESW/CPE.BIN` (the Sony CEP assistance file, string at 0x17F15C), and 0x17EBB8 then compares its validity date with the clock. The same gate guards the other start path (0x17ED30-0x17EDAE). The factory flash has no such file. Nothing the UART peer sends can change this, so the queue is not blocked: no earlier message is pending (state 0x20025618 returns to 0 after each ACK; measured with `--trace-memory 0x20025610:20`).
- Watchdog: 0xAEE4C is a timer callback. It calls 0xAB41C (true when state 0x20025418 is in 5..13) and logs "Watchdog Expired" and posts reset event 0x10000 when that is FALSE. The state stays 0/1 because HAL start is never called, so the chip is reset and re-initialised every 11 s (0x2F, 0xBBD, 0x0A, BD5 sub 9, 0xF9, sub 1, 0x30, 0x83, 0x0A 3a00). Open: the FAT16 volume (BPB at NOR offset 0xB80200, "GARMIN", 512 B sectors, 4 sectors per cluster, 2 FATs of 40 sectors, 112 root entries) is not linearly mapped (root-directory sectors read as FTL metadata, mtools cannot open it), so CPE.BIN was not injected. Next step: reproduce the firmware's own file write (cpe_xfer from the phone, string near 0x17F175) or decode the flash layer, then give the file a validity date after the sim clock.
- Mode 20: 0xA51A8(20) is called from 0xA6E5A (HAL mailbox handler 0xA6CF8, message 0x219; 0x21A and 0x200 give mode 0, 0x201 mode 3) and from 0xA6F3A (bus message 0x5FE, nonzero byte). 0x5FE is published by 0x468CDE4 (settings blob, 161 bytes) and 0x219 by 0x466A5BE (state machine around 0x466A4A4, state 0x3C). Who triggers them is not traced; mode 20 is not reached.
- 0xAAC3C (BD5 subs 20/23/24/29/30) is the Sony CEP assistance check state machine (log strings CEP_INFO, CEP_TRANSFER_BEGIN), not the fix path. 0xA7708 and its neighbours format a GPS CSV log, not the receive path. The fix/measurement layout is still not found; nothing is fed.
- 0xAFDF4 is a map-coordinate affine transform, not the GNSS receive path.
