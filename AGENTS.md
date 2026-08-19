# Jarred Drive agent guide

Jarred Drive is a personal, local-first repository. Do not add work-repository dependencies, credentials,
cloud telemetry, or services without an explicit request.

Hard safety boundary: VX3 controls VESC over PPM; the ESP observes VESC over UART. Never add motor-command,
throttle, braking, or VESC-configuration write calls. A proposal to change that boundary requires explicit user
approval and physical safety review.

Treat `data/demo` as synthetic fixtures and say so. Never report classifier performance, hardware validation,
waterproofing, or safe operating limits from simulation or unit tests. Physical gates live in
`docs/hardware_validation.md`.

Canonical verification:

```bash
make demo
make check
make firmware-hardware
make dashboard
```

Preserve raw telemetry. Events, rides, summaries, and plots are derived and replaceable. Real imports,
annotations, and configuration snapshots are local/ignored by Git.
