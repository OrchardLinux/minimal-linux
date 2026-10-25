# Distro-owned Alpine boot presentation

Alpine artwork and display presentation are owned by this image. Shared hardware support supplies kernel, firmware preparation, USB transport and handoff.

## Artwork

`artwork/upstream-alpinelinux-logo.svg` is pinned to the Alpine project's repository revision recorded in `artwork/source.json`. `alpine-mark.svg` isolates the official mountain/hex mark and places white behind its transparent mountain cutouts for use on black. Alpine blue `#0d597f` and the original mark paths are retained. Alpine trademarks belong to their owners; this does not imply endorsement.

`generate-logo.py` produces independent blue/white one-bit planes, not a shared global brand. Both stages use the same 400-pixel canvas from `artwork/presentation.json`;  their generated headers are required to match byte-for-byte. The exact C renderers are tested with ASan/UBSan: six Pongo stride/geometry cases and twelve m1n1 geometry/depth cases, including padding, small displays, 30/32-bit conversion and one-time publication.

## Build

Requires Python, Git, `rsvg-convert`, ImageMagick, native make/C tools and Xcode with an iPhoneOS SDK for Pongo; Podman and the installed `orchard-hardware>=0.1.9,<0.2` producer/toolchain for m1n1.

```sh
python boot/build-pongo.py --output out/branding/Pongo-alpine.bin
python boot/build-loader.py --output out/branding/m1n1-alpine.bin
python boot/pongo/test-renderer.py
python boot/m1n1/test-splash.py
```

Use `--resume` only with the matching pinned, patched worktree; choose new output paths. Each producer refuses overwriting. Pongo/newlib revisions are pinned in the build scripts. m1n1 consumes the installed package's OrchardLinux upstream pin and hardware patches, with this distro's explicit extra patch/header/flags. `--work-dir` keeps the loader checkout/cache under this consumer instead of coupling consumers through an installed-package worktree.

Pin the newly built binaries as explicit loader/Pongo inputs with `pin_components.py`.

## Readiness clear

The image's `minimal-ready` helper invokes `minimal-clear-splash` and then `minimal-console` after service/hardware readiness. It validates the actual simpledrm ARM64 fbdev format, stride, channel masks and memory bounds, writes black pixels only within that buffer, then activates the black framebuffer. No panel/backlight controls, driver reset, storage write, power management or touch operations are involved.

Clearing is cosmetic: absent/unsupported displays produce a recorded warning rather than invalidating authenticated headless readiness. The ready record includes `splash.cleared` and any error.
