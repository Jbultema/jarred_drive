# Brand system

Jarred Drive's visual identity joins two ideas: a compact DIY foil-assist worn by the rider and a precise
engineering instrument that turns sessions into evidence. Artwork is bundled locally so the dashboard and
documentation remain usable offline.

## Canonical mark

The mark is intentionally a physical-system silhouette, not a generic e-foil:

- a crouched rider wearing the battery at the lumbar region;
- a short coiled umbilical from the pack to the board's rear connector;
- a compact motor pod fixed to the mast approximately one-third down from the board;
- a clearly exposed propeller rather than a jet or turbine;
- a distinct foil wing at the mast bottom; and
- cyan instrumentation and orange energy accents over the deep-navy structure.

Do not redraw the lead as a cable extending visibly down the mast, place the motor at the foil wing, convert
the lumbar pack to a backpack, or use the mark to imply that the logger controls propulsion.

## Assets

| File | Use |
|---|---|
| `assets/branding/jarred-drive-mark-source.png` | Full-resolution source raster |
| `assets/branding/jarred-drive-mark.png` | README, dashboard navigation, and general product mark |
| `assets/branding/jarred-drive-icon.png` | Browser/app icon and compact contexts |
| `assets/branding/jarred-drive-hero.png` | Flight Deck and repository hero treatment |

The generated source currently uses a clean white field because automated alpha extraction did not preserve
the production image reliably. Present it as an intentional light badge; do not use the checkerboard-preview
version. A future vector trace can replace the raster without changing the canonical geometry above.

## Palette

| Role | Hex | Purpose |
|---|---|---|
| Deep water | `#050C15` | Primary background |
| Instrument panel | `#0B1927` | Cards and navigation |
| Telemetry cyan | `#4DE4FF` | Primary signal and interaction |
| Energy amber | `#FFB547` | Power, launch, and caution |
| Healthy green | `#5EE5AE` | Ready/verified states |
| Fault coral | `#FF667D` | Stop, crash, and fault states |
| Ice white | `#F3FBFF` | Primary text |
| Sensor gray | `#8FA8B9` | Supporting text |

## Usage and accessibility

Keep the mark's full silhouette legible and preserve clear space around the mast, propeller, and coiled lead.
On small surfaces use the provided icon rather than cropping the larger mark. UI meaning must never rely on
color alone: pair status colors with text labels, shapes, or icons. Maintain readable contrast on the navy
palette and retain descriptive alt text that identifies the lumbar pack, coiled lead, mast motor/propeller,
and foil.

The hero is atmospheric product artwork, not an engineering diagram. Use
[architecture.md](architecture.md) and the build/wiring package for physical assembly decisions.
