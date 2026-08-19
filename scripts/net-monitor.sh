#!/usr/bin/env bash
# net-monitor.sh — dual-WAN link health monitor (Personal .1 vs Claro .2).
#
# Born 2026-08-19: the Personal gateway (192.168.1.1) showed multi-day packet
# loss (user observed 60% bursts) that cloud tools never surface — API calls
# just get slower. Default route was moved to the Claro gateway (192.168.1.2),
# but first egress-IP checks showed BOTH gateways NATing out through the same
# Telecom/Personal public IP — so this monitor exists to map each link's real
# behavior over time, not just assume the labels.
#
# Probes, per cycle (all four pinned by host routes so the default route
# doesn't matter — recreate with:
#   nmcli con mod "Wired connection 1" \
#     +ipv4.routes "1.1.1.1/32 192.168.1.1" \
#     +ipv4.routes "8.8.8.8/32 192.168.1.2" ):
#   - each gateway itself (LAN reachability: distinguishes router-down from
#     upstream loss)
#   - one internet target pinned through each gateway (1.1.1.1 via .1,
#     8.8.8.8 via .2)
# Every EGRESS_EVERY cycles it also logs the public egress IP per link
# (ifconfig.me pinned via .1, api.ipify.org pinned via .2) — this is what
# will show the moment the Claro WAN actually comes up as a distinct upstream.
#
# Output: one status line per cycle to the log; ALERT lines when internet-path
# loss >= LOSS_WARN% or a gateway stops answering. Grep the log, don't trust
# a wrapper (process-lesson from the sweep incident, CLAUDE.md 2026-08-18).
#
# Usage: setsid nohup ./net-monitor.sh >> "$LOG" 2>&1 &
# Env: NET_MON_INTERVAL (s, default 15), NET_MON_PINGS (default 10),
#      NET_MON_LOSS_WARN (%, default 10), NET_MON_EGRESS_EVERY (default 40)

set -u

# All link parameters are env-overridable (nothing hardcoded to one LAN --
# the 2026-08-19 Claro cutover renumbered the whole subnet under this script's
# feet). Leave NET_MON_GW_B empty for single-link mode: the B-side probes and
# the shared-egress comparison are skipped entirely.
GW_A=${NET_MON_GW_A:-192.168.1.1}; NAME_A=${NET_MON_NAME_A:-personal}; TGT_A=${NET_MON_TGT_A:-1.1.1.1}
GW_B=${NET_MON_GW_B-192.168.1.2}; NAME_B=${NET_MON_NAME_B:-claro};    TGT_B=${NET_MON_TGT_B:-8.8.8.8}   # NET_MON_GW_B= (empty) -> single-link
ECHO_A_IP=${NET_MON_ECHO_A_IP:-34.160.111.145};  ECHO_A_HOST=${NET_MON_ECHO_A_HOST:-ifconfig.me}    # pinned via GW_A
ECHO_B_IP=${NET_MON_ECHO_B_IP:-104.26.12.205};   ECHO_B_HOST=${NET_MON_ECHO_B_HOST:-api.ipify.org}  # pinned via GW_B

INTERVAL=${NET_MON_INTERVAL:-15}
PINGS=${NET_MON_PINGS:-10}
LOSS_WARN=${NET_MON_LOSS_WARN:-10}
EGRESS_EVERY=${NET_MON_EGRESS_EVERY:-40}

# probe <target> -> "lost/total avg_rtt_ms" (rtt "-" when all lost)
probe() {
    local out lost="?" total="?" rtt="-"
    out=$(ping -n -q -c "$PINGS" -i 0.2 -W 1 "$1" 2>/dev/null)
    if [[ $out =~ ([0-9]+)\ packets\ transmitted,\ ([0-9]+)\ received ]]; then
        total=${BASH_REMATCH[1]}
        lost=$(( total - BASH_REMATCH[2] ))
    fi
    if [[ $out =~ =\ [0-9.]+/([0-9.]+)/ ]]; then
        rtt=${BASH_REMATCH[1]}
    fi
    echo "$lost/$total $rtt"
}

loss_pct() { # "lost/total ..." -> integer percent (0 when unparsable)
    local lt=${1%% *}
    local lost=${lt%%/*} total=${lt##*/}
    [[ $lost =~ ^[0-9]+$ && $total =~ ^[0-9]+$ && $total -gt 0 ]] || { echo 0; return; }
    echo $(( lost * 100 / total ))
}

egress_ip() { # <pinned_ip> <hostname> -> public IP or "-"
    curl -s --max-time 8 --resolve "$2:443:$1" "https://$2" 2>/dev/null | head -c 64
}

cycle=0
echo "NET-MONITOR start $(date +%FT%T) links=$NAME_A${GW_B:+,$NAME_B} interval=${INTERVAL}s pings=$PINGS warn=${LOSS_WARN}% pid=$$"
while :; do
    ts=$(date +%FT%T)
    gwa=$(probe "$GW_A"); ina=$(probe "$TGT_A")
    specs=("$NAME_A:$gwa:gw" "$NAME_A:$ina:inet")
    line="$ts $NAME_A gw=${gwa% *} inet=${ina% *} rtt=${ina#* }"
    if [[ -n $GW_B ]]; then
        gwb=$(probe "$GW_B"); inb=$(probe "$TGT_B")
        specs+=("$NAME_B:$gwb:gw" "$NAME_B:$inb:inet")
        line+=" | $NAME_B gw=${gwb% *} inet=${inb% *} rtt=${inb#* }"
    fi
    echo "$line"

    for spec in "${specs[@]}"; do
        name=${spec%%:*}; rest=${spec#*:}; kind=${rest##*:}; res=${rest%:*}
        p=$(loss_pct "$res")
        if (( p >= LOSS_WARN )); then
            echo "ALERT $ts $name $kind loss ${p}% (${res%% *})"
        fi
    done

    if (( cycle % EGRESS_EVERY == 0 )); then
        ea=$(egress_ip "$ECHO_A_IP" "$ECHO_A_HOST")
        if [[ -n $GW_B ]]; then
            eb=$(egress_ip "$ECHO_B_IP" "$ECHO_B_HOST")
            echo "EGRESS $ts $NAME_A=${ea:--} $NAME_B=${eb:--}"
            if [[ -n $ea && $ea == "$eb" ]]; then
                echo "EGRESS-NOTE $ts both links share one public IP ($ea) — same upstream right now"
            fi
        else
            echo "EGRESS $ts $NAME_A=${ea:--}"
        fi
    fi
    cycle=$((cycle + 1))
    sleep "$INTERVAL"
done
