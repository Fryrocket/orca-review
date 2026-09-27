# ORCA FORGE deployment evidence — 2026-09-24

## Placement

- **FORGE:** authoritative ORCA host; future RX9700 runtime host after separate hardware/runtime acceptance.
- **KILN:** worker node and private SSH relay; it does not own ORCA state.
- **ANVIL:** operator workstation; it accesses the console only through a persistent loopback tunnel.
- **EMBER:** monitoring/backup node; no ORCA state or service was placed there.
- **IRIS:** remains unproven and outside this deployment.

## Release

- Source commit: `28340bdaabb65d673352c9b0df1f51f52754b459`
- Release archive SHA-256: `24739afde586780b5cb946d0cdf097a941768660a0576a6e5a7634b6f733b8fe`
- Installed path: `/opt/orca/releases/28340bdaabb65d673352c9b0df1f51f52754b459`
- Active symlink: `/opt/orca/current`
- Persistent state: `/var/lib/orca/orca-events.db`
- Host-local identity tokens: `/var/lib/orca/identity-tokens.json`; generated on FORGE, mode `0600`, values never printed or copied.

## Service boundary

- System service: `orca.service`, enabled and active on FORGE.
- Bind: `127.0.0.1:8787` only.
- Service hardening includes `NoNewPrivileges`, private temporary storage, strict system protection, owner-only umask, empty capability bounding set, and `/var/lib/orca` as the only writable application path.
- Direct KILN/LAN connection to `192.168.7.30:8787` was refused as intended.
- KILN service `orca-forge-tunnel.service` binds only `127.0.0.1:18787` and forwards through its existing dedicated Forge SSH identity.
- ANVIL LaunchAgent `com.fryrocket.orca-forge-tunnel` binds only `127.0.0.1:8787` and forwards through KILN.

## Verification

- FORGE hardware inventory: Ryzen 9 5900XT (16 cores/32 threads), 62 GiB RAM, approximately 3.7 TB root, 3.7 TB model volume, and 1.8 TB data volume. Existing Radeon 550-class display GPU remains; RX9700 installation is future work.
- `orca.service`: enabled and active.
- `/api/health`: `healthy`, integrity valid, from FORGE, KILN relay, and ANVIL operator endpoint.
- ANVIL console HTML loaded through the private tunnel.
- Database SHA-256 was unchanged across a service restart; restart health passed.
- Database and identity-token files are mode `0600`; state directory is mode `0700`.
- Evidence chain valid; zero active jobs; zero write-enabled connectors.
- All fleet nodes start `unproven`; remote execution is disabled for every node.

## Rollback

1. `sudo systemctl stop orca.service` on FORGE.
2. Point `/opt/orca/current` to the path stored in `/var/lib/orca/previous-release` when a previous release exists; this first deployment has no predecessor.
3. Preserve `/var/lib/orca` and its checksum before any restore; never delete it as part of rollback.
4. `sudo systemctl daemon-reload && sudo systemctl start orca.service`, then require loopback health and integrity checks.

## Remaining gates

This is an observation-mode deployment, not cutover acceptance. Connector writes, provider mutations, model calls, spending, remote commands, automated scheduling/delivery, and GPU runtimes remain disabled. RX9700 installation/driver/runtime testing, authenticated node heartbeat enrollment, IRIS onboarding, trusted external evidence, provider credential restoration/rotation, and controlled failure/recovery drills remain open.
