import os, time, uuid, json, socket, platform, subprocess
import requests

SERVER = os.environ.get("SERVER", "http://127.0.0.1:8000")
SECRET = os.environ.get("SECRET", "CACCONCON")
APP_VERSION = "agent/1.1.0"
ID_PATH = os.path.expanduser("~/.heartbeat_id")

# Persistent client_id
if os.path.exists(ID_PATH):
    with open(ID_PATH, 'r') as f: CLIENT_ID = f.read().strip()
else:
    CLIENT_ID = str(uuid.uuid4())
    with open(ID_PATH, 'w') as f: f.write(CLIENT_ID)

# Optional: keep device awake if termux-wake-lock exists
try:
    subprocess.run(["termux-wake-lock"], check=False)
except Exception:
    pass

start = time.monotonic()

_last_pub_ip = None
_last_pub_ip_at = 0

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def get_public_ip(cache_secs=300):
    global _last_pub_ip, _last_pub_ip_at
    now = time.time()
    if _last_pub_ip and (now - _last_pub_ip_at) < cache_secs:
        return _last_pub_ip
    try:
        _last_pub_ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
        _last_pub_ip_at = now
        return _last_pub_ip
    except Exception:
        try:
            _last_pub_ip = requests.get("https://ifconfig.me/ip", timeout=5).text.strip()
            _last_pub_ip_at = now
            return _last_pub_ip
        except Exception:
            return _last_pub_ip  # may be None

while True:
    uptime = int(time.monotonic() - start)
    payload = {
        "client_id": CLIENT_ID,
        "uptime_seconds": uptime,
        "ip_public": get_public_ip(),
        "ip_local": get_local_ip(),
        "hostname": socket.gethostname(),
        "os": ("android" if "ANDROID_ROOT" in os.environ else platform.system().lower()),
        "arch": platform.machine(),
        "app_version": APP_VERSION,
        "ts": int(time.time()),
    }
    try:
        r = requests.post(f"{SERVER}/api/ping", json=payload, timeout=10, headers={"X-Auth": SECRET})
        # print(r.status_code)
    except Exception:
        pass
    time.sleep(30)
