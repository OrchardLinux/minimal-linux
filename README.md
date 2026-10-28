# Minimal Linux

A small Alpine-based Linux image for Apple devices, demonstrating the Orchard release format without a desktop or systemd requirement.

Currently supports iPad 6 Wi-Fi (`iPad7,5`, J71b), experimentally. Boot is tethered and requires a host computer. This is a development/reference image, not a general-purpose tablet distribution.

The [P105 recovery composer](p105/README.md) adds a private ARMv7 RAM environment
for the original iPad mini Wi-Fi. It works with hardware 0.1.11 and the native
Orchard CLI adapter for tethered boot and handoff to an existing NFS desktop.

## Build and validate

Follow [BUILD.md](BUILD.md) to set up a repository-local environment, build public components, assemble a coherent root/recovery release and run isolated tests. [Boot presentation](boot/README.md) describes the Alpine artwork and loader producers.

Builds use the installed `orchard-hardware` package and explicit component artifacts, not sibling source checkouts. Private firmware, calibration, device identity and diagnostic keys are not included in public images.

## Install a local build

Use the [Orchard CLI](https://github.com/OrchardLinux/cli) with a compatible device and a prepared Linux-data partition. Back up the device first; storage changes can permanently erase data.

```sh
orchard resolve out/releases/YOUR_NEW_VERSION/index.toml
orchard install out/releases/YOUR_NEW_VERSION/index.toml
```

The CLI asks before installation or formatting. Do not interrupt a confirmed storage operation. Building or testing in a container does not qualify a release on hardware.

`orchard launch` can start an installation only when the published shared launcher explicitly supports that build's root receipt and kernel/runtime inputs. An arbitrary local rebuild is not automatically supported by the public launcher.

## License

See [LICENSE](LICENSE), [NOTICE](NOTICE), and component notices. Alpine artwork and trademarks belong to their respective owners; no endorsement is implied.
