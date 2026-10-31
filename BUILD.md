# Build

## GitHub Actions

`.github/workflows/build.yml` runs unit tests on pull requests and `main`. Version tags (`v*`) and manual dispatches build the image: macOS renders the loader artwork, Linux ARM64 builds m1n1, and Linux ARM64 extracts the digest-pinned Alpine OCI base with `skopeo`/`umoci` and runs `system/install-base` in a native chroot. This is the same install recipe used by the local Containerfile, without Podman or a container daemon.

Select the published orchard release with the compiled components in manual dispatch; tag builds use the explicit default in the workflow. `ci/dependencies` checks out orchard's `main` (or `ORCHARD_REF`), verifies that release's component bundle and exposes its compiled kernel/modules/tools. The build receipt records the exact orchard commit.

Assembly runs the same producers, auditor and CLI resolution as below, then rewrites artifact references to immutable release URLs. Version tags create **draft** releases; manual runs only upload seven-day workflow artifacts. Assets include the base, root/build receipts, source archives and checksums for subsequent shared-launcher builds. Follow the [release order](https://github.com/OrchardLinux/orchard/blob/main/docs/ci.md); building is not physical-device qualification.

Public tag/manual builds attest every final asset, including `SHA256SUMS`, and retain `minimal-linux-build.sigstore.jsonl` alongside workflow/draft release assets. Private or unknown-visibility builds skip signing and bundle copying. Only final assembly has signing permissions; public signing failures block release creation. The bundle is not listed in the signed checksum manifest. Verify an asset with `gh attestation verify FILE --repo OrchardLinux/minimal-linux`; attestation is not device qualification.

## With orchard

```sh
orchard build [--version VERSION]
```

builds a release into `out/releases/VERSION` (default `dev-DATE-TIME`) through
`tools/build.py`, the entry `distro.toml` names: the loader and base are kept in
`out/components/NAME/KEY/`, keyed by their files, and rebuilt only when they
change; the release is assembled and audited every time. `orchard run` boots its
recovery on the attached device without installing, and `orchard install`
installs it. The rest of this page is what that entry runs, step by step.

## Local setup

Requires uv and a native ARM64 Podman environment. Run commands from this
repository. Build tools require no device access or host firmware cache.

```sh
orchard --version
```

`orchard` comes from orchard's launcher on your PATH and runs orchard's `main`, or
the checkout your `orchard.local.toml` names. Run this repository's producers with
`orchard python ...`, which uses that checkout's environment. Container package
downloads remain separate from the IPSW/device-firmware cache. Full Alpine image
assembly below is owned by this repository; it is not an `orchard build` special case.

## Public inputs

Build the distro-branded loader and static BusyBox/Dropbear tools using the
[orchard producers](https://github.com/OrchardLinux/orchard/blob/main/BUILD.md)
and this image's [boot producers](boot/README.md). Verify their receipts before pinning.
Pongo is not built here: use orchard's one Pongo, `quiet/pongo.bin` from the
orchard component bundle (black screen; the Alpine logo appears with m1n1).

The component copier pins them as independent copies with a per-file hash
inventory, refusing links and existing output paths. Kernels are not pinned
there: a release covers every platform, and `build.py` builds or reuses each
platform's kernel through orchard's shared cache (the same builder as `orchard
build` in orchard's examples), or takes `--kernel-dir PLATFORM=DIRECTORY` per
platform (CI, orchard's per-platform component bundles). `--platform PLATFORM`
builds fewer platforms, for development only.

```sh
orchard python pin_components.py \
  --loader /absolute/path/m1n1.bin --pongo /absolute/path/quiet/pongo.bin \
  --busybox /absolute/path/busybox --dropbear /absolute/path/dropbear \
  --dropbearkey /absolute/path/dropbearkey --wpa-supplicant /absolute/path/wpa_supplicant \
  --wpa-cli /absolute/path/wpa_cli --iw /absolute/path/iw --output out/components/public
```

This tool records selected input hashes; it is not a signature/trust service.

## Base and coherent release

From this directory, with the editable workspace dependencies:

```sh
orchard python build_base.py --output out/components/base.tar.gz
orchard python build.py \
  --base out/components/base.tar.gz \
  --base-receipt out/components/base.tar.gz.json \
  --inputs out/components/public/inputs.json \
  --version YOUR_NEW_VERSION --output out/releases/YOUR_NEW_VERSION
orchard python audit.py out/releases/YOUR_NEW_VERSION
orchard python -m orchard.manifests --verify-local out/releases/YOUR_NEW_VERSION/index.toml
```

Use fresh output paths; producers refuse overwriting. The official Alpine OCI digest is pinned in `system/Containerfile`; APK repositories retain signature checking. The base records package versions in `/etc/alpine-packages.lock`. Its archive hash and all selected hardware hashes are recorded separately from the install contract. The APK mirror is not an immutable snapshot: future base rebuilds may select newer signed package revisions and must get new receipts.

The producer composes Alpine-owned policy into one public gzip root for every platform (no kernel or modules: orchard's platform layer brings those at install, and orchard writes the boot entry), seals a recovery per platform to the root's receipt, adds orchard's layer per platform, and emits `release.toml` plus the index that pins it. Public build receipts omit local machine paths. No private firmware, SSH keys, ADT or machine IDs are embedded.

## Native isolated checks

```sh
orchard python -m unittest discover -s tests -q
podman import out/releases/YOUR_NEW_VERSION/rootfs.tar.gz localhost/orchard-minimal-test:YOUR_NEW_VERSION
podman run --rm --init --network none --cap-add NET_ADMIN --cap-add NET_RAW --cap-add SYS_ADMIN \
  -v "$PWD/out/releases/YOUR_NEW_VERSION:/payload:ro" -v "$PWD/tests:/test:ro" \
  localhost/orchard-minimal-test:YOUR_NEW_VERSION /usr/bin/python3 /test/native-image.py
orchard python tests/native-init.py localhost/orchard-minimal-test:YOUR_NEW_VERSION
orchard python tests/native-recovery.py out/releases/YOUR_NEW_VERSION
```

These operate only in disposable containers. No device passthrough, source overlay, external network or physical storage installation. The full init test supplies only ephemeral keys, an inherited-style `/run` tmpfs and a dummy USB NIC. Hardware verification is real and must fail on the container kernel; readiness must remain false. Read-only container cgroup warnings do not establish a physical cgroup failure. Native service tests use a reaping init, not Python as an accidental unreaping PID 1.
