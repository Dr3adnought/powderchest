import docker
import json
import os
import psutil
import requests
from datetime import UTC, datetime

# --- CONFIGURATION ---
NODE_NAME = "Galleon (RPi 5)"
LOCAL_OUTPUT_PATH = "/mnt/data/maa-monitoring/status_applepi.json"
BATFE_RECEIVER_URL = "http://192.168.0.114:5000/update-status"

WG_EASY_BASE_URL = os.getenv("WG_EASY_BASE_URL", "http://localhost:51821").rstrip("/")
WG_EASY_PASSWORD = os.getenv("WG_EASY_PASSWORD", "")
WG_EASY_STALE_SECONDS = int(os.getenv("WG_EASY_STALE_SECONDS", "180"))


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_docker_stats():
    targets = [
        "mc-server", "mc-teen", "skynet", "ollama",
        "open-webui", "pihole", "wg-easy", "unbound",
    ]
    try:
        client = docker.from_env()
    except Exception:
        return {name: "unknown" for name in targets}

    services = {}
    for name in targets:
        try:
            container = client.containers.get(name)
            state = container.attrs["State"]
            health = state.get("Health", {}).get("Status", state.get("Status"))
            services[name] = health
        except Exception:
            services[name] = "offline"
    return services


def get_system_vitals():
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = int(f.read()) / 1000

    disk = psutil.disk_usage("/")
    net_io = psutil.net_io_counters(pernic=False)

    return {
        "cpu_temp": f"{temp:.1f}C",
        "cpu_usage": f"{psutil.cpu_percent()}%",
        "memory_usage": f"{psutil.virtual_memory().percent}%",
        "disk_usage": f"{disk.percent}%",
        "disk_free_gb": round(disk.free / (1024 ** 3), 1),
        "net_io_total_bytes": net_io.bytes_sent + net_io.bytes_recv,
    }


def get_wireguard_stats():
    if not WG_EASY_PASSWORD:
        return None

    try:
        session = requests.Session()

        # Authenticate — wg-easy takes the plaintext password and compares
        # it internally against its bcrypt hash.
        auth_resp = session.post(
            f"{WG_EASY_BASE_URL}/api/session",
            json={"password": WG_EASY_PASSWORD},
            timeout=5,
        )
        if auth_resp.status_code not in (200, 204):
            return {
                "error": f"wg-easy auth failed: HTTP {auth_resp.status_code}",
            }

        # Fetch client list
        clients_resp = session.get(
            f"{WG_EASY_BASE_URL}/api/wireguard/client",
            timeout=5,
        )
        clients_resp.raise_for_status()
        clients = clients_resp.json()

        now = datetime.now(UTC)
        peers = []
        total_rx = 0
        total_tx = 0

        for c in clients:
            rx = safe_int(c.get("transferRx"))
            tx = safe_int(c.get("transferTx"))
            total_rx += rx
            total_tx += tx

            handshake_age = None
            online = False
            latest = c.get("latestHandshakeAt")
            if latest:
                try:
                    # wg-easy returns ISO 8601; Python needs timezone-aware parse
                    hs_time = datetime.fromisoformat(latest.replace("Z", "+00:00"))
                    handshake_age = int((now - hs_time).total_seconds())
                    online = handshake_age <= WG_EASY_STALE_SECONDS
                except ValueError:
                    pass

            peers.append({
                "name": c.get("name", "unknown"),
                "enabled": c.get("enabled", False),
                "address": c.get("address", ""),
                "latest_handshake_age_seconds": handshake_age,
                "rx_bytes": rx,
                "tx_bytes": tx,
                "online": online,
            })

        return {
            "peers_total": len(peers),
            "peers_online": sum(1 for p in peers if p["online"]),
            "total_rx_bytes": total_rx,
            "total_tx_bytes": total_tx,
            "peers": peers,
        }

    except requests.RequestException as exc:
        return {"error": str(exc)}


def main():
    print(f"Master-at-Arms: Starting report for {NODE_NAME}...")

    report = {
        "node": NODE_NAME,
        "timestamp": datetime.now(UTC).isoformat(),
        "services": get_docker_stats(),
        "system": get_system_vitals(),
    }

    wireguard_stats = get_wireguard_stats()
    if wireguard_stats is not None:
        report["wireguard"] = wireguard_stats

    # Save locally
    with open(LOCAL_OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=4)

    # Beam to BATFE
    try:
        response = requests.post(
            BATFE_RECEIVER_URL,
            json=report,
            timeout=10,
        )
        if response.status_code == 200:
            print(f"Report beamed successfully at {report['timestamp']}")
        else:
            print(f"Receiver responded with error: {response.status_code}")
    except Exception as e:
        print(f"Failed to beam report: {e}")


if __name__ == "__main__":
    main()
