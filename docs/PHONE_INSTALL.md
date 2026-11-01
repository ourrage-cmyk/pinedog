# Install the Pinedog InfiniTime build from a phone

No computer, SWD, or programmer is needed. The watch updates over Bluetooth
with the same DFU process as any InfiniTime release. The stock MCUboot
bootloader on the PineTime accepts unsigned application images, which is how
InfiniTime's own release zips work.

**Status: not yet tested on a watch.** The build is produced by CI and has
not been installed on hardware. Read the warnings below before you start.

## Before you start

- The watch must already run InfiniTime 1.x with MCUboot. Check in the watch:
  Settings, then About. If the watch was updated over Bluetooth before, this is
  already the case.
- Charge the watch to at least 50%. Keep the phone next to it during the update.
- Disconnect Gadgetbridge or any other app from the watch first. The watch
  accepts one Bluetooth connection at a time.
- Keep the stock InfiniTime zip for rollback. Get it from the InfiniTime
  releases page, file `pinetime-mcuboot-app-dfu-<version>.zip`.

## Get the zip

1. Open the latest successful run of the "InfiniTime store-and-sync DFU"
   workflow in the repository's Actions tab.
2. Download the artifact `pinedog-infinitime-dfu`. It is a zip containing
   `pinedog-infinitime-<version>-dfu.zip` and `SHA256SUMS`.
3. Unzip the artifact once. Keep the inner `pinedog-infinitime-<version>-dfu.zip`
   and copy it to the phone. Do not unzip the DFU zip itself.
4. Check the checksum if you can (`sha256sum -c SHA256SUMS`). The DFU zip
   must match.

## Install with nRF Connect (Android or iPhone)

1. Open nRF Connect and go to the Scanner tab. Find `InfiniTime` and tap
   **Connect**.
2. Tap the **DFU** button at the top right.
3. Choose **Distribution packet (ZIP)** and select the DFU zip from step 3.
4. The transfer starts on its own. It takes a few minutes. The watch restarts
   when it is done.
5. On the watch, swipe right, open **Settings**, then **Firmware**, and tap
   **Validate**.

**Validate is required.** If you do not validate, MCUboot reverts to the
previous firmware on the next reboot. That is the safety net: a build that
never validates is rolled back automatically.

## Install with Gadgetbridge (Android)

Gadgetbridge can install InfiniTime firmware from a DFU zip: open the device,
choose the firmware update option, and pick the DFU zip. Use the same
Validate step on the watch afterwards. If Gadgetbridge offers only the
official releases, use nRF Connect.

## After the update

1. Check that the watch still shows the time, notifications and the
   heart-rate/steps screens. The Pinedog build keeps the same screens as the
   release it is built from.
2. Leave the watch on the dog. The logger starts recording as soon as the
   motion tick runs. No setting is needed.
3. Home Assistant finds the watch in its normal Bluetooth scan. The first
   records will be on the next sync.

## Going back to stock InfiniTime

Install the stock `pinetime-mcuboot-app-dfu-<version>.zip` in the same way
and validate. The records on the watch stay on flash, and the stock firmware
does not use them. They are sent when a Pinedog build runs again.

## Do not

- Do not install a zip from a failed run or from a build marked BROKEN.
- Do not install the Zephyr build from `firmware/release/` or `release/`. It
  overwrites the bootloader and needs SWD.
- Do not install over Bluetooth while the watch is below 30%.

## Known limits of this build (unverified)

- No pairing or encryption. A device in range that writes to the Ack
  characteristic could make the watch drop records Home Assistant has not
  stored. This is the main thing to fix before relying on it.
- Battery life is not measured. Sampling uses the 100 ms motion tick that stock
  InfiniTime already runs, so the extra cost is flash writes, one every five
  minutes.
- Classifier thresholds are fixed. Real dog data may need tuning.
