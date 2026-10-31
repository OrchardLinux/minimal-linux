# P105 ARMv7 recovery base

The original iPad mini Wi-Fi uses an ARMv7 recovery environment. Build its
Alpine package base in an ARM64 Podman environment:

```sh
python3 p105/build-base.py --output /absolute/new/alpine-base.tar
```

Pass `--no-cache` to refresh the package layer. Each build uses its returned
image ID, leaving existing Podman image tags untouched.

The recipe uses pinned container images and the official ARMv7 Alpine signing
keys. It extracts signed ARMv7 packages without running their scripts. A JSON
receipt beside the archive records the target architecture, image identity,
recipe hash and archive hash. The base does not contain owner firmware or
calibration. A separate private recovery composer and the companion hardware
and CLI contributions are required for a tethered boot.
