# Distro-owned Alpine boot presentation

Alpine artwork and display presentation are owned by this image. Shared hardware support supplies kernel, firmware preparation, USB transport and handoff.

## Artwork

`artwork/upstream-alpinelinux-logo.svg` is pinned to the Alpine project's repository revision recorded in `artwork/source.json`. `alpine-mark.svg` isolates the official mountain/hex mark and places white behind its transparent mountain cutouts for use on black. Alpine blue `#0d597f` and the original mark paths are retained. Alpine trademarks belong to their owners; this does not imply endorsement.

`generate-logo.py` produces independent blue/white one-bit planes on the 400-pixel canvas from `artwork/presentation.json`; `splash.py` turns them into orchard's boot splash, which m1n1 paints for an installed boot entry. The recovery shows the same mark as m1n1's custom logo (`logo.bin`: RGBA on black, 256×256 and 128×128), which orchard's assembly puts directly after m1n1. This image builds no m1n1 of its own: it is orchard's, with the artwork as data. Pongo, which runs before m1n1, is orchard's one Pongo and keeps the screen black.

## Build

Requires Python, `rsvg-convert` and ImageMagick; no m1n1 or C toolchain.

```sh
python boot/build-artwork.py --output out/artwork   # out/artwork/splash, out/artwork/logo.bin
```

Each output directory must be new. `tools/build.py` (the `orchard build` entry) runs it as a keyed component and pins the result with orchard's m1n1 and Pongo (`pin_components.py`).

## Readiness clear

The image's `minimal-ready` helper invokes `minimal-clear-splash` and then `minimal-console` after service/hardware readiness. It validates the actual simpledrm ARM64 fbdev format, stride, channel masks and memory bounds, writes black pixels only within that buffer, then activates the black framebuffer. No panel/backlight controls, driver reset, storage write, power management or touch operations are involved.

Clearing is cosmetic: absent/unsupported displays produce a recorded warning rather than invalidating authenticated headless readiness. The ready record includes `splash.cleared` and any error.
