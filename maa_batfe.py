import docker
import psutil
import requests
import json
import time
from datetime import datetime

# --- CONFIGURATION ---
NODE_NAME = "BATFE"
# Path to the status folder we created in your Nginx www directory
OUTPUT_PATH = "/home/BATFE/indomitable-rapscallion/www/status/status_batfe.json"
NTFY_URL = "https://ntfy.sh/powderchest_alerts" # Change to your preferred topic

def get_docker_stats():
    client = docker.from_env()
    services = {}
    # Containers to watch
    targets = ["mc-portal", "velocity-proxy"]
    
    for name in targets:
        try:
            container = client.containers.get(name)
            state = container.attrs['State']
            # Get the 'healthy' status or fall back to the basic 'status'
            health = state.get('Health', {}).get('Status', state.get('Status'))
            services[name] = health
        except Exception:
            services[name] = "down"
    return services

def get_system_vitals():
    # CPU Temp
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = int(f.read()) / 1000
    
    return {
        "cpu_temp": f"{temp:.1f}C",
        "cpu_usage": f"{psutil.cpu_percent()}%",
        "memory_usage": f"{psutil.virtual_memory().percent}%",
        "net_io": psutil.net_io_counters(pernic=False).bytes_sent + psutil.net_io_counters(pernic=False).bytes_recv
    }

def main():
    print(f"Master-at-Arms: Starting report for {NODE_NAME}...")
    
    report = {
        "node": NODE_NAME,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "services": get_docker_stats(),
        "system": get_system_vitals()
    }
    
    # Save to the Nginx web directory
    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=4)
    
    # Simple Alerting Logic
    if "unhealthy" in report["services"].values() or "down" in report["services"].values():
        requests.post(NTFY_URL, data=f"CRITICAL: Service failure on {NODE_NAME}!", 
                      headers={"Priority": "high"})
    
    print(f"Report saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()