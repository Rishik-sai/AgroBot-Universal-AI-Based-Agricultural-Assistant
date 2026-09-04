"""Local pre-deploy verification for AgroBot. Run from the app folder."""
import os, sys, socket, subprocess, time, json, urllib.request, urllib.error

APPDIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
results = []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))

def free_port():
    s = socket.socket(); s.bind(("", 0)); p = s.getsockname()[1]; s.close(); return p

print("\n=== 1. Environment ===")
from dotenv import load_dotenv
load_dotenv(os.path.join(APPDIR, ".env"))
for var, required in [("FLASK_SECRET_KEY", True), ("WEATHER_API_KEY", True),
                      ("GEMINI_API_KEY", False), ("ADMIN_PASSWORD", True)]:
    v = os.getenv(var, "")
    check(f"{var} present", bool(v) or not required,
          f"{len(v)} chars" if v else "empty (optional)" if not required else "MISSING")

if os.getenv("WEATHER_API_KEY", "").startswith("72b6594b"):
    print("  NOTE  using the original weather key (exposed in git history) - by choice")

print("\n=== 2. Gemini API (live call) ===")
gk = os.getenv("GEMINI_API_KEY", "")
if not gk:
    check("gemini key", False, "not set - AI chat will use canned fallbacks")
else:
    try:
        from google import genai
        c = genai.Client(api_key=gk)
        from app import GEMINI_MODELS
        last = None
        for m in GEMINI_MODELS:
            try:
                r = c.models.generate_content(model=m, contents="Reply with the single word: OK")
                check(f"gemini live call ({m})", bool(r.text), (r.text or "").strip()[:40])
                last = None
                break
            except Exception as e:
                last = f"{m}: {str(e)[:70]}"
        if last:
            check("gemini live call", False, last)
    except Exception as e:
        check("gemini live call", False, f"{type(e).__name__}: {str(e)[:120]}")

print("\n=== 3. OpenWeatherMap (live call) ===")
wk = os.getenv("WEATHER_API_KEY", "")
try:
    u = f"https://api.openweathermap.org/data/2.5/weather?q=Punjab,IN&appid={wk}"
    with urllib.request.urlopen(u, timeout=20) as r:
        d = json.load(r)
    check("weather live call", True, f"{d.get('name')} temp={d.get('main',{}).get('temp')}")
except urllib.error.HTTPError as e:
    body = e.read().decode()[:100]
    hint = " (new keys need ~10 min to activate)" if e.code == 401 else ""
    check("weather live call", False, f"HTTP {e.code}: {body}{hint}")
except Exception as e:
    check("weather live call", False, f"{type(e).__name__}: {str(e)[:100]}")

print("\n=== 4. Server boot (production command) ===")
port = free_port()
log = open(os.path.join(APPDIR, "..", "verify_server.log"), "w+")
proc = subprocess.Popen(
    [PY.replace("/python", "/gunicorn"), "-k",
     "geventwebsocket.gunicorn.workers.GeventWebSocketWorker",
     "-w", "1", "-b", f"127.0.0.1:{port}", "--timeout", "120", "wsgi:app"],
    cwd=APPDIR, stdout=log, stderr=subprocess.STDOUT)
base = f"http://127.0.0.1:{port}"
up = False
for _ in range(60):
    if proc.poll() is not None:
        break
    try:
        urllib.request.urlopen(base + "/login", timeout=2); up = True; break
    except Exception:
        time.sleep(0.5)
check("gunicorn serves /login", up, "" if up else "see verify_server.log")

if up:
    print("\n=== 5. Routes ===")
    for path in ["/", "/login", "/register", "/test-key", "/check-db", "/test-gemini"]:
        try:
            with urllib.request.urlopen(base + path, timeout=25) as r:
                body = r.read(400).decode(errors="replace")
            check(f"GET {path}", r.status == 200, f"HTTP {r.status}")
            if path in ("/test-key", "/test-gemini", "/check-db"):
                print(f"        -> {body[:220]}")
        except urllib.error.HTTPError as e:
            check(f"GET {path}", False, f"HTTP {e.code}")
        except Exception as e:
            check(f"GET {path}", False, str(e)[:80])

    print("\n=== 6. Secret leak check ===")
    try:
        with urllib.request.urlopen(base + "/test-key", timeout=10) as r:
            body = r.read().decode()
        check("/test-key hides the key", wk not in body,
              "key value NOT exposed" if wk not in body else "KEY IS EXPOSED")
    except Exception as e:
        check("/test-key hides the key", False, str(e)[:80])

    print("\n=== 7. Admin login ===")
    try:
        import http.cookiejar
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj),
                                         urllib.request.HTTPRedirectHandler())
        op.open(base + "/login", timeout=15)
        import urllib.parse
        data = urllib.parse.urlencode({"email": "admin@aiagrobot.com",
                                       "password": os.getenv("ADMIN_PASSWORD", "")}).encode()
        with op.open(base + "/login", data=data, timeout=20) as r:
            final, body = r.geturl(), r.read().decode(errors="replace")
        ok = "/dashboard" in final or "logout" in body.lower() or "Invalid" not in body
        check("login with .env ADMIN_PASSWORD", ok, f"landed on {final.split(str(port))[-1]}")
    except Exception as e:
        check("login", False, str(e)[:100])

proc.terminate()
try: proc.wait(timeout=10)
except Exception: proc.kill()
log.close()

print("\n" + "=" * 46)
bad = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(bad)}/{len(results)} checks passed")
if bad:
    print("Failed: " + ", ".join(bad))
print("=" * 46)
sys.exit(1 if bad else 0)
