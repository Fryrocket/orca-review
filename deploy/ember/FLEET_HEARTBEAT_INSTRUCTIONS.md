# Fleet Heartbeat — Instructions for Terminal Bot / Xcode
# Fryrocket / ORCA — 2026-10-14
#
# Context: The Reliability Sentinel on EMBER only watched EMBER's loopback and
# one local recovery file. FORGE, KILN, TEMPER never appeared in any log, and
# ANVIL went "offline" Oct 10 because the heartbeat mechanism itself was broken.
# Fix: a signed per-node heartbeat agent + fleet aggregation mode in the sentinel.
#
# All new files are already on main in this repo under deploy/ember/:
#   fleet_heartbeat_agent.py          — per-node agent (health + peer ping + HMAC)
#   reliability_sentinel.py           — extended with --mode fleet
#   orca-fleet-heartbeat@.service     — templated systemd oneshot unit
#   orca-fleet-heartbeat@.timer       — 5-minute timer
#   FLEET_HEARTBEAT_RUNBOOK.md        — full deployment runbook
#
# SAFETY: observation only. No remote execution, no service restarts, no
# threshold changes. The shared HMAC secret never goes in git.

## Step 1 — Generate the shared secret (run ONCE, on any trusted machine)

   openssl rand -hex 32 > /tmp/fleet-heartbeat.secret

## Step 2 — Distribute the secret to each node (out-of-band, NOT git)

   For each node (anvil, forge, kiln, ember, temper):
     sudo install -m 0600 -o fryrocket -g fryrocket /tmp/fleet-heartbeat.secret \
         /etc/orca/fleet-heartbeat.secret

   Then shred the local copy:
     shred -u /tmp/fleet-heartbeat.secret

## Step 3 — Install the agent on each node

   sudo cp fleet_heartbeat_agent.py /usr/local/lib/orca/
   sudo chmod 755 /usr/local/lib/orca/fleet_heartbeat_agent.py
   sudo mkdir -p /var/lib/orca-fleet-heartbeat
   sudo chown fryrocket:fryrocket /var/lib/orca-fleet-heartbeat

## Step 4 — Install the systemd unit and timer on each node

   sudo cp orca-fleet-heartbeat@.service /etc/systemd/system/
   sudo cp orca-fleet-heartbeat@.timer /etc/systemd/system/
   sudo systemctl daemon-reload

   Enable for THIS node only, e.g. on ANVIL:
     sudo systemctl enable --now orca-fleet-heartbeat@anvil.timer
   On FORGE:  orca-fleet-heartbeat@forge.timer
   On KILN:   orca-fleet-heartbeat@kiln.timer
   On EMBER:  orca-fleet-heartbeat@ember.timer
   On TEMPER: orca-fleet-heartbeat@temper.timer

## Step 5 — Update the Reliability Sentinel on EMBER

   sudo cp reliability_sentinel.py /usr/local/lib/orca/

   Create a second timer for fleet mode (same pattern as the existing local one):
     orca-reliability-sentinel-fleet.service:
       ExecStart=.../reliability_sentinel.py --mode fleet \
         --secret-file /etc/orca/fleet-heartbeat.secret \
         --heartbeat-dir /var/lib/orca-fleet-heartbeat
     orca-reliability-sentinel-fleet.timer: 5-minute cadence, same as local.

## Step 6 — Verify (after ~5 minutes)

   On any node:
     cat /var/lib/orca-fleet-heartbeat/anvil.json
     # Expect: observed_epoch within last 5 min, signature present,
     # peers listed with latency_ms.

   On EMBER:
     cat /var/lib/orca-reliability-sentinel/status.json
     # Expect: mode "fleet", state "healthy", all five nodes listed.

## Notes

- TEMPER enrollment waits on its bring-up. A missing report is flagged, not
  crashed — the agent tolerates it.
- The 15-minute freshness window means a dead node surfaces within one timer
  cycle instead of sitting silently for days.
- Do NOT add auto-restart, wake-on-LAN, or remote shell. Read-only by design.
