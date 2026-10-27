# Build

## GitHub Actions

`.github/workflows/build.yml` runs unit tests on pull requests and `main`. Version tags (`v*`) and manual dispatches build the image: macOS builds Pongo and its matching loader artwork, Linux ARM64 builds m1n1, and Linux ARM64 extracts the digest-pinned Alpine OCI base with `skopeo`/`umoci` and runs `system/install-base` in a native chroot. This is the same install recipe used by the local Containerfile, without Podman or a container daemon.

Select published hardware and CLI tags in manual dispatch; tag builds use the explicit defaults in the workflow. `ci/dependencies` installs their hashed wheel pair, verifies the hardware bundle and exposes its compiled kernel/modules/tools. No sibling hardware source checkout is used.

Assembly runs the same producers, auditor and CLI resolution as below, then rewrites artifact references to immutable release URLs. Version tags create **draft** releases; manual runs only upload seven-day workflow artifacts. Assets include the base, root/build receipts, source archives and checksums for subsequent shared-launcher builds. Follow the [release order](https://github.com/OrchardLinux/hardware/blob/main/docs/ci.md); building is not physical-device qualification.

Public tag/manual builds attest every final asset, including `SHA256SUMS`, and retain `minimal-linux-build.sigstore.jsonl` alongside workflow/draft release assets. Private or unknown-visibility builds skip signing and bundle copying. Only final assembly has signing permissions; public signing failures block release creation. The bundle is not listed in the signed checksum manifest. Verify an asset with `gh attestation verify FILE --repo OrchardLinux/minimal-linux`; attestation is not device qualification.

## Local setup

Requires a native ARM64 Podman machine and Python 3.9+ with venv/pip. Run commands from this repository. Build tools require no device access or host firmware cache.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --only-binary=:all: -r \
  https://github.com/OrchardLinux/cli/releases/latest/download/requirements.txt
```

Use `orchard-hardware>=0.1.10,<0.2`. For unpublished builds, install compatible CLI/hardware wheels by explicit paths instead. Container package downloads are separate from the IPSW/device-firmware cache.

## Public inputs

Build compatible loader, kernel, DTB, modules, Pongo and static BusyBox/Dropbear tools using the [hardware producers](https://github.com/OrchardLinux/hardware/blob/main/BUILD.md) and this image's [boot producers](boot/README.md). Verify component receipts before pinning. Keep kernel and module ABI names identical.

The component copier takes exact explicit paths, refuses links/overwriting, and creates independent copies plus a per-file hash inventory:

```sh
python pin_components.py \
  --loader /absolute/path/m1n1.bin --pongo /absolute/path/Pongo.bin \
  --kernel /absolute/path/kernel/Image.gz --dtb /absolute/path/kernel/j71b.dtb \
  --modules-dir /absolute/path/kernel/lib/modules \
  --busybox /absolute/path/busybox --dropbear /absolute/path/dropbear \
  --dropbearkey /absolute/path/dropbearkey --output out/components/public
```

`kernel.release` must be beside `lib/` in the supplied kernel tree. This tool records selected input hashes; it is not a signature/trust service.

## Base and coherent release

From this directory, with the installed hardware package available to `python`:

```sh
python build_base.py --output out/components/base.tar.gz
python build.py \
  --base out/components/base.tar.gz \
  --base-receipt out/components/base.tar.gz.json \
  --inputs out/components/public/inputs.json \
  --version YOUR_NEW_VERSION --output out/releases/YOUR_NEW_VERSION
python audit.py out/releases/YOUR_NEW_VERSION
orchard resolve out/releases/YOUR_NEW_VERSION/index.toml
```

Use fresh output paths; producers refuse overwriting. The official Alpine OCI digest is pinned in `system/Containerfile`; APK repositories retain signature checking. The base records package versions in `/etc/alpine-packages.lock`. Its archive hash and all selected hardware hashes are recorded separately from the install contract. The APK mirror is not an immutable snapshot: future base rebuilds may select newer signed package revisions and must get new receipts.

The producer composes the installed hardware resources with Alpine-owned policy, creates a public gzip root, seals a fresh recovery to its receipt, and emits a direct-artifact target manifest plus pinned distro index. Public build receipts omit local machine paths. No private firmware, SSH keys, ADT or machine IDs are embedded.

## Native isolated checks

```sh
python -m unittest discover -s tests -q
podman import out/releases/YOUR_NEW_VERSION/rootfs.tar.gz localhost/orchard-minimal-test:YOUR_NEW_VERSION
podman run --rm --init --network none --cap-add NET_ADMIN --cap-add NET_RAW --cap-add SYS_ADMIN \
  -v "$PWD/out/releases/YOUR_NEW_VERSION:/payload:ro" -v "$PWD/tests:/test:ro" \
  localhost/orchard-minimal-test:YOUR_NEW_VERSION /usr/bin/python3 /test/native-image.py
python tests/native-init.py localhost/orchard-minimal-test:YOUR_NEW_VERSION
python tests/native-recovery.py out/releases/YOUR_NEW_VERSION
```

These operate only in disposable containers. No device passthrough, source overlay, external network or physical storage installation. The full init test supplies only ephemeral keys, an inherited-style `/run` tmpfs and a dummy USB NIC. Hardware verification is real and must fail on the container kernel; readiness must remain false. Read-only container cgroup warnings do not establish a physical cgroup failure. Native service tests use a reaping init, not Python as an accidental unreaping PID 1.
