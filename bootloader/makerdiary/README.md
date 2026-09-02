# Makerdiary nRF52840 MDK USB Dongle

OpenPuck supports the Makerdiary/GeeekPi nRF52840 MDK USB Dongle through an
explicit `OPK_BOARD_MDK_USB_DONGLE` build. The MDK path is intentionally
compile-time isolated: ordinary OpenPuck builds do not auto-detect the board and
must not acquire MDK GPIO, reset, USB-ordering, or clock-diagnostic behavior.

## Application build

Run `make build-mdk`. This keeps the normal Adafruit nRF52840/S140 memory layout
and adds only the MDK board definition. Routine MDK updates use the resulting
application-only UF2 and leave S140, InternalFS, and the bootloader untouched.

## Fresh factory boards

Older/factory MDK units may contain S132 5.1.0. OpenPuck requires S140 6.1.1 and
an application linked at `0x26000`. For those boards:

1. Build the MDK application with `make build-mdk`.
2. Set `SOFTDEVICE_HEX` to Nordic S140 6.1.1.
3. Run `make package-mdk-first-install`.
4. Flash the generated first-install UF2 through the existing UF2 bootloader.

`tools/make_mdk_first_install.py` refuses SoftDevice/application overlap and
refuses any generated block at or above the Makerdiary bootloader base
`0xF4000`. The OpenPuck InternalFS range `0xED000..0xF3FFF` is not populated.

## OpenPuck bootloader

GitHub Actions installs the bootloader Python dependencies explicitly. For a
local Linux/macOS build, install the same versions before running the target:

```sh
python3 -m pip install adafruit-nrfutil==0.5.3.post16 intelhex==2.3.0
```

The Adafruit nRF52 Arduino core supplies the ARM GCC toolchain used by the
bootloader build. `build_mdk_bootloader.sh` also accepts `--arm-gcc-prefix` when
the compiler is installed elsewhere.

The repository does not vendor Adafruit's bootloader source. The build recipe
pins Adafruit_nRF52_Bootloader commit
`c87ea51b86b96f9b19458abfc6b37d4cb52e160b`, applies exactly two OpenPuck
compatibility changes, and builds the UF2 bootloader as `0.7.1-openpuck`. This
label is intentional: `INFO_UF2.TXT` must identify the device as
`UF2 Bootloader 0.7.1-openpuck`.

- conservatively configure P0.18 as nRESET only when both UICR PSELRESET words
  are erased; already-correct state is left alone and conflicting state is never
  overwritten;
- stop LFCLK and wait for it to stop immediately before handing control to the
  application, so OpenPuck can establish its application clock policy.

No OpenPuck watchdog patch is applied: the pinned Adafruit bootloader already
reloads active watchdog channels.

`tools/verify_mdk_bootloader_hex.py` accepts programmed bootloader/config bytes
only in `0xF4000..<0xFE000`, plus the standard Adafruit UICR words at
`0x10001014` (`0x000F4000`) and `0x10001018` (`0x000FE000`). It rejects
application, SoftDevice, settings-page, and unexpected UICR writes.

Run `make build-mdk-bootloader` from a Linux/macOS shell to clone the pinned
source, apply the local patches, build, validate, and generate a bootloader-only
S140 DFU ZIP with `adafruit-nrfutil`. GitHub Actions uses this same Make target.
The optional `bootloader/makerdiary/flash_mdk_bootloader.sh` helper requires an
explicit serial port and never guesses a device.

## Release contract

The MDK release path carries four distinct artifacts:

- application-only MDK UF2 for normal updates;
- one-time S140 6.1.1 + current MDK application UF2 for legacy factory boards;
- OpenPuck bootloader HEX;
- bootloader-only S140 DFU ZIP.

The large local production release builder is intentionally not part of this
repository-facing workflow.
