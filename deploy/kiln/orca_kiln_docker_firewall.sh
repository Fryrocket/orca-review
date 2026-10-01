#!/bin/sh
set -eu

IPT=/usr/sbin/iptables
IP6T=/usr/sbin/ip6tables
CHAIN=ORCA-DOCKER-FILTER
LAN=192.168.4.0/22
PUBLISHED_PORTS=2222,3000,6379,9000,9001
ATTESTATION=/var/lib/orca-kiln-docker-firewall/protected-ports.json

$IPT -N "$CHAIN" 2>/dev/null || true
$IPT -F "$CHAIN"
$IPT -C DOCKER-USER -j "$CHAIN" 2>/dev/null || $IPT -I DOCKER-USER 1 -j "$CHAIN"
$IPT -A "$CHAIN" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
$IPT -A "$CHAIN" -i docker0 -j RETURN
$IPT -A "$CHAIN" -i br+ -j RETURN
$IPT -A "$CHAIN" -i enp8s0 -p tcp --dport 6379 -j DROP
$IPT -A "$CHAIN" -i enp8s0 -s "$LAN" -p tcp -m multiport --dports 2222,3000,9000,9001 -j ACCEPT
$IPT -A "$CHAIN" -i tailscale0 -p tcp -m multiport --dports 2222,3000,9000,9001 -j ACCEPT
$IPT -A "$CHAIN" -p tcp -m multiport --dports "$PUBLISHED_PORTS" -j DROP
$IPT -A "$CHAIN" -j RETURN

if $IP6T -nL DOCKER-USER >/dev/null 2>&1; then
    $IP6T -N "$CHAIN" 2>/dev/null || true
    $IP6T -F "$CHAIN"
    $IP6T -C DOCKER-USER -j "$CHAIN" 2>/dev/null || $IP6T -I DOCKER-USER 1 -j "$CHAIN"
    $IP6T -A "$CHAIN" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
    $IP6T -A "$CHAIN" -i docker0 -j RETURN
    $IP6T -A "$CHAIN" -i br+ -j RETURN
    $IP6T -A "$CHAIN" -i tailscale0 -p tcp -m multiport --dports 2222,3000,9000,9001 -j ACCEPT
    $IP6T -A "$CHAIN" -p tcp -m multiport --dports "$PUBLISHED_PORTS" -j DROP
    $IP6T -A "$CHAIN" -j RETURN
fi

umask 0022
temporary="${ATTESTATION}.tmp"
printf '{"firewall":"ORCA-DOCKER-FILTER","protected_public_ports":[6379],"schema_version":1}\n' >"$temporary"
mv "$temporary" "$ATTESTATION"
