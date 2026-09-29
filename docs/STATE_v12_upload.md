# STATE.md — v12
AS OF 2026-09-27T0035Z — live fleet refresh and CRUCIBLE integration start.
Supersedes v11 (2026-09-24T1447Z). Read this FIRST every session.

## AUTHORITY AND SAFETY

- Fry remains the human authority for push, merge, deployment, cutover, provider
  writes, spend, secrets, deletion, and production-impacting action.
- ORCA model invocation, remote execution, connector writes, automatic failover,
  and production cutover remain disabled.
- Historical dated reports are evidence. This file and the newest verified
  `cc-bridge` handoff carry the current operational summary.

## VERIFIED LIVE CONNECTIONS

- ANVIL: `192.168.4.20`; Apple M4 MacBook Pro, 10 CPU/GPU cores, 16 GB memory.
- KILN: `192.168.4.28`; Tailscale `100.97.193.39`; Ubuntu 22.04.5; Ryzen 5
  4600G; 31 GiB; BILLOWS GTX 1660 Ti 6 GB, driver 580.178.04.
- FORGE: private anchor `192.168.7.30`; wired LAN `192.168.4.29`; Wi-Fi
  `192.168.4.30`; Ubuntu 24.04.5; Ryzen 9 5900XT; 62 GiB; about 10.3 TiB raw
  storage. ORCA and Docker are active; ORCA listens on loopback only and Gitea
  listens on `192.168.7.30:3000`.
- EMBER: `192.168.4.26`; Tailscale `100.87.165.66`; Raspberry Pi 4, 8 GB,
  512 GB USB SSD. CyberPower UPS is online at 100% charge and 4% load with
  7,025 seconds estimated runtime; no NUT errors appeared in the last 30 minutes.
- TEMPER was not proven online during this refresh. Do not infer a live address.

## CRUCIBLE AND GPU STATUS

- CRUCIBLE is installed on FORGE and identifies as **AMD Radeon AI PRO R9700**,
  32,624 MB GDDR6, 64 compute units, `gfx1201`, full x16 link.
- amdgpu is active; AMD SMI 26.2.2 and ROCm 7.2.1 enumerate the device.
- A 24 GB VRAM pattern test and a 30-second sustained HIP test passed with zero
  observed ECC, reset, or Xid-class errors. Peak observed hotspot was 87°C and
  VRAM 61°C, below the device slowdown thresholds.
- CRUCIBLE is hardware/runtime/load accepted. It is **not** an active ORCA model
  endpoint. Model/runtime selection, a post-reboot model test, QUENCH independent
  review, and Fry's activation decision remain open.
- BILLOWS is the device name for KILN's GTX 1660 Ti, not a separate host.

## CONNECTION REPAIRS

- ANVIL `kiln` SSH alias now uses `192.168.4.28`; `kiln-ts` remains the durable
  Tailscale route.
- KILN `forge` now uses the stable `192.168.7.30` private link. `forge-mdns`
  remains an explicit fallback and `forge-wifi` now uses `192.168.4.30`.
- Verified SSH fingerprints matched across each machine's alternate paths before
  stale address trust records were replaced. Backups were retained.

## ORCA WORKTREE

- Repository: `/Users/fryrocket/claude-server/orca-rebuild`, branch
  `agent/orca-rebuild-v1`.
- The worktree contained substantial existing modified/untracked work before
  this refresh. Do not discard or reset it.
- The active registry now records CRUCIBLE as installed ROCm compute hardware,
  BILLOWS by device name, and the verified host addresses. Large GPU inference
  stays blocked because no accepted model-serving capability is registered.
- No push, merge, deploy, service cutover, or connector-runtime enablement was
  performed by this refresh.

END STATE.md — AS OF 2026-09-27T0035Z
