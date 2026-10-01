# STATE.md — v12
AS OF 2026-10-01 — live ORCA business-control expansion checkpoint.
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
- TEMPER is positively discovered on the LAN. Its Raspberry Pi Ethernet MAC is
  `88:a2:9e:35:fc:25` at `192.168.4.27`; Wi-Fi is
  `88:a2:9e:35:fc:26` at `192.168.4.25`. Fry designated `192.168.4.25` as the
  primary management address; `.27` remains the wired fallback. The stable ED25519 SSH fingerprint is
  `SHA256:rFC82HnEi91Uxz9R8LRddN2w4gHF/95+aUNKJhDk+6o`. Read-only key access
  from ANVIL verified a Raspberry Pi 5 Model B Rev 1.1, 16 GB RAM, Debian 13,
  1 TB Crucial T500 NVMe, ASMedia two-port PCIe switch and a responding Hailo-8
  running firmware 4.23.0. CPU temperature was 45.2 C with no throttling and
  root storage was 4% used. On 2026-10-01 it was renamed to `temper`, KILN was
  given a dedicated restricted relay key, and FORGE accepted its owner-enrolled
  signed heartbeat. Owner authorization on 2026-10-01 made TEMPER a full FORGE
  ecosystem member and authorized the tested ORCA core integration. Immutable
  release `35a3f35ac6cdf28727ec92a7d93e3f1c968b2dfd` is live on FORGE with
  health and integrity valid and rollback preserved to
  `66398a66c260ec455a83f5b5dcdda257bdff9c5b`. TEMPER now appears in the FORGE
  fabric with its edge-worker, sensor, MQTT, telemetry, storage and Hailo
  capabilities. The exact release passed 1,050 tests. Four packaged Hailo-8
  vision models now pass direct accelerator execution: YOLOv6n at about 140.9
  FPS, YOLOv8s at 148.22 FPS, YOLOv5n segmentation at 61.32 FPS and YOLOv8s
  pose at 228.5 FPS. These are hardware-only measurements, not end-to-end
  camera latency. TEMPER's read-only Hailo/USB-camera inventory timer is live,
  refreshes every minute, reports the device and compatible H8 artifacts, and
  now identifies the connected UVC HDMI/USB capture camera as the single usable
  `/dev/video0` stream while excluding its `/dev/video1` metadata companion.
  The accepted input profile is MJPEG 1280x720 at 30 FPS, resized to 640x640 at
  5 FPS for bounded inference. The local-only signed
  job broker is active with a single accelerator queue, HMAC authentication,
  monotonic nonce replay protection, pinned models and input roots, 150-frame
  and 90-second limits, hashed artifacts and metadata-only evidence. One signed
  synthetic job through each model passed; a tampered signature was rejected
  without advancing the nonce, and the broker recovered to healthy with zero
  restarts. On 2026-10-01 a no-save ten-frame capture probe passed, followed by
  signed ten-frame jobs through YOLOv6n, YOLOv8s, YOLOv5n segmentation and
  YOLOv8s pose. All four completed in 1.158-1.252 seconds, wrote metadata only,
  performed no external action, and left both services at zero restarts. Peak
  observed CPU temperature was 51.0 C. The supplied 960x1280 JPEG fixture then
  exposed a still-image end-of-stream timeout; it failed closed with preserved
  evidence and no external action. The broker was corrected to use a bounded
  image-freeze stage, and the same SHA-256-pinned image passed all four models
  in 0.734-0.767 seconds. It produced metadata only, recovered with zero
  restarts, and remained at 49.9 C. ORCA exposes the governed edge catalog and
  recommends TEMPER for vision, sensor and future audio workloads. Signed
  bounded camera and approved-file inference are accepted; autonomous
  execution, custom models and business workflow activation remain gated.
  ORCA now also exposes a read-only `temper.plan_inference_workflow` tool. It
  maps a registered Inventory, Engineering, Canvas, Product Builder, Operations,
  Business, BGM or Studio workflow to compatible pinned models, required
  evidence and explicit prohibitions without enqueuing a job. Inventory visual
  counting remains paused until the operator declares the exact label scope;
  PCB, receiving, listing, safety, sensor and audio work remains blocked until
  an appropriate custom Hailo-8 model is validated. A six-check disposable
  workflow simulation passed with zero frames captured, jobs queued or external
  actions.

- TEMPER Watch is registered in ORCA and visible in Bot Monitor but remains
  inactive pending its recovery and soak gates. Its former discovery/hardware
  blocker is resolved. The authoritative
  A-to-Z completion checklist now lives on the existing TEMPER Notion page.
  Gates A-C are complete: the read-only authority contract, TEMPER identity and
  hardware baseline, and bounded Hailo/camera/file inference acceptance. The
  D-P software phase completed on 2026-10-01. TEMPER now runs a read-only,
  network-blocked `orca-temper-watch.timer` every minute under the unprivileged
  `fryrocket` account with strict filesystem, kernel, memory and CPU limits.
  Its versioned evidence contract maps signed heartbeat, Pi/NVMe resources,
  Hailo inventory and artifact hashes, the one-job inference broker, MQTT, and
  sensor/offline-queue state. Freshness, thermal, memory, swap, disk, queue and
  failure thresholds are explicit. Drift, replay, malformed data, stale input,
  missing secure MQTT, throttling and resource exhaustion fail visibly without
  self-repair. Negative-permission and thirteen-step disposable fault
  simulations passed; the full ORCA regression passed 1,060 tests. The first
  live report completed with zero restarts and zero external actions. CPU,
  NVMe, memory, swap, disk, camera, four Hailo model hashes, secure MQTT and the
  bounded broker were healthy. It truthfully reported two expected warnings:
  the temporary anonymous MQTT transition listener remains active and no
  accepted sensor stream/offline queue exists yet. Network/service recovery is
  next at Q-R.
  Safe unattended recovery work then added a disposable Q sequence: stale
  heartbeat, unavailable credentialed MQTT and buffered sensor data produced a
  critical exception-only report; fresh reconnection returned healthy with a
  distinct evidence hash, no duplicate report, no data loss, no live network
  change and zero external actions. The production monitor now has bounded
  `Restart=on-failure` behavior (five-second delay, three attempts per five
  minutes). A controlled TEMPER-Watch-only timer interruption reached inactive,
  restored active, generated fresh evidence and retained zero restarts; ORCA,
  MQTT, Hailo and TEMPER networking were not interrupted. The expanded full
  regression passed 1,061 tests. Q remains open for a real bounded interface
  loss/reconnect test, and R remains open for a true failure-triggered automatic
  restart; neither should risk unattended loss of remote control.
  Supervised reboot and iPhone credentialed-MQTT cutover require Fry at the
  hardware/phone. Custom-model foundations and PCB inspection require governed
  datasets and representative labelled images. TEMPER-only and five-node soaks,
  independent review, owner approval, rollback-safe activation and record
  reconciliation remain the final gates. TEMPER Watch may observe and stage an
  alert only; it may not use a remote shell, restart services, change models,
  publish MQTT, perform physical action, approve work or deploy.

- Google Drive received a recoverable organization pass on 2026-10-01. A dated
  `_ARCHIVE/ORCA-FORGE Archive — 2026-10-01` container now holds historical and
  explicitly superseded project records; nothing was deleted or trashed. The
  duplicate lowercase `forge` container was retired after its stable Connectors
  folder moved into the canonical `Forge` folder. Loose PCB procurement,
  optimization, inventory and ORCA test-video artifacts moved into their
  existing QuasarVolt or Bench Inventory destinations. Active FORGE build and
  emergency guides moved into canonical `Forge`; historical Forge ZIP/TAR
  bundles and duplicate decision notes moved into the dated archive. Twenty-one explicitly
  superseded `cc-bridge` records moved into the dated archive while current
  handoffs, IDs, active business folders and personal folders remained intact.

- Inventory barcode scanning is live in ORCA release
  `a915527981434785efc1ca8ad847e8fc08feace7`. It supports common USB and
  Bluetooth HID scanners, rapid scan
  capture, SKU and alias lookup, counted-quantity aggregation, and governed
  receiving and transfer handoffs. UPC-A, EAN-8, EAN-13 and GTIN-14 check
  digits are validated; common AIM prefixes are normalized; unknown or invalid
  codes fail visibly and never change stock. Count adjustments, receiving and
  transfers still require ORCA's existing review and approval paths. The full
  regression suite passed 1,068 tests before the subsequent TEMPER dataset
  expansion. Physical scanner acceptance on KILN remains open, but the parser,
  routing and Inventory UI are live; no scanner is required for ORCA startup.

- TEMPER visual-inventory dataset planning is live in ORCA release
  `a915527981434785efc1ca8ad847e8fc08feace7`. The new read-only planner produces deterministic,
  SHA-256-identified manifests tied to exact inventory SKUs and barcodes,
  bounded 70/15/15 train-validation-test targets, camera/background/lighting
  coverage, hard negatives, two-pass label review, near-duplicate split
  isolation, provenance and ownership requirements, and explicit precision,
  recall and count-error gates. People, identity and sensitive-trait labels are
  rejected. Unknown items must abstain for review, and the canonical inventory
  ledger remains authoritative. Planning cannot capture images, train a model,
  deploy a model or change stock. The expanded TEMPER simulation passed seven
  checks with zero captures, dataset writes, training, jobs or external action;
  the complete ORCA regression passed 1,075 tests. The live planner probe
  produced a deterministic manifest, exposed the registered tool handler and
  retained capture, training, deployment and stock mutation as false. The
  dataset/model itself remains unbuilt pending representative labelled images.
  FORGE health and integrity are valid with zero ORCA restarts. Rollback points
  to `/opt/orca/releases/35a3f35ac6cdf28727ec92a7d93e3f1c968b2dfd`.
  The first post-activation probe used the wrong barcode result-field name and
  stopped without changing the healthy service; the corrected UPC-A, dataset,
  edge-API, UI and KILN-gateway probes all passed.

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
- No push, merge, spending, credential change, or connector scope expansion was
  performed. The tested ORCA tree was activated on FORGE as immutable release
  `/opt/orca/releases/35a3f35ac6cdf28727ec92a7d93e3f1c968b2dfd`; release
  `/opt/orca/releases/66398a66c260ec455a83f5b5dcdda257bdff9c5b` remains the
  `/var/lib/orca/previous-release` rollback target.

## 2026-09-30 LOCAL IMPLEMENTATION DELTA

- The live worktree was already dirty. Existing media-cancellation, gateway,
  heartbeat, benchmark, personality, and math changes remain user-owned and
  were preserved.
- The Business workspace now has dedicated Legal Command Center, Connections &
  AI Paths, Accounting Control Center, Budget Control Center, and final
  Concept-to-Sale Acceptance Simulation surfaces.
- Legal workflows cover entity and registrations, contracts, product and
  marketplace compliance, intellectual property, privacy and consumer duties,
  and counsel-ready evidence. They draft and organize; they cannot sign, file,
  certify, contact authorities, or replace licensed advice.
- The connection map treats Google Drive as artifact storage, Notion as durable
  operating context, Linear as executable work, GitHub/Gitea as code history,
  QUENCH as independent review, and commerce providers as staged read-first
  integrations. Staged connectors must never be reported as live.
- ChatGPT Finances is represented truthfully as a future owner-authorized,
  read-only financial-data source through Plaid. The connection is made in
  ChatGPT, not ORCA. ORCA receives no bank credentials or Plaid tokens. Until
  the owner connects an eligible account and a read-only probe passes, its
  state remains `unconnected`.
- Budget workflows cover operating budgets, rolling cash flow and runway,
  budget-to-actual variance, product economics, project and capital budgets,
  and an exception-only owner dashboard. Money movement, bill payment, trades,
  account changes, tax filing, and professional financial conclusions remain
  prohibited.
- Active default model routes now reflect the accepted architecture: governed
  Codex on KILN is primary for coding and documentation, local Qwen is the
  fallback and primary large reasoner, QUENCH independently reviews, and SMITH
  stays retired. TEMPER has a live read-only Hailo capability catalog and
  automatic camera discovery; execution remains broker- and acceptance-gated.
- A planned ORCA Executive Orchestrator is now documented as the cross-business
  priority and delegation layer. It may maintain the operating picture,
  decompose authorized goals, assign bounded work, coordinate dependencies,
  prevent duplicates, monitor progress, and escalate exceptions. It receives
  no new authority: Fry remains the sole approval authority, and the executive
  cannot override policy, lane isolation, independent review, or core controls.
- Bot Monitor is a separate Studio sidebar workspace. It presents bot identity,
  position, duty, route, runtime state, activity frequency, assignments, last
  activity, tool count, failures, incidents, and recent evidence, and can stage
  an owner briefing. Monitoring is read-only; schedule, permission, pause, and
  stop changes continue through the control plane and approval policy.
- The local role catalog now registers an ordered solo-operator bot crew:
  Reliability Sentinel, Recovery Marshal, Connector Steward, Evidence Auditor,
  Security Watch, Budget Officer, Legal and Compliance Clerk, Inventory
  Steward, Product Scout, Product Development Lead, Channel Operator, Creative
  Director, TEMPER Watch, Browser Operator, Daily Briefing Officer, and
  Continuity Keeper. Bot Monitor includes registered roles so planned, gated,
  active, paused and failed identities are visible instead of disappearing.
  All new crew roles default inactive, have explicit activation gates, cannot
  approve R3 work or deploy, and retain role-specific prohibitions for money,
  publishing, legal conclusions, secrets, backup deletion, physical action and
  external communication. Continuity Keeper's external heartbeat is active,
  but its ORCA role remains gated until the candidate is deployed and reconciled.
- The planned ORCA Keychain uses KILN's OS keyring for live secrets and a
  separately encrypted recovery vault for versioned recovery material. Bots
  receive only purpose-bound credential injection through an allowlisted broker;
  they cannot enumerate, display, copy, export, prompt, log, screenshot, or
  remember secrets. Routine read-only/open actions may use standing capability
  grants for unattended remote operation. New credentials, expanded scopes,
  recovery, rotation, deletion, money, legal acceptance, publishing, security,
  and account changes require authenticated remote owner approval.
- ChatGPT Pro Library is planned as a tertiary continuity and disaster-recovery
  layer, not the authoritative backup. Prepare a curated recovery manifest,
  source/configuration bundles, checksums, restore instructions and encrypted
  archive parts below ChatGPT's per-file limit; keep the decryption key in a
  separate recovery escrow. Exclude plaintext secrets, browser profiles,
  personal/financial records and raw backup repositories. Upload requires a
  signed-in ChatGPT browser session. Acceptance requires upload inventory,
  checksum verification, documented retention limits and a disposable restore
  drill. EMBER Restic plus its independent encrypted offsite mirror remain the
  complete machine-recovery path.
- KILN live verification on 2026-09-30 found `/usr/bin/google-chrome-stable`,
  version `154.0.8037.57`. The dedicated-profile path was not asserted by that
  command and remains subject to the launcher/profile acceptance test.
- TEMPER is a live FORGE-lane ecosystem member and remains paused from
  autonomous workloads until network/MQTT ACLs, telemetry depth,
  model provenance, recovery, fault, and dedicated soak acceptance pass.
  Discovery, MAC/address binding, SSH fingerprint, Pi 5, memory, 1 TB NVMe,
  PCIe, Hailo-8, hostname, restricted KILN relay and signed-heartbeat gates are
  verified. ORCA reports TEMPER healthy and authenticated with evidence
  integrity valid. Its Hailo-8 hardware is live and four packaged H8 `.hef`
  artifacts pass direct accelerator execution. Their ORCA model catalog is
  live. The signed bounded job broker, all four synthetic post-processing paths,
  the physical camera profile and signed camera jobs through all four models are
  accepted. The user-supplied JPEG fixture also passes signed bounded file
  inference through all four models with input/model hashes and metadata-only
  output. Custom models and autonomous workflows remain gated by provenance and
  per-workflow acceptance.
  The read-only camera inventory service is active with zero restarts, excludes
  the Pi's internal codec devices and the camera's UVC metadata companion, and
  reports one connected USB camera at `/dev/video0`.
  Credentialed listener 41883 now enforces an `armband/#` topic ACL. Authenticated
  round-trip, forbidden-topic denial and anonymous-denial probes passed, and the
  local logger was moved to 41883 with an automatic rollback copy retained.
  Listener 1883 still accepts anonymous LAN clients only as a compatibility
  bridge for the installed iPhone build. The iOS source now requires Keychain
  credentials on LAN in local commit `d9aa741`, with 50/50 Swift tests and both
  MQTT contract checks passing; it is not installed on the phone yet. The
  firmware already supports authenticated MQTT. Install and verify the iOS
  build before closing anonymous 1883. Model, recovery, fault and soak gates
  follow.
- EMBER was audited live on 2026-09-30. The signed heartbeat, FORGE loopback
  tunnel, NUT UPS driver/server/monitor, read-only OLED, wake guard, Tailscale,
  and FORGE-VIS backup services were active. The local encrypted Restic backup
  completed successfully, verified 25 snapshots, sampled data packs, and found
  no repository errors. The root SSD was 42% used, memory had about 7.1 GiB
  available, swap was unused, and CPU temperature was about 37 C.
- EMBER's 2026-09-30 Google Drive `RATE_LIMIT_EXCEEDED` defect was repaired with
  throttling, bounded retries and delayed verification. The prior script is
  retained at `/usr/local/sbin/orca-offsite-sync.previous-20260930`. The live
  copy-only/immutable job completed successfully: 92 encrypted files matched,
  zero differences were found, and no remote deletion occurred. A disposable
  Restic restore of `orca-ember-node.service` passed checksum verification; the
  retained evidence is `/var/lib/orca-backup/restore-drill-latest.json` and the
  restored sample is under `/var/lib/orca-backup/restore-drill-p7sqYF`. A
  controlled restart of `orca-forge-tunnel.service` also recovered normally on
  its loopback-only port, returned a healthy integrity-valid ORCA response, and
  left the signed EMBER heartbeat active. Power-loss/reboot recovery and
  exception-only stale-backup alert acceptance remain open before final EMBER
  hardening can be declared complete.
- The final business simulation is planned as disposable and no-spend. It spans
  concept, evidence, product design, BOM, sourcing, manufacturing plan,
  inventory, media, listing drafts, marketing, legal, accounting, mock sale,
  fulfillment, return, close, reporting, recovery, and archive. It must stop on
  integrity, authority, thermal, resource, repeated-service, or unexplained
  mutation failure.
- The complete regression suite passed 945 tests before the initial bot-crew
  activation. The live FORGE service remains healthy with valid integrity and
  zero restarts; KILN's gateway exposes the 29-role catalog and a previous
  release is preserved.
- A later ordered acceptance pass activated seven narrow read-only roles:
  Recovery Marshal, Connector Steward, Evidence Auditor, Security Watch,
  Budget Officer, Legal and Compliance Clerk, and Inventory Steward. Their
  focused acceptance suite passed 26/26 on 2026-09-30. All seven systemd timers
  are active; their most recent one-shot services exited successfully with no
  restart loops. Live evidence reports healthy state, no money movement, no
  external contact or filing, no stock mutation or shipment, no secret-content
  read, and no connector writes. Connector runtime read paths remain explicitly
  `unproven`; Budget and Legal are truthfully waiting for approved inputs.
  Remaining crew roles are still inactive and gated. This activation is out of
  the recorded rollout order because Reliability Sentinel remains inactive
  while steps 2-8 are active; no further crew activation should occur until the
  owner reviews that sequencing contradiction. The current live release is
  `/opt/orca/releases/continuity-policy-20260930-v1`; it adds append-only,
  versioned conversation checkpoints that remain context rather than authority
  or execution evidence. Its rollback pointer
  is `/opt/orca/releases/memory-save-first-20260930-8473f70`.
- The legacy `smith` evidence identity still appears in the live core-bot list
  even though the SMITH model service is retired; correcting that durable
  identity/runtime presentation changes core activation semantics and remains
  blocked pending explicit owner review. Qwen and Codex routing are unchanged.
- No financial, legal, commerce or provider account was newly connected or
  changed by this release.

## 2026-10-01 RECONCILIATION

- The complete local regression suite passes 972/972 tests. The only initial
  collection failure was a recovery-marshal test importing from the wrong
  directory; the test now resolves the deployed EMBER helper explicitly and
  the full suite passes without exclusions.
- Live read-only verification found KILN and FORGE healthy with valid integrity
  and zero service restarts. The active release remains
  `/opt/orca/releases/continuity-policy-20260930-v1`; the actual preserved
  rollback pointer is
  `/opt/orca/releases/memory-save-first-20260930-8473f70`.
- The disposable ORCA total A-to-Z simulation is complete and accepted: 26/26
  stages and 54/54 nested checks passed with no failed stages. Safety evidence
  records zero deployments, external writes, messages, money movement,
  production inventory changes, publications, or purchases. Linear FOR-17 was
  closed with the retained evidence path
  `/var/lib/orca/total-simulation-latest.json`.
- Fourteen narrow governed crew roles are active. Reliability Sentinel is now
  truthfully active in ORCA after its isolated EMBER runtime, authority
  boundaries, focused checks, complete regression, live health and rollback
  path were accepted. The ordered rollout contradiction in FOR-11 is resolved;
  Product Scout, Product Development Lead, Channel Operator and Creative
  Director have now passed their gates. TEMPER Watch is next in the ordered
  stack but remains blocked until TEMPER identity and hardware acceptance;
  Browser Operator and Daily Briefing Officer have passed their gates;
  Continuity Keeper is the next actionable role.
- EMBER's remaining hardening gates are the supervised physical power-loss and
  reboot drill plus exception-only stale-backup alert acceptance. These require
  owner availability and were not attempted remotely.
- TEMPER is positively discovered, renamed, authenticated, publishing a healthy
  signed heartbeat and deployed as a FORGE fabric member in release
  `a5eb12efc83559c0a226b34f60321154fb361713`. It remains safely paused from
  autonomous jobs until the iOS credentialed-LAN build is installed, anonymous
  1883 is closed, an approved Hailo model exists, and offline queue, recovery,
  fault and dedicated soak acceptance are established. The credentialed 41883
  listener and TEMPER's local logger have passed their ACL and connectivity
  cutover tests.
- The Notion To Do database has been cleaned of its starter tutorial rows. Its
  only genuine standalone task remains the comprehensive ORCA/Forge operator
  and developer manual after stable operation.
- Reliability Sentinel is installed as an isolated read-only systemd timer on
  EMBER and is active in ORCA's role catalog under the accepted gate
  `read_only_telemetry_and_exception_reporting_accepted_20261001`. Its live
  report is healthy with no findings or actions taken; the timer and ORCA
  service have zero restarts. Focused checks passed 10/10 and the complete suite
  passed 973/973. Live release:
  `/opt/orca/releases/reliability-sentinel-20261001-active`; rollback:
  `/opt/orca/releases/continuity-policy-20260930-v1`.
- Product Scout is active in the live ORCA catalog under gate
  `cited_synthetic_product_research_accepted_20261001`. Its isolated FORGE
  timer is enabled and healthy, its first live cycle completed successfully,
  and it is waiting for an owner-approved candidate pack. It has no network
  access and recorded zero purchases, vendor contacts, publications, external
  actions or invented sales estimates. Focused Product Scout, role and
  heartbeat checks passed 44/44; the complete suite passed 980/980. The live
  release is `/opt/orca/releases/product-scout-20261001-active`, with
  `/opt/orca/releases/reliability-sentinel-20261001-active` preserved as the
  rollback target. Both ORCA and Product Scout report zero restarts.
- The acceptance run exposed an intermittent first-run heartbeat nonce-lock
  race. The lock initialization now serializes on the validated parent
  directory before publishing the sibling lock file; the concurrent stress
  reproduction passed 25/25 and the repair is included in the live release.
- Product Development Lead is active under gate
  `bounded_product_engineering_and_review_accepted_20261001`. Its bounded FORGE
  worker and corrected product classifier passed 22/22 focused checks and the
  complete suite passed 987/987. The protected live acceptance for the Pi 5
  Hi-Fi Guardian HAT selected all seven required product, industrial, quality,
  supply, electrical, firmware and mechanical tracks, retained all ten lifecycle
  phases and eight open requirements, and kept the product an unreleased concept.
  Purchases, supplier contacts, inventory allocations, manufacturing releases,
  deployments and external actions were all zero. KILN's independent Evidence
  Auditor verified the exact live artifact checksum and owner-approval reference.
  ORCA and the worker have zero restarts. Live release:
  `/opt/orca/releases/product-development-lead-20261001-active`; rollback:
  `/opt/orca/releases/product-scout-20261001-active`.
- Channel Operator is active under gate
  `draft_only_multichannel_acceptance_20261001`. Its sandboxed FORGE worker
  prepared six synthetic drafts for website, Shopify, Amazon, eBay, Alibaba and
  Temu with exact channel economics, shared-availability mapping and required
  approval gates. Focused channel, role, inventory and Business checks passed
  47/47; the final activation and math/A-to-Z gate passed 43/43; the complete
  ORCA suite passed 996/996. Listings published, live price changes, orders
  submitted, customer messages, refunds, shipments, inventory reservations,
  spend and external actions were all zero. KILN's independent Evidence Auditor
  verified the exact live report checksum and owner approval. ORCA and the
  worker have zero restarts. Live release:
  `/opt/orca/releases/channel-operator-20261001-active`; rollback:
  `/opt/orca/releases/product-development-lead-20261001-active`.
- The full-suite run exposed an order-dependent exact-math defect: Decimal's
  inherited `Inexact` signal could make an exact fraction appear approximate.
  The calculator now clears inherited flags for each calculation, a dedicated
  regression proves `1/3 + 1/6 = 1/2` remains exact after unrelated Decimal
  work, and the A-to-Z simulator's math stage passes.
- Creative Director is active under gate
  `draft_media_provenance_and_claim_review_accepted_20261001`. Its
  network-denied FORGE worker accepted a synthetic QuasarVolt Guardian HAT
  brief and staged reproducible CRUCIBLE manifests for one 1024-square product
  image and one 73-frame short video. It retained brand rules, source-rights
  declaration, claim evidence, prompts, negative prompts, seeds, model names,
  output paths and manifest checksums. No image or video was generated during
  this acceptance. Focused media, broker, Business and role checks passed
  80/80; the complete ORCA suite passed 1004/1004. Generation, publication,
  uploads, paid ads, spend, likeness use, asset licensing, unsupported claims
  and external actions were all zero. KILN's independent Evidence Auditor
  verified the exact acceptance artifact checksum. CRUCIBLE's live broker
  reports healthy SDXL generation/editing plus Wan text-to-video,
  image-to-video and MP4 export. ORCA has zero restarts and valid integrity.
  Live release: `/opt/orca/releases/creative-director-20261001-active`;
  rollback: `/opt/orca/releases/channel-operator-20261001-active`.
- Browser Operator is active under gate
  `private_ephemeral_page_read_and_action_boundary_accepted_20261001`. Live
  KILN audit verified Google Chrome `154.0.8037.57`, the owner-only dedicated
  ORCA profile and the fixed desktop launcher. The controller reads only public
  HTTPS pages in a separate ephemeral WebKit context; a fixed loopback origin
  exists solely for acceptance. Page text is capped at 50,000 characters and
  passed to reasoning as explicitly untrusted reference material. Downloads
  and device permissions are denied. Non-web URLs, embedded credentials,
  public HTTP, literal private-network targets, secret-shaped form values,
  paths outside ORCA Projects, unapproved profiles and external-action
  permission fail closed. A disposable live page returned the expected title
  and 88-character body, and KILN's Evidence Auditor verified its checksum.
  Focused browser/launcher/role checks pass 56/56 and the complete ORCA suite
  passes 1018/1018. Forms submitted, uploads, downloads, purchases, messages,
  publications, account changes, credentials read and external actions are all
  zero. KILN Studio restarted cleanly; ORCA integrity is valid with zero
  restarts. Live release: `/opt/orca/releases/browser-operator-20261001-active`;
  rollback: `/opt/orca/releases/browser-controller-candidate-20261001`.
- Daily Briefing Officer is active in the live ORCA role catalog under gate
  `cross_source_truthful_owner_briefing_accepted_20261001`. Its
  isolated, network-denied FORGE worker compiled a disposable six-source owner
  briefing covering completed work, failures, approvals, money, inventory,
  fleet health and owner-set priorities. It preserved the exact priority order,
  exposed all unhealthy-source failures, and recorded zero hidden failures,
  priority changes, approvals granted, notifications and external actions.
  Focused briefing and role checks passed 13/13 and the complete ORCA suite
  passed 1025/1025. KILN's independent Evidence Auditor verified the runtime
  artifact checksum. The first activation attempt rolled back automatically
  because the immediate health probe ran before ORCA reopened its port. The
  bounded startup grace period then activated the exact same tested release
  successfully. KILN and FORGE both report healthy state with valid integrity;
  ORCA and the worker have zero restarts. The worker is truthfully waiting for
  an approved summary pack, and its timer is active for 07:00 America/Chicago.
  Live release: `/opt/orca/releases/daily-briefing-officer-20261001-candidate`;
  rollback: `/opt/orca/releases/browser-operator-20261001-active`.
- Linear FOR-12 and FOR-15 are closed as accepted. Their live Legal, Accounting
  and Budget surfaces, read-only workers, negative authority boundaries, full
  regression and zero-effect simulation evidence passed. Real financial feeds,
  legal conclusions and consequential actions remain unconnected or gated.
- Recovery Marshal now emits an explicit exception-only `alert_required` signal:
  healthy evidence stays silent, while stale, missing, malformed or failed
  evidence requests an alert. The live EMBER report is healthy and silent, so
  FOR-18 now waits only for the supervised physical power-loss/reboot drill.
- Linear starter issues FOR-1 through FOR-4 were canceled as vendor onboarding
  placeholders. Missing execution work is now tracked explicitly as FOR-19
  through FOR-26: KILN app/artifact handoffs, voice/headset acceptance, media
  playback, Ubuntu maintenance, QuasarVolt external readiness, the Pi 5 Hi-Fi
  Guardian HAT, the post-TEMPER eight-hour five-node soak, and the final
  operator/developer manual.
- TEMPER inventory-vision foundations are live in ORCA release
  `/opt/orca/releases/a52aac436cbbe7274144d2e3c47c56d3dbf80dc2`, with
  `/opt/orca/releases/a915527981434785efc1ca8ad847e8fc08feace7`
  preserved as rollback. Inventory now includes an SKU/barcode-bound label-set
  manager and deterministic capture-session planner. The read-only tool layer
  adds capture planning, dataset validation for balance, exact duplicates,
  cross-split perceptual-hash leakage, provenance, privacy and two-pass review,
  plus Hailo-8 conversion and model-registry planning. The expanded disposable
  dataset-to-deployment simulation passed 13/13 with zero captured frames,
  writes, training jobs, conversions or deployments. Focused checks passed
  47/47 and the complete suite passed 1080/1080. A live planner request returned
  the expected 35/8/7 split, eight capture scenarios, deterministic hashes and
  all execution gates closed. FORGE and the KILN gateway are healthy with valid
  integrity; ORCA has zero restarts. Physical capture, training, HEF conversion,
  registry approval and deployment remain separate future gates.
- The unattended-safe acceptance layer is live in ORCA release
  `/opt/orca/releases/7b5020a137a0bfef08f73b2c5e63aea94b0d02b3`, with
  `/opt/orca/releases/a52aac436cbbe7274144d2e3c47c56d3dbf80dc2`
  preserved as rollback. FORGE is healthy with valid integrity and zero ORCA
  restarts; KILN's gateway and FORGE tunnel are active.
  It runs the TEMPER Watch D-P fault matrix, a disposable network-loss and
  recovery sequence, the inventory dataset-to-Hailo-8 planning path, bot
  negative-authority validation, and fake opaque-reference credential-broker
  checks without changing live state. Its first run passed 5/5, performed zero
  external actions, and produced a six-event redacted hash chain with head
  `90a45bca7809361d2cd7407b43843c412e82e6e3f94b213a0cad3788aa1c0fc4`.
  The same harness then ran from the activated FORGE release and passed 5/5;
  retained evidence is
  `/var/lib/orca/unattended-acceptance/unattended-20261001T184849Z.jsonl`
  with valid six-event head
  `363fa789f200a1df17f89873c0388871ea464f19301b12a7257b3fc868b46373`.
  The shared run-evidence writer detects tampering and redacts credential-like
  fields. Sensitive broker requests still require authenticated owner approval;
  the test never accessed a real keychain or secret. The recovery drill was
  corrected to restore `deploy`, `desktop`, and frozen benchmark assets as part
  of the modern ORCA release surface. A fresh isolated reconstruction then
  passed all 854 restored v1 checks, package installation, state recovery,
  signed-node expiry, emergency-stop exercise, and evidence verification. The
  complete source suite passed 1097/1097. Real SKU selection and image capture,
  physical scanner/headset checks, live interface loss, restart/reboot or power
  loss, iPhone MQTT cutover, model conversion, registry approval, and deployment
  remain explicitly outside unattended acceptance.
- The private ORCA External Test Lab is live at
  `https://orca-external-test-lab.fryrocket621688.chatgpt.site/`. The expanded
  browser acceptance run passed **128/128** tests across 14 categories with no
  failures or skips. The verified result includes navigation, responsive UI,
  accessibility, form and approval boundaries, browser storage, error states,
  download behavior, recovery behavior, evidence integrity, and disposable
  business-path simulations. The repaired download produced a real browser
  download event for the session-scoped JSON fixture. Evidence SHA-256:
  `1227c1528671677f533b104185b9cf151f4411aaa2f4514c05224f984d8d0242`.
  Site source commit: `aa4bf9b0c3b21e560b75fecd6b15ddc668486c13`;
  deployed version:
  `appgprj_6abeabc02fd48191b71132c8bdd1d9bd~appgver_91b64e2f98048191a4874a6b62b81d0f`.
- Autonomous-security phase one is implemented locally and documented in
  `docs/AUTONOMOUS_SECURITY_BASELINE_2026-10-01.md`. A new deterministic
  `orca.autonomous_security` policy covers ANVIL, FORGE, KILN, EMBER, and
  TEMPER; classifies listener scope, firewall state, SSH policy, unattended
  updates and login-abuse throttling; produces redacted evidence fingerprints;
  and generates rollback-first, non-executing firewall plans. It explicitly
  separates unattended containment and bounded stateless-service recovery from
  owner-gated firewall, trust, credential, reboot, deletion, money, legal,
  publishing and external-contact actions. Focused security checks passed
  **18/18** and the complete source suite passed **1,103/1,103**.
- Autonomous-security activation is now **live and verified** on all four Linux
  nodes. Each node used saved configuration, a five-minute automatic rollback,
  source-scoped UFW rules, a fresh independent key-based SSH session and
  service-specific probes before rollback cancellation. KILN, FORGE, EMBER and
  TEMPER now run fail2ban and security-only unattended updates with automatic
  reboot disabled. FORGE and TEMPER are key-only with root SSH disabled; KILN
  and EMBER retained their already-correct key-only policy.
- KILN's persistent Docker `DOCKER-USER` chain blocks Redis from the LAN and
  restricts Gitea and MinIO to the management LAN or Tailscale. Its protected
  port attestation lets unprivileged Security Watch distinguish a blocked
  container socket from a real exposure; a Docker unit dependency re-applies
  the filter after future Docker restarts. The live report is healthy with zero
  findings and the required services have zero restarts. FORGE ORCA and Gitea,
  EMBER backup/UPS/relay paths, and every required KILN route remained healthy.
- TEMPER retired anonymous MQTT 1883 after proving the authenticated 41883
  client reconnected. Its prior Watch unit had an invalid start-limit policy
  for a frequent successful oneshot; the unit is corrected and no longer enters
  `start-limit-hit`. Network readiness now waits for actual connectivity rather
  than every profile. A bounded unprivileged camera probe reads one frame to
  `/dev/null`, stores only health metadata, retains no imagery and feeds TEMPER
  Watch. The current Watch report is healthy with zero exceptions; HailoRT,
  Pironman, telemetry, dashboard, broker and signed heartbeats remain healthy at
  about 49°C.
- Security work is tracked in Linear **FOR-29** and the matching Notion To Do
  page. The Forge infrastructure, ORCA additive-expansion, TEMPER, and EMBER
  Notion pages carry their scoped findings and next gates. Google Drive's
  existing `STATE_v12_upload.md` was updated in place, and the standalone
  baseline was added to the canonical Forge folder. Local Git checkpoint:
  `b7ebd4d`. The GitHub review branch was not updated because the destination's
  privacy and access posture has not yet been verified for internal network and
  security-posture documentation; no alternate export was attempted.
- KILN's live read-only Security Watch was corrected so an inactive firewall
  can no longer produce a false healthy report. Its prior script is preserved
  at `/usr/local/lib/orca/orca_security_watch.py.pre-autonomous-security-20261001`.
  The timer remains active with zero restarts; after firewall activation and the
  Docker protected-port attestation, the current report is `healthy`, has zero
  findings, reads no secret content, and applies no changes.
- A delayed acceptance cycle exposed and repaired a second evidence-only issue:
  the Docker filter remained effective, but its attestation lived under `/run`
  and could disappear during service lifecycle cleanup. The root-produced
  attestation now lives in persistent systemd-managed state under `/var/lib`,
  the watcher consumes that path, focused checks pass, and a subsequent live
  watcher run again reports `healthy` with zero findings.
- Owner direction now establishes the normal operating policy: every node with
  a fresh authenticated healthy heartbeat should be active. ANVIL, FORGE,
  KILN, EMBER and TEMPER were explicitly resumed through ORCA's revision-checked
  control path; the live pause list is empty. Safety pauses still engage during
  a real outage and are cleared only after fresh healthy evidence.
- Sequential reboot/recovery drills passed on TEMPER, EMBER, FORGE and KILN.
  TEMPER recovered HailoRT, Pironman, telemetry and all scheduled workers.
  FORGE recovered ORCA, integrity, Gitea, its database and both in-review jobs.
  KILN recovered its gateway, heartbeat, containers, Docker firewall,
  persistent attestation and Security Watch. EMBER's first drill exposed a
  boot-time Tailscale tunnel race; its tunnel now uses bounded connection
  attempts and automatic retry. A second reboot proved automatic tunnel,
  signed-heartbeat, UPS, backup, recovery and monitoring recovery.
- The final soak runner uses bounded 33-frame video samples and explicitly does
  not submit the previously rejected 49- or 73-frame jobs.
- Final source regression passed **1,117/1,117**. ORCA `/api/health` returned
  healthy with valid integrity. ANVIL, FORGE, KILN, EMBER and TEMPER all report
  fresh signed healthy heartbeats, and the Linux nodes show no failed units.
  ANVIL's application firewall and FileVault are on; stealth mode remains the
  only host-firewall setting requiring owner-present macOS authorization.
  The live ORCA pause list is empty and all five nodes are healthy and active.
- Meta Muse integration is now a tested local candidate and is **not deployed
  live during the active eight-hour soak**. Personal Muse shopping is handled
  through an authenticated ORCA Business handoff that creates a deterministic
  research-only prompt, fixed official URL, handoff ID, cited candidate-pack
  return contract, and explicit zero-purchase, zero-message, zero-publication
  and zero-credential boundary. A separate email handoff may read, classify,
  group, minimally summarize and draft replies from owner-connected authorized
  mail, but cannot send, reply, forward, delete, archive, move, label, mark spam,
  unsubscribe, open attachments, click links, change account settings or expose
  credentials. Email and attachments are always untrusted input. ORCA does not claim an undocumented personal
  Muse API. Meta's separate OpenAI-compatible Muse Spark Model API is recorded
  as an optional staged provider and remains disabled until owner-controlled
  credentials, cost approval and outbound-data acceptance exist. Focused Muse,
  Business and web tests passed **57/57**; the complete source regression passed
  **1,125/1,125**. Deployment and live validation remain gated behind successful
  soak completion and continuity-record reconciliation.
- A dedicated first-class ORCA **Inbox** workspace is now a tested local
  candidate and is not yet deployed. The sidebar surface provides owner-only
  authenticated reading of privacy-minimized email summaries, sender, subject,
  project/customer association, category, priority, deadlines, follow-ups,
  uncertainty and reply drafts, with search and filters. Returned Muse packages
  are schema-bounded, secret-scanned, idempotent and conflict-protected before
  import into an owner-mode `0600` SQLite store. ORCA stores no raw message
  bodies or attachments and performs no sends, deletes, moves, labels, link
  clicks or mailbox changes. Focused Inbox, Muse, Business and web checks pass
  **62/62** and the complete source regression passes **1,130/1,130**. A real
  mailbox remains unconnected; until an accepted connector exists, summaries
  enter only through the governed Muse return package. Deployment and live
  acceptance remain behind the active soak gate.
- A separate first-class ORCA **Communications Hub** is now implemented as a
  tested local candidate and is not deployed during the active soak. It builds
  on the minimized Inbox records rather than creating a second mailbox. Its
  deterministic read-only operating view produces customer/vendor timelines,
  an owner-review follow-up queue, calendar candidates, suspicious-summary
  quarantine and one exception-oriented daily communications brief. It uses
  ORCA's existing Connector Steward, Evidence Auditor, Legal and Compliance
  Clerk and Daily Briefing Officer lanes instead of creating an overlapping
  autonomous bot. It performs zero sends, mailbox mutations, calendar writes,
  contact writes, link opens or attachment opens; consequential external
  actions remain separately approval-gated. Focused Communications, Inbox,
  Muse and web acceptance passed **41/41**, JavaScript syntax and patch checks
  passed, and the complete source regression passed **1,134/1,134**. A live
  mailbox and calendar remain unconnected. Deployment and live acceptance stay
  behind successful soak completion and continuity-record reconciliation.
- The existing `orca-continuity-checkpoint` heartbeat now includes the five-node
  autonomous-security posture and FOR-29. It remains active every six hours,
  stays quiet while state is healthy and unchanged, and may perform only
  bounded read-only checks, disposable simulations, evidence verification, and
  non-destructive recovery checks. Firewall activation, SSH/credential/trust
  changes, major updates, reboots, deletion and consequential external actions
  retain their separate verified activation gates.

END STATE.md — AS OF 2026-10-01
