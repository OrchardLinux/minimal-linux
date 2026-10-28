# P105 ARMv7 RAM recovery

`build-base.py` obtains an Alpine ARMv7 base through the signed package indexes.
Its pinned ARM64 container runs the package manager; the official ARMv7 image
supplies the target signing keys. Target programs are extracted without running
package scripts. The receipt records the resulting image and archive hashes.

`prepare-recovery.py` composes a private root from that archive, an explicit
owner initramfs and its matching MtCl capture. Supply the verified target JSON
with `udid` and `ecid`. The result records the selected ECID for Orchard's USB
identity and the device protocol. Firmware and calibration remain private.

The composer clears inherited SSH keys. Recovery generates its diagnostic key
after a host provisions access through the physical serial console. A small
closure of the ARMv7 SSH executable and its libraries can travel in RAM through
the NFS pivot, preserving its pinned key across userspaces.

Pass the composed root to the hardware package's `kernel/p105/build` as
`--private-initramfs`, with the separate `--calibration` input. That producer
installs the recovery init and selects its kernel USB settings while retaining
the P105 flash fence. The companion CLI's `docs/p105.md` describes private
manifest assembly and the native boot workflow.

The NFS root needs the hardware package's P105 systemd runtime and Python 3.9
or later. It can contain the preserved Arch / Omarchy A desktop during this
phase. The ARMv7 desktop release builder remains a later contribution.
