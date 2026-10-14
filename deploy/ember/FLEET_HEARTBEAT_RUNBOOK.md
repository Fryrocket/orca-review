# Fleet Heartbeat Deployment Runbook
# Fryrocket / ORCA — 2026-10-14
#
# Goal: every node (ANVIL, FORGE, KILN, EMBER, TEMPER) publishes a signed
# health + peer-reachability report every 5 minutes. EMBER's Reliability
# Sentinel aggregates them and flags stale/degraded/missing nodes.
#
# SAFETY: observation only. No remote execution, no service restarts,
# no threshold changes, no secrets in git or reports. The shared HMAC secret
# lives only in /etc/orca/fleet-heartbeat.secret on each node (mode 0600).

## 1. Generate the shared secret (run ONCE, on any trusted machine)
   openssl rand -hex 32 > /tmp/fleet-heartbeat.secret
   # Distribute out-of-band (SSH, not git). On each node:
   sudo install -m 0600 -o fryrocket -g fryrocket /tmp/fleet-heartbeat.secret \
       /etc/orca/fleet-heartbeat.secret
   shred -u /tmp/fleet-heartbeat.secret

## 2. Install the agent on each node
   sudo cp fleet_heartbeat_agent.py /usr/local/lib/orca/
   sudo chmod 755 /usr/local/lib/orca/fleet_heartbeat_agent.py
   sudo mkdir -p /var/lib/orca-fleet-heartbeat
   sudo chown fryrocket:fryrocket /var/lib/orca-fleet-heartbeat

## 3. Install the systemd unit + timer (per node)
   sudo cp orca-fleet-heartbeat@.service /etc/systemd/system/
   sudo cp orca-fleet-heartbeat@.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   # Enable for THIS node, e.g. on ANVIL:
   sudo systemctl enable --now orca-fleet-heartbeat@anvil.timer
   # On FORGE:  orca-fleet-heartbeat@forge.timer
   # On KILN:   orca-fleet-heartbeat@kiln.timer
   # On EMBER:  orca-fleet-heartbeat@ember.timer
   # On TEMPER: orca-fleet-heartbeat@temper.timer

## 4. Update the Reliability Sentinel on EMBER
   sudo cp reliability_sentinel.py /usr/local/lib/orca/
   # The existing orca-reliability-sentinel.timer keeps running local mode.
   # Add a second timer for fleet mode (5-min cadence, same pattern):
   #   orca-reliability-sentinel-fleet.service  ->  --mode fleet
   #                                          ->  --secret-file /etc/orca/fleet-heartbeat.secret
   #                                          ->  --heartbeat-dir /var/lib/orca-fleet-heartbeat
   # Reports land in /var/lib/orca-reliability-sentinel/status.json (mode field
   # distinguishes local vs fleet).

## 5. Verify
   # On any node, after ~5 minutes:
   cat /var/lib/orca-fleet-heartbeat/anvil.json
   # Should show observed_epoch within the last 5 min, signature present,
   # peers reachable with latency_ms.
   # On EMBER:
   cat /var/lib/orca-reliability-sentinel/status.json
   # mode "fleet", state "healthy", all five nodes listed.

## 6. What changes vs. before
   # Before: sentinel only watched EMBER's loopback + one local recovery file.
   # FORGE/KILN/TEMPER never appeared; ANVIL went "offline" Oct 10 and nobody
   # noticed because the heartbeat mechanism itself was broken.
   # After: five signed reports, 15-min freshness window, HMAC-verified,
   # peer reachability included. A dead node surfaces within one timer cycle.

## 7. Out of scope (deliberately)
   # No auto-restart, no wake-on-LAN triggering, no remote shell.
   # TEMPER enrollment waits on its bring-up; the agent tolerates a missing
   # report (flags it) rather than crashing.
