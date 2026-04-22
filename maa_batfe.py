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
    services = {}
    targets = ["mc-portal", "velocity-proxy"]

    try:
        client = docker.from_env()
    except Exception:
        return {name: "unknown" for name in targets}

    for name in targets:
        try:
            container = client.containers.get(name)
            state = container.attrs["State"]
            health = state.get("Health", {}).get("Status", state.get("Status"))
            services[name] = health
        except Exception:
            services[name] = "down"
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


def get_pihole_stats():
    summary_url = PIHOLE_SUMMARY_URL
    if not summary_url and PIHOLE_BASE_URL:
        summary_url = f"{PIHOLE_BASE_URL}/api/stats/summary"

    if not summary_url:
        return None

    source = "http"

    try:
        session = requests.Session()

        if PIHOLE_PASSWORD and PIHOLE_BASE_URL:
            auth_payload = {"password": PIHOLE_PASSWORD}
            if PIHOLE_TOTP:
                auth_payload["totp"] = safe_int(PIHOLE_TOTP)

            auth_response = session.post(
                f"{PIHOLE_BASE_URL}/api/auth",
                json=auth_payload,
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
            "source": source,
        }
    except requests.RequestException as exc:
        return {
            "status": "unavailable",
            "error": str(exc),
            "source": source,
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

    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=4)
    
    # Simple Alerting Logic
    if "unhealthy" in report["services"].values() or "down" in report["services"].values():
        requests.post(NTFY_URL, data=f"CRITICAL: Service failure on {NODE_NAME}!", 
                      headers={"Priority": "high"})
    
    print(f"Report saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()