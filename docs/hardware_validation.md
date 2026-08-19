# Hardware validation gates

These are evidence gates, not a substitute for the supplied build guide. Record results, photos, firmware hash,
VESC firmware, configuration snapshot, and measured values for each gate.

1. **Host simulation:** `make check` passes; three synthetic scenarios render and alert correctly.
2. **Firmware compile:** `make firmware-hardware` succeeds for the exact checked-out sources.
3. **USB-only display:** verify orientation, legibility, reboot behavior, and READY/WARNING/STOP pages.
4. **USB-only monitoring board:** confirm every 74HC4051 channel, NTC conversion near room temperature,
   QMI8658 axes/scaling against Waveshare demo, and SD row cadence.
5. **Water calibration:** measure dry, condensation/drop, and wet ADC distributions using final electrodes and
   local water; replace the firmware placeholder, verify three-sample debounce and session latch.
6. **Independent 12S-to-5.1V supply:** verify converter pinout, fuse, polarity, ripple, transient behavior, and
   5.0–5.2 V at USB-C before attaching the ESP.
7. **VESC-only commissioning:** propeller removed; record hardware/firmware, motor detection, conservative
   limits, PPM behavior, and remote loss-of-link idle response.
8. **Read-only UART:** join TX/RX/GND only; compare every available field against VESC Tool and prove remote
   behavior remains unchanged when the ESP is disconnected/rebooted.
9. **Fault injection:** exercise missing SD, invalid NTC, hot-sensor simulation, VESC fault, water alarm, UART
   loss, and brownout/reboot; verify raw log integrity and dominant warnings.
10. **Home sync:** with propulsion disconnected, verify Wi-Fi remains absent during RECORDING, STOP closes the
    session, SYNC joins only the intended LAN, mDNS resolves, interrupted Range downloads resume, altered files
    fail SHA-256, duplicate syncs are idempotent, and acknowledgement never deletes SD files.
11. **Progressive load:** 12S2P then 12S3P, prop removed/restrained as required by the build guide; inspect
    connectors, current path, voltage sag, temperatures, and sampling gaps.
12. **Lumbar umbilical and submerged drive:** with propulsion electrically isolated, validate the final short
    coiled lead from the lumbar pack to the rear-of-board connector across the full riding range of motion.
    Record relaxed/extended length, connector retention and release behavior, bend radius, abrasion and snag
    exposure, waterproofing, strain relief at both ends, and a controlled rider/board separation drill. Confirm
    that no loose external lead descends the mast. Verify the compact motor/propeller installation at the
    intended position approximately one-third down from the board, including fastener retention, propeller
    clearance/guarding, cable containment, mast loading, and compatibility with the lower foil and stabilizer.
13. **Sealed enclosure:** dry leak testing, controlled droplet, cable strain relief, lid clearance, logging during
    movement, and post-test corrosion inspection.
14. **Restrained wet propulsion:** only after control, failsafe, telemetry, temperature protection, retention,
    and leak sensing pass independently.
15. **Labeled field sessions:** manually annotate at least 5–10 sessions before evaluating or training foil-state
    classification. Compare detection precision/recall by event type; do not promote guessed thresholds.

No repository status, unit test, synthetic result, or successful compile closes gates 3–15.
