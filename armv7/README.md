# ARMv7 recovery base

Apple's 32-bit boards (the apple-armv7 platform, first the original iPad mini
Wi-Fi) use an ARMv7 recovery environment. Build its Alpine package base in an
ARM64 Podman environment:

```sh
python3 armv7/build-base.py --output /absolute/new/alpine-base.tar.gz
```

Pass `--no-cache` to refresh the package layer. Each build uses its returned
image ID, leaving existing Podman image tags untouched.

The recipe uses pinned container images and the official ARMv7 Alpine signing
keys. It extracts signed ARMv7 packages without running their scripts. A JSON
receipt at `alpine-base.tar.gz.json` records Orchard's target architecture
(`arm`), image identity, recipe hash and archive hash. The gzip tar uses the
merged `/usr` layout expected by Orchard's recovery producer and includes
native `blkid`, `sfdisk`, `mke2fs` and its configuration. Python's musl loader
and libraries live under `/usr/lib` so the producer can stage their closure.
The base does not contain owner firmware or
calibration. A separate private recovery composer and the companion hardware
and CLI contributions are required for a tethered boot.
