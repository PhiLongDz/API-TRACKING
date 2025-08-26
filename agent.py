#!/usr/bin/env python3
import os, time, uuid, socket, platform, subprocess, json
import requests

# ========= Config =========
SERVER = os.environ.get("SERVER", "http://37.27.65.125:21072").rstrip("/")
APP_VERSION = "agent/3.0.0"
POST_INTERVAL = int(os.environ.get("INTERVAL", "30"))  # seconds
ID_PATH = os.path.expanduser("~/.heartbeat_id")

# ========= Optional deps (psutil) =========
# psutil cho CPU/RAM/process — thử import; nếu thiếu thì fallback đọc /proc
try:
    import psutil
    HAVE_PSUTIL = True
except Exception:
    HAVE_PSUTIL = False

# ========= Persistent client_id =========
if os.path.exists(ID_PATH):
    try:
        CLIENT_ID = open(ID_PATH, "r").read().strip()
    except Exception:
        CLIENT_ID = str(uuid.uuid4())
        open(ID_PATH, "w").write(CLIENT_ID)
else:
    CLIENT_ID = str(uuid.uuid4())
    open(ID_PATH, "w").write(CLIENT_ID)

# ========= Termux wake lock (nếu có) =========
try:
    subprocess.run(["termux-wake-lock"], check=False)
except Exception:
    pass

start_monotonic = time.monotonic()
_last_pub_ip, _last_pub_ip_at = None, 0.0

def get_public_ip(cache_secs=300):
    global _last_pub_ip, _last_pub_ip_at
    now = time.time()
    if _last_pub_ip and (now - _last_pub_ip_at) < cache_secs:
        return _last_pub_ip
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            ip = requests.get(url, timeout=6).text.strip()
            if ip:
                _last_pub_ip, _last_pub_ip_at = ip, now
                return ip
        except Exception:
            continue
    return _last_pub_ip

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

# ========= CPU/RAM =========
_prev_cpu_called = False
def cpu_percent():
    """Ưu tiên psutil, fallback /proc/stat (delta)"""
    global _prev_cpu_called
    if HAVE_PSUTIL:
        # lần đầu psutil.cpu_percent(None) trả 0.0; gọi nhanh 2 lần để có số ổn định
        if not _prev_cpu_called:
            try: 
                _ = psutil.cpu_percent(interval=None)
            except Exception:
                pass
            _prev_cpu_called = True
            time.sleep(0.1)
        try:
            return float(psutil.cpu_percent(interval=0.1))
        except Exception:
            pass
    # fallback /proc/stat
    try:
        def read():
            with open("/proc/stat", "r") as f:
                parts = f.readline().split()[1:8]
                v = list(map(int, parts))
                idle = v[3] + v[4]  # idle + iowait
                total = sum(v)
                return idle, total
        idle0, tot0 = read()
        time.sleep(0.2)
        idle1, tot1 = read()
        dt = tot1 - tot0
        didle = idle1 - idle0
        if dt <= 0: 
            return 0.0
        return max(0.0, min(100.0, (1.0 - (didle / dt)) * 100.0))
    except Exception:
        return 0.0

def ram_percent():
    if HAVE_PSUTIL:
        try:
            return float(psutil.virtual_memory().percent)
        except Exception:
            pass
    # fallback đọc MemInfo
    try:
        kv = {}
        with open("/proc/meminfo") as f:
            for ln in f:
                k, v = ln.split(":", 1)
                kv[k.strip()] = int(v.strip().split()[0])
        tot = kv.get("MemTotal", 0)
        avail = kv.get("MemAvailable", 0)
        if tot > 0:
            return ((tot - avail) / tot) * 100.0
    except Exception:
        pass
    return 0.0

# ========= Processes (ứng dụng / package / tên tiến trình) =========
def running_processes(max_items=50):
    names = []

    # A) thử psutil trước (nhanh, portable)
    if HAVE_PSUTIL:
        try:
            for p in psutil.process_iter(attrs=["name", "cmdline"]):
                nm = p.info.get("name") or ""
                if not nm and p.info.get("cmdline"):
                    nm = os.path.basename(p.info["cmdline"][0]) if p.info["cmdline"] else ""
                if nm:
                    names.append(nm)
        except Exception:
            pass

    # B) fallback dùng ps (một số máy Android hạn chế flag; thử nhiều biến thể)
    if not names:
        for cmd in (["ps", "-A", "-o", "comm"], ["ps", "-eo", "comm"], ["ps"]):
            try:
                out = subprocess.check_output(cmd, timeout=5).decode(errors="ignore")
                lines = [l.strip() for l in out.splitlines() if l.strip()]
                # bỏ header "COMMAND"/"COMM"
                lines = [l for l in lines if not l.lower().startswith(("command", "comm", "pid"))]
                for l in lines:
                    # lấy tên cuối (comm) nếu dòng có nhiều cột
                    nm = l.split()[-1] if " " in l else l
                    if nm:
                        names.append(nm)
                break
            except Exception:
                continue

    # C) Android package detection (tùy chọn: hiển thị com.xxx nếu thấy)
    # Không chạy lệnh nặng mỗi lần; để đơn giản, giữ danh sách tên tiến trình.
    # Nếu bạn muốn map "com.mojang.minecraftpe" -> "Minecraft" cần gọi Android PackageManager (khá phức tạp trong Termux).

    # dedupe, rút gọn số lượng
    seen, out = set(), []
    for nm in names:
        if nm not in seen:
            seen.add(nm)
            out.append(nm)
            if len(out) >= max_items:
                break
    return out

def main_loop():
    print(f"[agent] starting; server={SERVER}")
    print(f"[agent] client_id={CLIENT_ID}")
    hostname = socket.gethostname()
    os_name = "android" if "ANDROID_ROOT" in os.environ else platform.system().lower()
    arch = platform.machine()

    # nhịp đầu tiên: gọi cpu_percent() để có baseline
    _ = cpu_percent()

    while True:
        try:
            payload = {
                "client_id": CLIENT_ID,
                "uptime_seconds": int(time.monotonic() - start_monotonic),
                "ip_public": get_public_ip(),
                "ip_local": get_local_ip(),
                "hostname": hostname,
                "os": os_name,
                "arch": arch,
                "app_version": APP_VERSION,
                "ts": int(time.time()),  # server sẽ dùng giờ server cho last_seen, ts chỉ để tham khảo
                "cpu_pct": round(cpu_percent(), 2),
                "ram_pct": round(ram_percent(), 2),
                "processes": running_processes(50),
            }
            r = requests.post(f"{SERVER}/api/ping", json=payload, timeout=10)
            # in gọn (không spam)
            print(f"[agent] POST /api/ping -> {r.status_code}")
        except Exception as e:
            print(f"[agent] error: {e}")
        time.sleep(POST_INTERVAL)

if __name__ == "__main__":
    try:
        import platform  # used above
        main_loop()
    except KeyboardInterrupt:
        pass
