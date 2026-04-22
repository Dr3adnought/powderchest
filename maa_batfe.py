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
PIHOLE_SESSION_CACHE_PATH = os.getenv(
    "PIHOLE_SESSION_CACHE_PATH",
    "/home/BATFE/indomitable-rapscallion/.pihole_session_cache.json",
)
PIHOLE_AUTH_BACKOFF_SECONDS_RAW = os.getenv("PIHOLE_AUTH_BACKOFF_SECONDS", "300")

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


def get_nested(data, path, default=None):
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def first_present(data, paths, default=None):
    for path in paths:
        value = get_nested(data, path)
        if value is not None:
            return value
    return default


PIHOLE_AUTH_BACKOFF_SECONDS = safe_int(PIHOLE_AUTH_BACKOFF_SECONDS_RAW, 300)


def _load_pihole_session_cache():
    try:
        with open(PIHOLE_SESSION_CACHE_PATH, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_pihole_session_cache(data):
    try:
        with open(PIHOLE_SESSION_CACHE_PATH, "w") as f:
            json.dump(data, f)
    except OSError:
        # Non-fatal: the collector can still run without persistent cache.
        pass


def _session_headers_from_cache(cache):
    sid = cache.get("sid")
    expires_at = safe_int(cache.get("expires_at"), 0)
    now = int(datetime.now(UTC).timestamp())
    if not sid or now >= expires_at:
        return None
    return {"X-FTL-SID": sid}


def _authenticate_pihole(session, cache):
    now = int(datetime.now(UTC).timestamp())
    next_auth_after = safe_int(cache.get("next_auth_after"), 0)
    if now < next_auth_after:
        return None, f"auth-backoff:{next_auth_after - now}s"

    auth_payload = {"password": PIHOLE_PASSWORD}
    if PIHOLE_TOTP:
        auth_payload["totp"] = safe_int(PIHOLE_TOTP)

    auth_response = session.post(
        f"{PIHOLE_BASE_URL}/api/auth",
        json=auth_payload,
        timeout=3,
    )

    if auth_response.status_code == 429:
        cache["next_auth_after"] = now + max(60, PIHOLE_AUTH_BACKOFF_SECONDS)
        _save_pihole_session_cache(cache)
        return None, "rate-limited"

    auth_response.raise_for_status()

    auth_json = auth_response.json() if auth_response.content else {}
    session_obj = auth_json.get("session", {}) if isinstance(auth_json, dict) else {}
    sid = session_obj.get("sid")
    if not sid:
        return None, "missing-sid"

    validity = safe_int(session_obj.get("validity"), 300)
    cache["sid"] = sid
    cache["expires_at"] = now + max(30, validity - 10)
    cache["next_auth_after"] = 0
    _save_pihole_session_cache(cache)
    return {"X-FTL-SID": sid}, None


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
        request_headers = {}
        cache = _load_pihole_session_cache()

        if PIHOLE_PASSWORD and PIHOLE_BASE_URL:
            cached_headers = _session_headers_from_cache(cache)
            if cached_headers:
                request_headers = cached_headers
                source = "http-auth-cached"
            else:
                new_headers, auth_error = _authenticate_pihole(session, cache)
                if not new_headers:
                    return {
                        "status": "unavailable",
                        "error": f"Pi-hole auth unavailable ({auth_error})",
                        "source": source,
                    }
                request_headers = new_headers
                source = "http-auth"

        response = session.get(summary_url, timeout=3, headers=request_headers)

        # If a cached SID expired unexpectedly, retry once with a fresh auth.
        if response.status_code == 401 and PIHOLE_PASSWORD and PIHOLE_BASE_URL:
            cache = _load_pihole_session_cache()
            cache.pop("sid", None)
            cache["expires_at"] = 0
            _save_pihole_session_cache(cache)

            new_headers, auth_error = _authenticate_pihole(session, cache)
            if not new_headers:
                return {
                    "status": "unavailable",
                    "error": f"Pi-hole re-auth failed ({auth_error})",
                    "source": source,
                }
            request_headers = new_headers
            source = "http-auth-refresh"
            response = session.get(summary_url, timeout=3, headers=request_headers)

        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, dict) and isinstance(payload.get("stats"), dict):
            payload = payload["stats"]

        if not isinstance(payload, dict):
            return {
                "status": "unavailable",
                "error": "Unexpected Pi-hole payload type",
                "source": source,
            }

        # Pi-hole v5/v6 schema compatibility.
        status_value = first_present(payload, [
            ("status",),
            ("dns", "status"),
        ], default=None)

        if status_value is None:
            blocking = first_present(payload, [
                ("blocking",),
                ("dns", "blocking"),
            ], default=None)
            if isinstance(blocking, bool):
                status_value = "enabled" if blocking else "disabled"

        dns_queries_today = safe_int(first_present(payload, [
            ("dns_queries_today",),
            ("queries_today",),
            ("queries", "total"),
            ("dns", "queries", "total"),
        ], default=0))

        ads_blocked_today = safe_int(first_present(payload, [
            ("ads_blocked_today",),
            ("queries", "blocked"),
            ("dns", "queries", "blocked"),
        ], default=0))

        ads_percentage_today = round(safe_float(first_present(payload, [
            ("ads_percentage_today",),
            ("queries", "percent_blocked"),
            ("dns", "queries", "percent_blocked"),
        ], default=0.0)), 2)

        domains_being_blocked = safe_int(first_present(payload, [
            ("domains_being_blocked",),
            ("gravity", "domains_being_blocked"),
            ("gravity", "domains"),
        ], default=0))

        unique_clients = safe_int(first_present(payload, [
            ("unique_clients",),
            ("clients", "active"),
            ("dns", "clients", "active"),
        ], default=0))

        return {
            "status": status_value or "unknown",
            "dns_queries_today": dns_queries_today,
            "ads_blocked_today": ads_blocked_today,
            "ads_percentage_today": ads_percentage_today,
            "domains_being_blocked": domains_being_blocked,
            "unique_clients": unique_clients,
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