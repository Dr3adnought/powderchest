import docker
import json
import os
from datetime import UTC, datetime

import psutil
import requests

# --- CONFIGURATION ---
NODE_NAME = "Sloop (RPi 4B)"
# Path to the status folder we created in your Nginx www directory
OUTPUT_PATH = "/home/BATFE/indomitable-rapscallion/www/status/status_batfe.json"
NTFY_URL = "https://ntfy.sh/powderchest_alerts" # Change to your preferred topic
PIHOLE_SUMMARY_URL = os.getenv("PIHOLE_SUMMARY_URL", "").strip()
PIHOLE_BASE_URL = os.getenv("PIHOLE_BASE_URL", "").strip().rstrip("/")
PIHOLE_PASSWORD = os.getenv("PIHOLE_PASSWORD", "")
PIHOLE_TOTP = os.getenv("PIHOLE_TOTP", "")

def safe_float(value, default=0.0):
                timeout=3,
            )
            auth_response.raise_for_status()
            source = "http-auth"

        response = session.get(summary_url, timeout=3)
        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, dict) and isinstance(payload.get("stats"), dict):
            payload = payload["stats"]

        return {
            "status": payload.get("status", "unknown"),
            "dns_queries_today": safe_int(payload.get("dns_queries_today")),
            "ads_blocked_today": safe_int(payload.get("ads_blocked_today")),
            "ads_percentage_today": round(safe_float(payload.get("ads_percentage_today")), 2),
            "domains_being_blocked": safe_int(payload.get("domains_being_blocked")),
            "unique_clients": safe_int(payload.get("unique_clients")),
            "source": source
        }
    except requests.RequestException as exc:
        return {
            "status": "unavailable",
            "error": str(exc),
            "source": source
        }


def get_wireguard_stats():
    if not WIREGUARD_INTERFACE:
        return None

    try:
        result = subprocess.run(
            ["wg", "show", WIREGUARD_INTERFACE, "dump"],
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return {
            "interface": WIREGUARD_INTERFACE,
            "error": str(exc),
        }

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) <= 1:
        return {
            "interface": WIREGUARD_INTERFACE,
            "peers_total": 0,
            "peers_online": 0,
            "total_rx_bytes": 0,
            "total_tx_bytes": 0,
            "peers": [],
        }

    now = int(datetime.now(UTC).timestamp())
    peers = []
    total_rx = 0
    total_tx = 0
    latest_ages = []

    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) < 8:
            continue

        public_key, _, endpoint, _, latest_handshake, rx_bytes, tx_bytes, _ = fields[:8]
        handshake_timestamp = safe_int(latest_handshake)
        handshake_age = None
        if handshake_timestamp > 0:
            handshake_age = max(0, now - handshake_timestamp)
            latest_ages.append(handshake_age)

        rx_total = safe_int(rx_bytes)
        tx_total = safe_int(tx_bytes)
        total_rx += rx_total
        total_tx += tx_total

        peer_online = handshake_age is not None and handshake_age <= WIREGUARD_STALE_SECONDS
        peers.append(
            {
                "public_key_short": f"{public_key[:8]}...",
                "endpoint": endpoint or "Unknown",
                "latest_handshake_age_seconds": handshake_age,
                "rx_bytes": rx_total,
                "tx_bytes": tx_total,
                "online": peer_online,
            }
        )

    return {
        "interface": WIREGUARD_INTERFACE,
        "peers_total": len(peers),
        "peers_online": sum(1 for peer in peers if peer["online"]),
        "latest_handshake_age_seconds": min(latest_ages) if latest_ages else None,
        "total_rx_bytes": total_rx,
        "total_tx_bytes": total_tx,
        "peers": peers,
    }

def main():
    print(f"Master-at-Arms: Starting report for {NODE_NAME}...")
    
    report = {
        "node": NODE_NAME,
        "timestamp": datetime.now(UTC).isoformat(),
        "services": get_docker_stats(),
        "system": get_system_vitals()
    }

    pihole_stats = get_pihole_stats()
    if pihole_stats:
        report["pihole"] = pihole_stats

    wireguard_stats = get_wireguard_stats()
    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=4)
    
    # Simple Alerting Logic
    if "unhealthy" in report["services"].values() or "down" in report["services"].values():
        requests.post(NTFY_URL, data=f"CRITICAL: Service failure on {NODE_NAME}!", 
                      headers={"Priority": "high"})
    
    print(f"Report saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()