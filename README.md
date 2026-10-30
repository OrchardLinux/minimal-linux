# Minimal Linux

A small Alpine-based Linux image for Apple devices, demonstrating the Orchard release format without a desktop or systemd requirement.

Currently supports iPad 6 Wi-Fi (`iPad7,5`, J71b), experimentally. Boot is tethered and requires a host computer. This is a development/reference image, not a general-purpose tablet distribution.

## Local development

This repository is a distribution on top of
[orchard](https://github.com/OrchardLinux/orchard), which holds the hardware support
and the `orchard` tool. Put orchard's launcher on your PATH once (see its
[README](https://github.com/OrchardLinux/orchard#develop)); here it runs orchard's
`main` by default, or the checkout a gitignored `orchard.local.toml` names
(`orchard = "../orchard-mine"`, plus `device = "j71b"` for your board). Run this
repository's producers and tests in that orchard's environment:

```sh
orchard python -m unittest discover -s tests
```

RAM experiments and device bring-up happen in orchard itself, with its
[examples](https://github.com/OrchardLinux/orchard/tree/main/examples). This
repository builds the Alpine image; its assembly is documented below.

## Build and validate

Follow [BUILD.md](BUILD.md) to set up a repository-local environment, build public components, assemble a coherent root/recovery release and run isolated tests. [Boot presentation](boot/README.md) describes the Alpine artwork and loader producers.

Distro builds use the orchard checkout `orchard` runs and explicit component artifacts. Private firmware, calibration, device identity and diagnostic keys are not included in public images.

## Install a local build

Use [orchard](https://github.com/OrchardLinux/orchard) with a compatible device and a prepared Linux-data partition. Back up the device first; storage changes can permanently erase data.

```sh
orchard resolve out/releases/YOUR_NEW_VERSION/index.toml
orchard install out/releases/YOUR_NEW_VERSION/index.toml
```

The CLI asks before installation or formatting. Do not interrupt a confirmed storage operation. Building or testing in a container does not qualify a release on hardware.

`orchard launch` can start an installation only when the published shared launcher explicitly supports that build's root receipt and kernel/runtime inputs. An arbitrary local rebuild is not automatically supported by the public launcher.

## License

See [LICENSE](LICENSE), [NOTICE](NOTICE), and component notices. Alpine artwork and trademarks belong to their respective owners; no endorsement is implied.
