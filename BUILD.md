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
`tools/build.py`, the entry `orchard.toml` names: the loader and base are kept in
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

`orchard` comes from orchard's launcher on your PATH and runs orchard's newest
nightly (`ORCHARD_VERSION` pins one); an orchard checkout's own `bin/orchard` runs
that checkout. Run this repository's producers with `orchard python ...`, which
uses that orchard's environment. Container package
downloads remain separate from the IPSW/device-firmware cache. Full Alpine image
assembly below is owned by this repository; it is not an `orchard build` special case.

## Without orchard's tool

The build imports none of orchard's Python: it runs orchard's producers as
commands from an orchard snapshot (orchard's
[distribution contract](https://github.com/OrchardLinux/orchard/blob/main/docs/distribution-contract.md)).
`orchard build` passes its own; by hand, take an orchard checkout or a
release's `orchard-source.tar.gz` unpacked as `ORCHARD`. `snapshot.py` holds
the few lines that find it and run its commands.

```sh
export ORCHARD=/path/to/orchard PYTHONPATH=/path/to/orchard/src
python3 boot/build-artwork.py --output out/artwork
python3 build_base.py --output out/base/base.tar.gz
# What orchard supplies finished: kernels and boards per platform, m1n1, Pongo, tools.
python3 -m orchard.inputs --output out/orchard-inputs.json --platform apple-16k
python3 pin_components.py --loader M1N1 --splash out/artwork/splash --logo out/artwork/logo.bin \
  --pongo PONGO --busybox … --dropbear … --dropbearkey … --wpa-supplicant … --wpa-cli … --iw … \
  --output out/public          # M1N1, PONGO, the tools: the paths orchard-inputs.json names
python3 build.py --base out/base/base.tar.gz --base-receipt out/base/base.tar.gz.json \
  --inputs out/public/inputs.json --orchard-inputs out/orchard-inputs.json --orchard "$ORCHARD" \
  --version YOUR_NEW_VERSION --output out/releases/YOUR_NEW_VERSION
python3 audit.py out/releases/YOUR_NEW_VERSION --orchard "$ORCHARD"
python3 -m orchard.manifests --verify-local out/releases/YOUR_NEW_VERSION/index.toml
python3 -m orchard.installer release out/releases/YOUR_NEW_VERSION
```

`orchard.inputs` takes the nightly's kernels, m1n1 and tools when they were
built from the snapshot's files, and builds them otherwise; given
`--kernel-dir PLATFORM=DIR`, `--m1n1`, `--pongo` and `--tools` (CI, from
orchard's component bundles) it uses those as they are. Pongo is never built
here: it is orchard's one Pongo (black screen; the Alpine logo appears with
m1n1). `pin_components.py` records the selected inputs' hashes; it is not a
signature or trust service.

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
