#!/usr/bin/env python3
"""
8Chess Volunteer CPU Worker Client
- Connects your CPU to the 8Chess volunteer network
- Evaluates positions for live web players using your local 8chess binary
- Auto-downloads the official 8chess binary if not already compiled locally
- Requires a signed-in 8Chess account:
    1. The script requests a device code from the server
    2. You approve it in one click on the website (the site wakes up with it)
    3. Your in-game donor name becomes your 8Chess account username
Optional: pass a pre-authorized --token to skip browser approval.
"""

import argparse
import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import webbrowser
import urllib.parse
import urllib.request
import zipfile

GITHUB_RELEASE_TAG = "v1.0.10"
RELEASE_BASE = f"https://github.com/EightChess-Team/8chess/releases/download/{GITHUB_RELEASE_TAG}"

def asset_candidates() -> list:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if "linux" in system:
        if "aarch64" in machine or "arm64" in machine:
            return ["linux-aarch64.tar.gz"]
        if "riscv64" in machine:
            return ["linux-riscv64.tar.gz"]
        return ["linux-x86_64-v3.tar.gz", "linux-x86_64-v4.tar.gz", "linux-x86_64.tar.gz"]
    elif "darwin" in system:
        return ["macos-universal.tar.gz"]
    elif "windows" in system:
        if "arm64" in machine:
            return ["windows-aarch64.zip"]
        return ["windows-x86_64-v3.zip", "windows-x86_64-v4.zip", "windows-x86_64.zip"]
    return ["linux-x86_64.tar.gz"]

def get_asset_name_for_platform() -> str:
    return asset_candidates()[0]

def ensure_binary(specified_path: str = None) -> str:
    # 1. Check user-specified path
    if specified_path and os.path.isfile(specified_path) and os.access(specified_path, os.X_OK):
        return os.path.abspath(specified_path)

    # 2. Check local paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "eightchess"),
        os.path.join(script_dir, "eightchess.exe"),
        os.path.join(os.getcwd(), "eightchess"),
        os.path.join(os.getcwd(), "eightchess.exe"),
        os.path.join(os.getcwd(), "target", "release", "eightchess"),
        os.path.join(os.getcwd(), "target", "release", "eightchess.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    # 3. Check if cargo is available to build locally
    if os.path.isfile(os.path.join(os.getcwd(), "Cargo.toml")):
        print("[*] Local source detected. Building optimized 8chess binary with cargo...")
        try:
            subprocess.run(["cargo", "build", "--release"], check=True)
            target_bin = os.path.join(os.getcwd(), "target", "release", "eightchess")
            if os.path.isfile(target_bin):
                return target_bin
        except Exception as e:
            print(f"[!] Cargo build failed: {e}. Will attempt binary download.")

    # 4. Download precompiled binary from official GitHub release
    download_dir = os.path.join(script_dir, "bin")
    os.makedirs(download_dir, exist_ok=True)

    last_error = None
    for asset_name in asset_candidates():
        url = f"{RELEASE_BASE}/{asset_name}"
        archive_path = os.path.join(download_dir, asset_name)

        print(f"[*] Downloading official 8Chess binary ({asset_name}) from GitHub...")
        try:
            urllib.request.urlretrieve(url, archive_path)
        except Exception as e:
            last_error = e
            print(f"[!] Download failed for {asset_name}: {e}")
            continue

        # Extract
        if archive_path.endswith(".tar.gz") or archive_path.endswith(".tgz"):
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(download_dir)
        elif archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as z:
                z.extractall(download_dir)

        for root, dirs, files in os.walk(download_dir):
            for f in files:
                if f in ("eightchess", "eightchess.exe"):
                    bin_path = os.path.join(root, f)
                    try:
                        os.chmod(bin_path, 0o755)
                    except Exception:
                        pass
                    print(f"[+] Downloaded and extracted 8chess to: {bin_path}")
                    return bin_path

        print(f"[!] No binary found inside {asset_name}, trying next asset...")

    raise FileNotFoundError(f"Could not find or download eightchess binary. Last error: {last_error}")

# Ensure aiohttp is installed
try:
    import aiohttp
except ImportError:
    print("[*] Installing required aiohttp package...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp", "--quiet"])
    import aiohttp

def http_json(url: str, payload: dict = None, timeout: int = 15) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())

def device_auth(server_url: str, open_browser: bool = False) -> str:
    """
    Device authorization flow:
      1. Ask the server for a short-lived device code
      2. Show a one-click approval URL (and the code itself)
      3. Poll until the signed-in user Approves or Denies the request
    Returns the personal worker token.
    """
    base = server_url.rstrip("/")
    print("=" * 60)
    print("   8Chess requires account authorization to donate CPU")
    print("=" * 60)

    start = http_json(f"{base}/api/worker/device/start", payload={})
    device_code = start["device_code"]
    user_code = start["user_code"]
    verify_url = start.get("verify_url") or f"{base}/?worker={user_code}"

    print()
    print("  ┌────────────────────────────────────────────────────┐")
    print("  │  AUTHORIZATION REQUIRED                            │")
    print("  │  Open this link and approve the request:           │")
    print()
    print(f"  │  {verify_url}")
    print()
    print(f"  │  Your worker code:  {user_code}")
    print("  └────────────────────────────────────────────────────┘")
    print()
    print("[*] Waiting for you to approve in your browser...", flush=True)

    if open_browser:
        try:
            webbrowser.open(verify_url)
        except Exception:
            pass

    deadline = time.time() + 900
    while time.time() < deadline:
        try:
            res = http_json(f"{base}/api/worker/device/poll?code={urllib.parse.quote(device_code)}")
            status = res.get("status", "pending")
        except Exception as e:
            print(f"[!] Network hiccup while polling ({e}); retrying...", flush=True)
            time.sleep(3)
            continue

        if status == "approved":
            print("[+] Worker authorized! Connecting as your account...", flush=True)
            return res.get("worker_token", "")
        if status == "denied":
            print("[!] The request was denied on the website. Exiting.")
            sys.exit(1)
        if status == "expired":
            print("[!] Code expired. Starting a new authorization round...")
            return ""
        time.sleep(2.5)

    print("[!] Authorization timed out. Exiting.")
    sys.exit(1)

async def run_worker(server_url: str, worker_token: str, threads: int, engine_path: str):
    # Normalize ws URL
    ws_url = server_url.replace("http://", "ws://").replace("https://", "wss://").rstrip("/") + "/ws/worker"

    system_info = f"{platform.system()} {platform.machine()} ({platform.processor() or 'CPU'})"

    print("=" * 60)
    print("           8Chess Volunteer CPU Worker Node")
    print("=" * 60)
    print(f"[+] Threads:       {threads}")
    print(f"[+] System:        {system_info}")
    print(f"[+] Engine Binary: {engine_path}")
    print(f"[+] Coordinator:   {ws_url}")
    print("=" * 60)

    moves_served = 0
    donor_name = ""

    while True:
        try:
            print(f"[*] Connecting to {ws_url}...", flush=True)
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url, heartbeat=20.0) as ws:
                    await ws.send_json({
                        "type": "register",
                        "token": worker_token,
                        "system": system_info,
                        "threads": threads,
                        "version": "8Chess 1.0"
                    })

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            mtype = data.get("type")

                            if mtype == "auth_error":
                                print()
                                print("[!] WORKER NOT AUTHORIZED:", data.get("message", "invalid token"))
                                print("[!] Run this script again to request a fresh authorization.")
                                os._exit(1)

                            elif mtype == "registered":
                                donor_name = data.get("name") or data.get("account") or ""
                                if donor_name:
                                    donor_name = f"@{donor_name}"
                                print(f"[+] Authorized! You are donating as {donor_name}.", flush=True)
                                print("[+] Awaiting web game moves...", flush=True)

                            elif mtype == "compute":
                                task_id = data["task_id"]
                                fen = data.get("fen", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
                                moves_list = data.get("moves", [])

                                t0 = time.time()
                                bestmove, score, depth = await compute_uci_move(engine_path, fen, moves_list, threads)
                                dt = time.time() - t0
                                moves_served += 1

                                print(f"[⚡ Move #{moves_served}] Task {task_id[:6]}: -> {bestmove} (score {score:+d}cp, d={depth}, {dt:.2f}s)", flush=True)

                                await ws.send_json({
                                    "type": "result",
                                    "task_id": task_id,
                                    "bestmove": bestmove,
                                    "score": score,
                                    "depth": depth
                                })

                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            print("[!] WebSocket closed or error. Reconnecting in 5 seconds...", flush=True)
                            break
        except aiohttp.WSServerHandshakeError as e:
            print(f"[!] Handshake failed ({e}). Retrying in 5 seconds...", flush=True)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[!] Connection failed: {e}. Retrying in 5 seconds...", flush=True)
            await asyncio.sleep(5)

async def compute_uci_move(engine_path: str, fen: str, moves_list: list, threads: int) -> tuple:
    proc = await asyncio.create_subprocess_exec(
        engine_path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )

    cmd_pos = "position " + ("startpos" if "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR" in fen and not moves_list else f"fen {fen}")
    if moves_list:
        cmd_pos += " moves " + " ".join(moves_list)
    cmd_pos += "\n"

    proc.stdin.write(b"uci\n")
    proc.stdin.write(f"setoption name Threads value {threads}\n".encode())
    proc.stdin.write(b"isready\n")
    proc.stdin.write(cmd_pos.encode())
    proc.stdin.write(b"go movetime 500\n")
    await proc.stdin.drain()

    bestmove = "(none)"
    score = 0
    depth = 14

    try:
        while True:
            line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=4.0)
            if not line_bytes:
                break
            line = line_bytes.decode(errors="ignore").strip()
            if "score cp" in line:
                try:
                    parts = line.split()
                    idx = parts.index("cp")
                    score = int(parts[idx + 1])
                except Exception:
                    pass
            if "depth" in line:
                try:
                    parts = line.split()
                    idx = parts.index("depth")
                    depth = int(parts[idx + 1])
                except Exception:
                    pass
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    bestmove = parts[1]
                break
    except Exception as e:
        print("[!] Engine compute timeout:", e)
    finally:
        try:
            proc.stdin.write(b"quit\n")
            await proc.stdin.drain()
            proc.kill()
        except Exception:
            pass

    return bestmove, score, depth

def main():
    parser = argparse.ArgumentParser(description="8Chess Volunteer CPU Worker")
    parser.add_argument("--server", default="http://localhost:8080", help="CpuPlay server URL (e.g. https://xxx.trycloudflare.com)")
    parser.add_argument("--threads", type=int, default=max(1, os.cpu_count() or 4), help="Number of CPU threads to donate")
    parser.add_argument("--token", default=os.environ.get("CPUPLAY_WORKER_TOKEN", ""), help="Pre-authorized worker token (skips browser approval)")
    parser.add_argument("--name", default="", help="(deprecated) ignored — your donor name is your 8Chess account username")
    parser.add_argument("--open", dest="open_browser", action="store_true", help="Open the authorization page automatically in a browser when needed")
    parser.add_argument("--engine", default=None, help="Explicit path to 8chess executable")
    args = parser.parse_args()

    token = (args.token or "").strip()
    if not token:
        token = device_auth(args.server, open_browser=args.open_browser)
        if not token:
            token = device_auth(args.server, open_browser=args.open_browser)
        if not token:
            print("[!] Could not authorize this machine.")
            sys.exit(1)

    engine_bin = ensure_binary(args.engine)
    asyncio.run(run_worker(args.server, token, args.threads, engine_bin))

if __name__ == "__main__":
    main()
