# ANVIL, FORGE, and KILN Hardware Inventory — 2026-09-24

> Historical three-host capture. The 2026-09-25 audit adds EMBER and the
> current service/resource measurements. Its resulting placement decisions are
> recorded in
> [`FOUR_HOST_AI_STACK_2026-09-25.md`](FOUR_HOST_AI_STACK_2026-09-25.md).
> Hardware facts below remain useful, but the division of labor at the end is
> superseded by that four-host plan.

Source: live, read-only host inspection over the existing SSH path. Hardware
serial numbers are intentionally omitted from this document.

## ANVIL — operator worktop

| Component | Verified hardware |
| --- | --- |
| System | MacBook Pro, model identifier Mac16,1 |
| SoC | Apple M4, 10 CPU cores (4 performance + 6 efficiency) |
| GPU | Integrated Apple M4 GPU, 10 cores, Metal supported |
| Memory | 16 GB unified memory |
| Storage | Approximately 460 GiB system filesystem; about 196 GiB available during inspection |
| Operating system | macOS 26.6.2, Apple silicon |

At capture time system-wide memory free percentage was 77%. ANVIL is best
suited to interactive operator control, source development, local validation,
and human review. It should not become the authoritative persistent control
plane or absorb dedicated server/inference duties.

## FORGE — primary powerhouse server

| Component | Verified hardware |
| --- | --- |
| CPU | AMD Ryzen 9 5900XT, 16 cores / 32 threads, boost enabled, up to approximately 5.0 GHz |
| Memory | 64 GB DDR4-3200, 4 × 16 GB Patriot Memory; no ECC reported |
| Motherboard | ASUS TUF GAMING B550-PLUS WIFI II |
| Current GPU | AMD Radeon 540/550-class display adapter (`1002:699f`) |
| Planned GPU | **CRUCIBLE** — AMD Radeon RX 9700; not installed or runtime-accepted as of this inventory |
| Primary storage | Lexar NM790 4 TB NVMe; root filesystem, about 3.5 TB available |
| Model storage | Lexar NM790 4 TB NVMe mounted at `/srv/models`, about 3.7 TB available |
| Data storage | Samsung SSD 870 2 TB SATA mounted at `/srv/data`, about 1.8 TB available |
| Additional storage | Samsung SSD 870 1 TB SATA, present but no mounted filesystem shown by this inspection |
| Wired network | Realtek RTL8125 2.5 GbE |
| Wireless network | Realtek RTL8852BE PCIe Wi-Fi 6 / 802.11ax |
| Operating system | Ubuntu 24.04.5 LTS, x86-64 |
| Kernel | Linux 7.0.0-31-generic |

At capture time FORGE had approximately 62 GiB usable memory, 1.6 GiB used,
61 GiB available, and zero use of its 8 GiB swap. Its storage layout and CPU
capacity make it the correct primary ORCA and future high-throughput inference
host. GPU inference acceptance remains blocked until CRUCIBLE (the RX 9700) is physically
installed, drivers/runtime are verified, and Fry accepts the result.

## KILN — secondary inference/support brain

| Component | Verified hardware |
| --- | --- |
| CPU | AMD Ryzen 5 4600G with integrated Radeon graphics, 6 cores / 12 threads, up to approximately 4.3 GHz |
| Memory | 32 GB DDR4-2133, 4 × 8 GB Samsung; no ECC reported |
| Motherboard | ASUS PRIME B450M-A II |
| GPU | ASUS/ASUSTeK GeForce GTX 1660 Ti (TU116), 6 GB VRAM, 120 W limit |
| GPU identifiers | PCI `10de:2182`, ASUS subsystem `1043:8840`, VBIOS `90.16.20.40.EC` |
| NVIDIA runtime | Driver 580.178.04; GPU idle at 34°C during inspection |
| Storage | Crucial P3 Plus 500 GB NVMe; 457 GB root filesystem, about 188 GB available |
| Wired network | Realtek RTL8111/8168/8411 Gigabit Ethernet |
| Operating system | Ubuntu 22.04.5 LTS, x86-64 |
| Kernel | Linux 6.8.0-138-generic |

At capture time KILN had approximately 31 GiB usable memory, 13 GiB available,
and 1.7 GiB of its 2 GiB swap in use. The 6 GB GTX 1660 Ti is appropriate for
small quantized models, embeddings, routing, and supporting inference work; it
is not sized for large-model workloads. KILN remains the secondary brain and
relay rather than the primary powerhouse.

## Intended division of labor

- FORGE: authoritative ORCA control plane, durable data/model storage, and
  future CRUCIBLE/RX-9700-backed primary inference.
- KILN: authenticated secondary inference/support node running SMITH and
  QUENCH services, plus the encrypted FORGE relay.
- ANVIL: operator worktop, development, review, and loopback console access.

This inventory records hardware facts only. It does not authorize physical
installation, remote execution, provider writes, model invocation, spending,
credential restoration, or production cutover.
