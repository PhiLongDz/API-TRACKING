import os, time, uuid, socket, platform, subprocess, requests

SERVER = os.environ.get("SERVER","http://127.0.0.1:8000").rstrip("/")
APP_VERSION = "agent/2.1.0"
ID_PATH = os.path.expanduser("~/.heartbeat_id")

if os.path.exists(ID_PATH):
    CLIENT_ID=open(ID_PATH).read().strip()
else:
    CLIENT_ID=str(uuid.uuid4()); open(ID_PATH,'w').write(CLIENT_ID)

try: subprocess.run(["termux-wake-lock"],check=False)
except: pass

start=time.monotonic()
_last_pub_ip,_last_pub_ip_at=None,0
_prev_cpu=None

def get_public_ip(cache_secs=300):
    global _last_pub_ip,_last_pub_ip_at
    now=time.time()
    if _last_pub_ip and (now-_last_pub_ip_at)<cache_secs: return _last_pub_ip
    for url in ("https://api.ipify.org","https://ifconfig.me/ip"):
        try:
            ip=requests.get(url,timeout=5).text.strip()
            if ip: _last_pub_ip,_last_pub_ip_at=ip,now; return ip
        except: pass
    return _last_pub_ip

def get_local_ip():
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(2)
        s.connect(("8.8.8.8",80)); ip=s.getsockname()[0]; s.close(); return ip
    except: return None

def read_cpu_times():
    try:
        line=open('/proc/stat').readline()
        parts=list(map(int,line.split()[1:11])); 
        while len(parts)<10: parts.append(0)
        idle, iowait = parts[3], parts[4]; idle_all=idle+iowait; total=sum(parts)
        return (idle_all,total)
    except: return None

def cpu_percent():
    global _prev_cpu
    cur=read_cpu_times()
    if cur is None: return None
    if _prev_cpu is None: _prev_cpu=cur; return 0.0
    idle0,tot0=_prev_cpu; idle1,tot1=cur; _prev_cpu=cur
    dt=tot1-tot0; didle=idle1-idle0
    if dt<=0: return 0.0
    return (1.0-(didle/dt))*100.0

def ram_percent():
    try:
        kv={}; 
        for ln in open('/proc/meminfo'): k,v=ln.split(':',1); kv[k.strip()]=int(v.strip().split()[0])
        tot=kv.get('MemTotal',0); avail=kv.get('MemAvailable',0)
        return ((tot-avail)/tot)*100.0 if tot>0 else None
    except: return None

def running_apps(max_items=50):
    cmds=(["ps","-A","-o","comm"],["ps","-eo","comm"],["ps"])
    for cmd in cmds:
        try:
            out=subprocess.check_output(cmd,timeout=5).decode(errors='ignore')
            lines=[l.strip() for l in out.splitlines() if l.strip()]
            lines=[l for l in lines if not l.lower().startswith(("command","comm"))]
            names=[l.split()[-1] if ' ' in l else l for l in lines]
            seen=set(); res=[]
            for n in names:
                if n not in seen: seen.add(n); res.append(n)
                if len(res)>=max_items: break
            return res
        except: pass
    return []

while True:
    payload={
        "client_id":CLIENT_ID,
        "uptime_seconds":int(time.monotonic()-start),
        "ip_public":get_public_ip(),
        "ip_local":get_local_ip(),
        "hostname":socket.gethostname(),
        "os":"android" if "ANDROID_ROOT" in os.environ else platform.system().lower(),
        "arch":platform.machine(),
        "app_version":APP_VERSION,
        "ts":int(time.time()),
        "cpu_pct":round(cpu_percent() or 0.0,2),
        "ram_pct":round(ram_percent() or 0.0,2),
        "processes":running_apps(50),
    }
    try: requests.post(f"{SERVER}/api/ping",json=payload,timeout=10)
    except: pass
    time.sleep(30)
