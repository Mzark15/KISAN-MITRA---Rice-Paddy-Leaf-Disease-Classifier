#!/usr/bin/env python3
"""Kisan Mitra dev CLI: run the backend, build the test APK and try photos from one place.

    py kisan.py serve              start the backend for your phone (guest mode, all interfaces)
    py kisan.py apk                point the app at this laptop and build the debug APK
    py kisan.py all                apk, then serve
    py kisan.py check              is the backend up, are the models loaded?
    py kisan.py diagnose PATH...   send photos (or a folder) to the backend, show the verdict
    py kisan.py ip                 this laptop's LAN address
    py kisan.py firewall           the one-time command that lets your phone reach the laptop

Standard library only; run it from anywhere. `py kisan.py <command> -h` shows each command's options.
"""

import argparse
import json
import mimetypes
import os
import random
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
WEB_ENV = os.path.join(ROOT, "web", ".env.local")
APK_BUILT = os.path.join(ROOT, "android", "app", "build", "outputs", "apk", "debug", "app-debug.apk")
APK_OUT = os.path.join(ROOT, "dist", "KisanMitra-test.apk")
MODELS = os.path.join(BACKEND, "models")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
IS_WIN = os.name == "nt"


def say(msg: str = "") -> None:
    print(msg, flush=True)


def lan_ips() -> list[str]:
    """Best guess first: the address of the default route, then every other private IPv4."""
    ips = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # UDP connect sends nothing; it just picks the outgoing interface
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith(("127.", "169.254.")):
                ips.append(ip)
    except OSError:
        pass
    return ips


def load_dotenv() -> None:
    """Read .env from the project root (existing environment variables win)."""
    path = os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def base_url(args) -> str:
    if getattr(args, "url", None):
        return args.url.rstrip("/")
    return f"http://{(lan_ips() or ['127.0.0.1'])[0]}:{getattr(args, 'port', 8000)}"


# ---------------------------------------------------------------- commands

def cmd_ip(args) -> int:
    ips = lan_ips()
    if not ips:
        say("No network address found. Are you on Wi-Fi?")
        return 1
    say(f"Use this one first: {ips[0]}")
    for ip in ips[1:]:
        say(f"also seen:          {ip}")
    return 0


def cmd_firewall(args) -> int:
    say("Windows blocks incoming connections on 'Public' networks. Open PowerShell as Administrator and run:\n")
    say(f'  New-NetFirewallRule -DisplayName "Kisan Mitra {args.port}" -Direction Inbound '
        f"-Protocol TCP -LocalPort {args.port} -Action Allow -Profile Any\n")
    say("Then check from your phone's browser:  http://<laptop-ip>:%d/healthz" % args.port)
    return 0


def cmd_serve(args) -> int:
    load_dotenv()
    env = os.environ.copy()
    if not args.login:
        env["AUTH_DISABLED"] = "1"  # guest mode: no Cognito login needed
    env.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

    missing = [f for f in ("crop_gate.tflite", "crop_gate.json", "model_meta.json") if not os.path.isfile(os.path.join(MODELS, f))]
    if missing:
        say(f"WARNING: missing in backend/models/: {', '.join(missing)}. Without the gate every image gets a disease prediction.")

    ips = lan_ips()
    say("Kisan Mitra backend")
    say(f"  this laptop : http://localhost:{args.port}/healthz")
    for ip in ips[:2]:
        say(f"  phone / LAN : http://{ip}:{args.port}/healthz")
    say(f"  guest mode  : {'off (login required)' if args.login else 'on (AUTH_DISABLED=1)'}")
    say("  stop        : Ctrl+C\n")
    cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", args.host, "--port", str(args.port)]
    if args.reload:
        cmd.append("--reload")
    try:
        return subprocess.call(cmd, cwd=BACKEND, env=env)
    except KeyboardInterrupt:
        return 0


def _write_web_env(url: str) -> None:
    """Point the app at `url`, keeping a one-time backup of the previous value."""
    lines = []
    if os.path.isfile(WEB_ENV):
        with open(WEB_ENV, encoding="utf-8") as f:
            lines = [l.rstrip("\n") for l in f]
        old = next((l for l in lines if l.startswith("VITE_API_BASE_URL=")), "")
        backup = WEB_ENV + ".bak"
        if old and old != f"VITE_API_BASE_URL={url}" and not os.path.exists(backup):
            shutil.copyfile(WEB_ENV, backup)
            say(f"  saved previous settings to {os.path.relpath(backup, ROOT)}")
    lines = [l for l in lines if not l.startswith("VITE_API_BASE_URL=")]
    if not any(l.startswith("VITE_AUTH_DISABLED=") for l in lines):
        lines.append("VITE_AUTH_DISABLED=1")
    lines.insert(0, f"VITE_API_BASE_URL={url}")
    with open(WEB_ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def cmd_apk(args) -> int:
    url = args.api.rstrip("/") if args.api else base_url(args)
    say(f"Building debug APK that talks to {url}")
    _write_web_env(url)
    if not shutil.which("npm"):
        say("npm not found. Install Node.js first.")
        return 1
    if not os.path.isdir(os.path.join(ROOT, "node_modules")):
        say("Installing npm packages (first run)...")
        if subprocess.call("npm install", cwd=ROOT, shell=True) != 0:
            return 1
    if subprocess.call("npm run android:debug", cwd=ROOT, shell=True) != 0:
        say("\nAPK build failed (scroll up for the Gradle error).")
        return 1
    os.makedirs(os.path.dirname(APK_OUT), exist_ok=True)
    shutil.copyfile(APK_BUILT, APK_OUT)
    say(f"\nAPK ready: {APK_OUT}  ({os.path.getsize(APK_OUT) / 1e6:.1f} MB)")
    say("Copy it to your phone and install it (allow 'install unknown apps').")
    say("If your Wi-Fi/IP changes, run `py kisan.py apk` again.")
    return 0


def cmd_all(args) -> int:
    args.api = None
    rc = cmd_apk(args)
    return rc if rc else cmd_serve(args)


def _get(url: str, timeout: float = 10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def cmd_check(args) -> int:
    url = base_url(args)
    say(f"Backend: {url}")
    for f in ("model_meta.json", "paddy_disease_model_fold0.tflite", "crop_gate.json", "crop_gate.tflite"):
        p = os.path.join(MODELS, f)
        say(f"  {'ok     ' if os.path.isfile(p) else 'MISSING'} backend/models/{f}")
    try:
        _get(f"{url}/healthz")
        say("  ok      /healthz")
        h = _get(f"{url}/health")
        say(f"  model_mode = {h.get('model_mode')}   (want: tflite)")
        say("  note: DynamoDB/AWS errors in the server log are fine for local testing")
        return 0
    except (urllib.error.URLError, OSError) as exc:
        say(f"  DOWN    {exc}\n  Start it with: py kisan.py serve")
        return 1


def _multipart(path: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        data = f.read()
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nen\r\n'.encode(),
        (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{os.path.basename(path)}"\r\n'
         f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def diagnose_one(url: str, path: str) -> tuple[int, dict]:
    body, ctype = _multipart(path)
    req = urllib.request.Request(f"{url}/diagnose", data=body, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {"detail": e.reason}


def cmd_diagnose(args) -> int:
    url = base_url(args)
    files = []
    for p in args.paths:
        if os.path.isdir(p):
            found = [os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs if f.lower().endswith(IMG_EXT)]
            random.shuffle(found)
            files += found[: args.n]
        elif os.path.isfile(p):
            files.append(p)
        else:
            say(f"not found: {p}")
    if not files:
        say("No images to test.")
        return 1
    accepted = rejected = 0
    try:
        for f in files:
            code, j = diagnose_one(url, f)
            name = os.path.relpath(f) if len(f) > 60 else f
            if code == 200:
                accepted += 1
                flag = "" if j.get("safe_to_act") else "  (low confidence)"
                say(f"[CLASSIFIED] {j['disease']} {j['confidence']:.1f}%{flag}   <- {name}")
            elif code == 422:
                rejected += 1
                say(f"[REJECTED]   not a rice leaf   <- {name}")
            else:
                say(f"[ERROR {code}] {j.get('detail')}   <- {name}")
    except (urllib.error.URLError, OSError) as exc:
        say(f"Cannot reach {url}: {exc}\nStart the backend first: py kisan.py serve")
        return 1
    if len(files) > 1:
        say(f"\n{len(files)} photos: {accepted} classified, {rejected} rejected as non-rice")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="kisan", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, url=False):
        p.add_argument("--port", type=int, default=8000)
        if url:
            p.add_argument("--url", help="backend URL (default: this laptop's LAN address)")

    p = sub.add_parser("serve", help="start the backend")
    common(p)
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = reachable from your phone (default)")
    p.add_argument("--login", action="store_true", help="require real login (needs AWS Cognito); default is guest mode")
    p.add_argument("--reload", action="store_true", help="auto-restart when code changes")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("apk", help="build the debug APK")
    common(p)
    p.add_argument("--api", help="backend URL to bake in (default: http://<laptop-ip>:<port>)")
    p.set_defaults(fn=cmd_apk)

    p = sub.add_parser("all", help="build the APK, then start the backend")
    common(p)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--login", action="store_true")
    p.add_argument("--reload", action="store_true")
    p.set_defaults(fn=cmd_all)

    p = sub.add_parser("check", help="backend health + model files")
    common(p, url=True)
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("diagnose", help="send photos to the backend")
    common(p, url=True)
    p.add_argument("paths", nargs="+", help="image files and/or folders")
    p.add_argument("-n", type=int, default=10, help="photos to sample per folder (default 10)")
    p.set_defaults(fn=cmd_diagnose)

    p = sub.add_parser("ip", help="show this laptop's LAN address")
    p.set_defaults(fn=cmd_ip)

    p = sub.add_parser("firewall", help="print the Windows firewall command")
    common(p)
    p.set_defaults(fn=cmd_firewall)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
