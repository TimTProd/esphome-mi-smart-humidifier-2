# UART fixes for Mi Smart Humidifier 2 (BW15 / RTL8720C)

Experimental source patches saved separately from the device configuration.
**This branch does not automatically apply the patches when compiling
`humidifier.yaml`.** Apply them to isolated dependency checkouts as below.
No firmware, credentials, private configuration, generated build tree or raw
runtime logs are included. No upstream PR is opened by saving this branch.

## Exact tested sources

| Dependency | Revision |
| --- | --- |
| ESPHome | `2026.2.1` |
| [prokoma/libretiny](https://github.com/prokoma/libretiny) | `55aacc865f612b2aac202aba09e8403eeb97c5a7` |
| [dhewg/esphome-miot](https://github.com/dhewg/esphome-miot) | `a456ab1219f0ec87d2f0ca547bf03bb1a011ec51` |
| Arduino API package | `2022.8.24+sha.237b10a` |

## Two changes

1. **Real UART receive storage: 64 -> 512 bytes.**
   `libretiny-ring.patch` changes the RTL8720C driver's ring specialization and
   its matching `SerialClass` pointer. The common pointer change is guarded
   with `LT_RTL8720C`; other chip families retain their existing pointer type.
   Changing only storage does not compile: `RingBufferN<512>*` is not a
   `RingBufferN<64>*`. No unsafe cast or global Arduino buffer-size change is
   used. The regression burst is 94 bytes: the old ring retains 64, the new
   ring retains all 94.
2. **Do not time out a partial MIOT frame while UART bytes are queued.**
   `miot-timeout.patch` adds `!this->available()` to the existing partial-frame
   timeout condition. A delayed main loop can then read an already-queued
   continuation/CR rather than discard the prefix first. The timeout duration
   itself is unchanged. An incomplete stale frame with an empty queue is still
   discarded. This is not a full UART parser rewrite.

## Applying the patches safely

Use independent checkouts and an independent PlatformIO core directory, not a
shared/global installation. Here `$PATCHES` is the absolute path to this folder,
`$LT` is a LibreTiny checkout at the pinned revision, and `$MIOT` is the MIOT
repository checkout at its pinned revision:

```sh
git -C "$LT" apply --check "$PATCHES/libretiny-ring.patch"
git -C "$LT" apply "$PATCHES/libretiny-ring.patch"
git -C "$MIOT" apply --check "$PATCHES/miot-timeout.patch"
git -C "$MIOT" apply "$PATCHES/miot-timeout.patch"
```

In a **private candidate YAML**, reference the patched local MIOT component and
the local LibreTiny platform, and set a separate `build_path`. Do not replace
Wi-Fi/API/OTA credentials with examples or publish them. Preserve other device
settings. Pinning the original revision alone does not apply these patches.

PlatformIO may install a **copy** of a local `file://` platform. Before building,
verify the installed private platform contains both changed headers and that
its contents match the patched checkout. Do not assume dirty local files were
copied by a Git-based package install.

Compilation-only commands (with paths substituted for your private candidate):

```sh
export PLATFORMIO_CORE_DIR="$CANDIDATE/pio-home"
esphome compile --only-generate "$CANDIDATE/smart-humidifier-2.yaml"
pio run -j 4 -d "$CANDIDATE/build"
```

Use the pinned ESPHome in a local virtual environment. These commands do not
perform upload/OTA. A build must not silently install the latest global ESPHome.

## Host regression harness

`host_regression.py` compiles the **actual Arduino RingBuffer header** and the
**actual extracted `Miot::loop()` body**, with a minimal host UART/time adapter.
It does not emulate hardware interrupts, SDK execution, or the entire MIOT
component. The adapter assumes `RECEIVE_TIMEOUT=300`, `MAX_LINE_LENGTH=512`
and a 513-byte message array for these pinned sources; declaration changes in
upstream code require reviewing those fixture assumptions. It requires Python
and a C++17 compiler named `g++`.

The timeout guard cannot distinguish a queued continuation from an unrelated
new frame arriving after a stale incomplete prefix. It favors retaining queued
bytes, so stale-prefix/new-frame recovery remains a case to investigate before
upstream acceptance.

Expected fixture layout (dependencies are not vendored here):

```text
fixture/candidate/
  components/miot/miot.cpp
  libretiny/cores/realtek-ambz2/arduino/libraries/Serial/SerialPrivate.h
  pio-home/packages/framework-arduino-api/api/RingBuffer.h
```

```sh
python3 host_regression.py /absolute/path/to/fixture/candidate all
```

The harness writes generated C++ and test executables into `fixture/tests/`.
Use a disposable fixture, outside this repository's source tree. Its `-iquote`
include option avoids Arduino `String.h` shadowing system `string.h` on
case-insensitive macOS filesystems.

Verified regressions: burst retention, 512-byte capacity, ring wraparound,
queued CR after a 350 ms main-loop delay, stale empty-queue timeout, normal
fragmentation, consecutive frames, `millis()` wraparound and preservation of
existing overlength handling. Both target regressions were observed failing
before their respective fixes, then passing afterward. Patch application and
RED/GREEN tests were independently replayed on clean pinned upstream checkouts
before publishing this branch. The full cross-build also validates the pointer
compatibility that the smaller host harness does not exercise.

## What was verified, and what remains unresolved

- The patched candidate compiled on an Apple Silicon MacBook for BW15 using
  ESPHome 2026.2.1. PlatformIO reported SUCCESS, RAM 13001 / 262144 bytes and
  flash 567085 / 1015808 bytes.
- The verified UF2 was uploaded after explicit owner approval. Device identity,
  matching compilation timestamp, sensor updates and physical mist production
  were checked after startup. Firmware SHA256:
  `d1610a0f1212f9f6b8e45ce121095485201edc5aba8779e9ae95996a12c0da9d`.
  The firmware itself is intentionally not in Git.
- **This is not evidence that all UART faults are fixed.** The longer capture
  on the patched build still recorded one burst of **44 receive timeouts and
  44 invalid-command warnings**. A later 15-minute observation had no such
  errors or API disconnections. These are different observation windows, not
  contradictory results.
- Repeated `Received property value without component: 2 7 ...` warnings were
  also observed; these patches do not add a handler for that property.
- No new patch, firmware rebuild, OTA or device-control operation is implied by
  committing this source snapshot. Further diagnosis and hardware testing are
  needed before claiming complete resolution or proposing upstream acceptance.
