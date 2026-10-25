#!/usr/bin/env python3
"""
8Chess CpuPlay Server
- User authentication (register/login/sessions) without artificial limits
- Volunteer CPU coordinator: pairs games with distributed worker nodes running 8chess
- Instant fallback to server's local 8chess binary if no volunteer is online
- WebSocket play endpoint interfacing with Lichess Chessground frontend
"""

import asyncio
import hashlib
import hmac
import json
import math
import os
import platform
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from typing import Dict, Optional
import aiohttp
from aiohttp import web
import chess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_PATH = os.path.join(BASE_DIR, "cpuplay.db")
TUNNEL_FILE = os.path.join(BASE_DIR, "tunnel_url.txt")

# Possible locations for 8chess executable
ENGINE_CANDIDATES = [
    os.path.join(BASE_DIR, "bin", "eightchess"),
    os.path.join(BASE_DIR, "bin", "eightchess.exe"),
    os.path.join(os.path.dirname(BASE_DIR), "target", "release", "eightchess"),
    os.path.join(os.path.dirname(BASE_DIR), "target", "release", "eightchess.exe"),
    "/opt/cpu_play/bin/eightchess",
    "eightchess"
]

def find_engine_path() -> Optional[str]:
    for p in ENGINE_CANDIDATES:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None

# ==================== DATABASE ====================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS games (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        player_color TEXT NOT NULL,
        moves TEXT NOT NULL,
        result TEXT DEFAULT NULL,
        worker_info TEXT DEFAULT NULL,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS volunteer_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        system_info TEXT NOT NULL,
        threads INTEGER DEFAULT 1,
        moves_served INTEGER DEFAULT 0,
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS worker_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS device_codes (
        device_code TEXT PRIMARY KEY,
        user_code TEXT UNIQUE NOT NULL,
        ip TEXT DEFAULT '',
        user_id INTEGER DEFAULT NULL REFERENCES users(id),
        status TEXT NOT NULL DEFAULT 'pending',
        worker_token TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

def hash_pw(password: str, salt: str) -> str:
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=2**14, r=8, p=1, dklen=32)
    return digest.hex()

def verify_pw(password: str, salt: str, expected: str) -> bool:
    # Legacy SHA-256 hashes from earlier builds
    if len(expected) == 64:
        legacy = hashlib.sha256((salt + password).encode()).hexdigest()
        return hmac.compare_digest(legacy, expected)
    return hmac.compare_digest(hash_pw(password, salt), expected)

def db_register(username: str, password: str):
    username = username.strip()
    if not username or len(username) < 3 or len(username) > 30:
        return False, "Username must be 3-30 characters."
    if len(password) < 4:
        return False, "Password must be at least 4 characters."
    salt = secrets.token_hex(8)
    pw_hash = hash_pw(password, salt)
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)", (username, pw_hash, salt))
        user_id = c.lastrowid
        token = secrets.token_hex(24)
        c.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
        conn.commit()
        return True, {"token": token, "username": username, "user_id": user_id}
    except sqlite3.IntegrityError:
        return False, "Username already exists."
    finally:
        conn.close()

def db_login(username: str, password: str):
    username = username.strip()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, password_hash, salt FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "Invalid username or password."
    user_id, pw_hash, salt = row
    if not verify_pw(password, salt, pw_hash):
        conn.close()
        return False, "Invalid username or password."
    token = secrets.token_hex(24)
    c.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
    conn.commit()
    conn.close()
    return True, {"token": token, "username": username, "user_id": user_id}

def db_get_user(token: str):
    if not token:
        return None
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    SELECT u.id, u.username FROM users u
    JOIN sessions s ON u.id = s.user_id
    WHERE s.token = ?
    """, (token,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "username": row[1]}
    return None

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def db_create_worker_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT INTO worker_tokens (token_hash, user_id) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 token_hash = excluded.token_hash,
                 created_at = CURRENT_TIMESTAMP""",
            (_token_hash(token), user_id)
        )
        conn.commit()
    finally:
        conn.close()
    return token

def db_get_worker_user(token: str):
    if not token:
        return None
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT u.id, u.username FROM worker_tokens w
        JOIN users u ON u.id = w.user_id
        WHERE w.token_hash = ?
    """, (_token_hash(token),))
    row = c.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "username": row[1]}
    return None

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

DEVICE_TTL_SEC = 900
DEVICE_MAX_PENDING_PER_IP = 5

def db_purge_devices():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            DELETE FROM device_codes
            WHERE created_at < datetime('now', '-20 minutes')
               OR (status != 'pending' AND created_at < datetime('now', '-3 minutes'))
        """)
        conn.commit()
    finally:
        conn.close()

def db_create_device_code(ip: str):
    db_purge_devices()
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM device_codes WHERE ip = ? AND status = 'pending'", (ip,))
        if c.fetchone()[0] >= DEVICE_MAX_PENDING_PER_IP:
            return None
        device_code = secrets.token_hex(16)
        for _ in range(12):
            user_code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            try:
                c.execute(
                    "INSERT INTO device_codes (device_code, user_code, ip) VALUES (?, ?, ?)",
                    (device_code, user_code, ip[:64])
                )
                conn.commit()
                return {"device_code": device_code, "user_code": user_code}
            except sqlite3.IntegrityError:
                continue
        return None
    finally:
        conn.close()

def db_approve_device(user_code: str, user_id: int, allow: bool = True) -> bool:
    user_code = (user_code or "").strip().upper()
    if not user_code:
        return False
    db_purge_devices()
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        if allow:
            worker_token = db_create_worker_token(user_id)
            c.execute(
                """UPDATE device_codes
                   SET status = 'approved', user_id = ?, worker_token = ?
                   WHERE user_code = ? AND status = 'pending'
                     AND created_at > datetime('now', '-20 minutes')""",
                (user_id, worker_token, user_code)
            )
        else:
            c.execute(
                """UPDATE device_codes
                   SET status = 'denied', user_id = ?
                   WHERE user_code = ? AND status = 'pending'
                     AND created_at > datetime('now', '-20 minutes')""",
                (user_id, user_code)
            )
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()

def db_poll_device(device_code: str):
    device_code = (device_code or "").strip()
    if not device_code:
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("SELECT status, worker_token FROM device_codes WHERE device_code = ?", (device_code,))
        row = c.fetchone()
        if not row:
            return {"status": "expired"}
        status, worker_token = row
        if status == "pending":
            return {"status": "pending"}
        c.execute("DELETE FROM device_codes WHERE device_code = ?", (device_code,))
        conn.commit()
        if status == "approved" and worker_token:
            return {"status": "approved", "worker_token": worker_token}
        return {"status": "denied" if status == "denied" else "expired"}
    finally:
        conn.close()

def db_record_volunteer_move(name: str, system_info: str, threads: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    INSERT INTO volunteer_stats (name, system_info, threads, moves_served, last_seen)
    VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
    ON CONFLICT(name) DO UPDATE SET
        system_info = excluded.system_info,
        threads = excluded.threads,
        moves_served = volunteer_stats.moves_served + 1,
        last_seen = CURRENT_TIMESTAMP
    """, (name, system_info, threads))
    conn.commit()
    conn.close()

def db_get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM games")
    total_games = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(moves_served), 0) FROM volunteer_stats")
    vol_moves = c.fetchone()[0]
    c.execute("SELECT name, system_info, threads, moves_served FROM volunteer_stats ORDER BY moves_served DESC LIMIT 10")
    top_donors = [{"name": r[0], "system": r[1], "threads": r[2], "moves": r[3]} for r in c.fetchall()]
    conn.close()
    return {
        "total_games": total_games,
        "volunteer_moves": vol_moves,
        "top_donors": top_donors
    }

def db_new_game(game_id: str, user_id: int, player_color: str):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO games (id, user_id, player_color, moves, status) VALUES (?, ?, ?, '', 'active')",
            (game_id, user_id, player_color)
        )
        conn.commit()
    finally:
        conn.close()

def db_update_game(game_id: str, moves: list, result: Optional[str] = None,
                   status: str = "active", worker_info: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """UPDATE games SET moves = ?, result = COALESCE(?, result), status = ?,
               worker_info = COALESCE(?, worker_info), updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (" ".join(moves), result, status, worker_info, game_id)
        )
        conn.commit()
    finally:
        conn.close()

# ==================== VOLUNTEER WORKER POOL ====================

class WorkerNode:
    def __init__(self, worker_id: str, ws: web.WebSocketResponse, name: str,
                 account_username: str, user_id: int, system_info: str, threads: int):
        self.worker_id = worker_id
        self.ws = ws
        self.name = name
        self.account_username = account_username
        self.user_id = user_id
        self.system_info = system_info
        self.threads = threads
        self.busy = False
        self.moves_count = 0
        self.last_seen = time.time()

class WorkerPool:
    def __init__(self):
        self.workers: Dict[str, WorkerNode] = {}
        self.pending_tasks: Dict[str, asyncio.Future] = {}

    def add(self, worker_id: str, ws: web.WebSocketResponse, name: str,
            account_username: str, user_id: int, system_info: str, threads: int):
        node = WorkerNode(worker_id, ws, name, account_username, user_id, system_info, threads)
        self.workers[worker_id] = node
        print(f"[WorkerPool] + Volunteer connected: {name} / @{account_username} ({threads}T on {system_info})", flush=True)

    def remove(self, worker_id: str):
        if worker_id in self.workers:
            node = self.workers.pop(worker_id)
            print(f"[WorkerPool] - Volunteer disconnected: {node.name}", flush=True)

    def get_idle_worker(self) -> Optional[WorkerNode]:
        candidates = [w for w in self.workers.values() if not w.busy and not w.ws.closed]
        if not candidates:
            return None
        candidates.sort(key=lambda w: (-w.threads, w.moves_count, w.last_seen))
        return candidates[0]

    async def compute_move(self, fen: str, moves_list: list, timeout: float = 6.0) -> Optional[dict]:
        worker = self.get_idle_worker()
        if not worker:
            return None

        worker.busy = True
        task_id = secrets.token_hex(8)
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self.pending_tasks[task_id] = future

        msg = {
            "type": "compute",
            "task_id": task_id,
            "fen": fen,
            "moves": moves_list,
            "wtime": 1000,
            "btime": 1000,
            "winc": 10,
            "binc": 10
        }

        try:
            await worker.ws.send_json(msg)
            result = await asyncio.wait_for(future, timeout=timeout)
            worker.moves_count += 1
            db_record_volunteer_move(worker.account_username, worker.system_info, worker.threads)
            return {
                "bestmove": result.get("bestmove"),
                "score": result.get("score", 0),
                "depth": result.get("depth", 16),
                "provider": f"Volunteer: @{worker.account_username} ({worker.threads}T {worker.system_info})",
                "is_volunteer": True
            }
        except Exception as e:
            print(f"[WorkerPool] Task {task_id} failed on {worker.name}: {e}", flush=True)
            return None
        finally:
            worker.busy = False
            self.pending_tasks.pop(task_id, None)

    def resolve_task(self, task_id: str, data: dict):
        fut = self.pending_tasks.get(task_id)
        if fut and not fut.done():
            fut.set_result(data)

worker_pool = WorkerPool()

# ==================== LOCAL FALLBACK ENGINE ====================

async def fallback_compute_move(fen: str, moves_list: list, movetime: int = 600) -> dict:
    engine_path = find_engine_path()
    if not engine_path:
        # Emergency heuristic move if engine binary is missing
        b = chess.Board(fen)
        for m in moves_list:
            b.push_uci(m)
        legal = list(b.legal_moves)
        if not legal:
            return {"bestmove": "(none)", "provider": "Fallback Server", "is_volunteer": False}
        return {"bestmove": legal[0].uci(), "provider": "8Chess Fallback (Minimal)", "is_volunteer": False}

    proc = await asyncio.create_subprocess_exec(
        engine_path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )

    cmd_pos = "position " + ("startpos" if fen == chess.STARTING_FEN else f"fen {fen}")
    if moves_list:
        cmd_pos += " moves " + " ".join(moves_list)
    cmd_pos += "\n"

    server_threads = max(1, min(os.cpu_count() or 1, 16))

    proc.stdin.write(b"uci\n")
    proc.stdin.write(f"setoption name Threads value {server_threads}\n".encode())
    proc.stdin.write(f"setoption name Hash value 256\n".encode())
    proc.stdin.write(b"isready\n")
    proc.stdin.write(cmd_pos.encode())
    proc.stdin.write(f"go movetime {int(movetime)}\n".encode())
    await proc.stdin.drain()

    bestmove = "(none)"
    score = 0
    depth = 12

    try:
        while True:
            line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=3.0)
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
            if " depth " in f" {line} ":
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
        print("[FallbackEngine] Read timeout or error:", e, flush=True)
    finally:
        try:
            proc.stdin.write(b"quit\n")
            await proc.stdin.drain()
            proc.kill()
        except Exception:
            pass

    return {
        "bestmove": bestmove,
        "score": score,
        "depth": depth,
        "provider": f"8Chess Server Node ({server_threads} Threads - Official NNUE)",
        "is_volunteer": False
    }

async def get_engine_move(fen: str, moves_list: list) -> dict:
    # 1. First attempt to route to an active volunteer donor CPU
    res = await worker_pool.compute_move(fen, moves_list)
    if res and res.get("bestmove") and res["bestmove"] not in ("(none)", "0000"):
        return res

    # 2. Seamlessly fall back to server engine so the user never stalls
    return await fallback_compute_move(fen, moves_list)

# ==================== HTTP & WS HANDLERS ====================

async def handle_index(request):
    return web.FileResponse(os.path.join(STATIC_DIR, "index.html"))

async def handle_auth_register(request):
    data = await request.json()
    ok, res = db_register(data.get("username", ""), data.get("password", ""))
    if not ok:
        return web.json_response({"ok": False, "error": res}, status=400)
    return web.json_response({"ok": True, **res})

async def handle_auth_login(request):
    data = await request.json()
    ok, res = db_login(data.get("username", ""), data.get("password", ""))
    if not ok:
        return web.json_response({"ok": False, "error": res}, status=401)
    return web.json_response({"ok": True, **res})

async def handle_auth_me(request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not token:
        token = request.query.get("token", "").strip()
    user = db_get_user(token)
    return web.json_response({"ok": bool(user), "user": user})

async def handle_stats(request):
    stats = db_get_stats()
    tunnel_url = ""
    if os.path.exists(TUNNEL_FILE):
        try:
            with open(TUNNEL_FILE) as f:
                tunnel_url = f.read().strip()
        except Exception:
            pass
    active_workers = [
        {
            "name": w.account_username,
            "account": w.account_username,
            "system": w.system_info,
            "threads": w.threads,
            "moves": w.moves_count,
            "busy": w.busy
        }
        for w in worker_pool.workers.values()
    ]
    return web.json_response({
        "ok": True,
        "workers_online": len(active_workers),
        "workers": active_workers,
        "tunnel_url": tunnel_url,
        **stats
    })

async def handle_worker_token(request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    user = db_get_user(token)
    if not user:
        return web.json_response({"ok": False, "error": "Login required to donate CPU."}, status=401)
    worker_token = db_create_worker_token(user["id"])
    return web.json_response({
        "ok": True,
        "worker_token": worker_token,
        "name": user["username"],
        "account": user["username"],
    })

async def handle_worker_script(request):
    worker_script_path = os.path.join(BASE_DIR, "worker.py")
    if os.path.exists(worker_script_path):
        return web.FileResponse(worker_script_path)
    return web.Response(text="# worker.py not found", status=404)

# ==================== WORKER DEVICE AUTHORIZATION ====================

def request_origin(request) -> str:
    proto = request.headers.get("X-Forwarded-Proto", request.scheme or "http")
    return f"{proto}://{request.host}"

async def handle_worker_device_start(request):
    ip = request.remote or "unknown"
    code = db_create_device_code(ip)
    if not code:
        return web.json_response(
            {"ok": False, "error": "Too many pending worker requests from this machine. Try again later."},
            status=429
        )
    origin = request_origin(request)
    return web.json_response({
        "ok": True,
        **code,
        "verify_url": f"{origin}/?worker={code['user_code']}",
        "expires_in": DEVICE_TTL_SEC
    })

async def handle_worker_device_poll(request):
    res = db_poll_device(request.query.get("code", ""))
    if not res:
        return web.json_response({"ok": False, "status": "expired"})
    return web.json_response({"ok": res.get("status") == "approved", **res})

async def handle_worker_device_approve(request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    user = db_get_user(token)
    if not user:
        return web.json_response(
            {"ok": False, "error": "Login required to authorize a worker."},
            status=401
        )
    try:
        data = await request.json()
    except Exception:
        data = {}
    user_code = data.get("user_code", "")
    allow = bool(data.get("allow", True))
    ok = db_approve_device(user_code, user["id"], allow)
    if not ok:
        return web.json_response(
            {"ok": False, "error": "Unknown, expired, or already-authorized worker code."},
            status=404
        )
    return web.json_response({"ok": True, "status": "approved" if allow else "denied"})

# ==================== VOLUNTEER-POWERED GAME REVIEW ====================

review_cooldowns: Dict[int, float] = {}

def move_quality_tag(loss_cp: int) -> str:
    if loss_cp >= 200:
        return "blunder"
    if loss_cp >= 120:
        return "mistake"
    if loss_cp >= 60:
        return "inaccuracy"
    return "good"

def win_percent(cp: float) -> float:
    cp = max(-1500.0, min(1500.0, cp))
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp)) - 1.0)

def move_accuracy(win_before: float, win_after: float) -> float:
    drop = max(0.0, win_before - win_after)
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * drop) - 3.1669))

async def handle_review(request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    user = db_get_user(token)
    if not user:
        return web.json_response({"ok": False, "error": "Login required for game review."}, status=401)

    now = time.time()
    last = review_cooldowns.get(user["id"], 0)
    if now - last < 15:
        return web.json_response(
            {"ok": False, "error": "Review session still cooling down. Try again in a few seconds."},
            status=429
        )
    review_cooldowns[user["id"]] = now

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request body."}, status=400)

    raw_moves = data.get("moves") or []
    if not (2 <= len(raw_moves) <= 60):
        return web.json_response(
            {"ok": False, "error": "Review needs between 2 and 60 moves."}, status=400
        )

    board = chess.Board()
    fens = []
    ucis = []
    for m in raw_moves:
        fens.append(board.fen())
        ucis.append(str(m))
        try:
            board.push_uci(str(m))
        except Exception:
            return web.json_response(
                {"ok": False, "error": f"Illegal move in position {len(ucis)}."}, status=400
            )

    total = len(fens)
    per_move_budget = float(data.get("movetime", 300))
    per_move_budget = max(100.0, min(per_move_budget, 600.0))
    timeout_each = max(3.0, per_move_budget / 1000.0 * 8 + 2.5)

    results = []
    provider_counts = {}
    for i, fen in enumerate(fens):
        moves_prefix = ucis[:i]
        task = None
        w = worker_pool.get_idle_worker()
        if w:
            task = await worker_pool.compute_move(fen, moves_prefix, timeout=timeout_each)
        if not task or not task.get("bestmove") or task.get("bestmove") in ("(none)", "0000"):
            task = await fallback_compute_move(fen, moves_prefix, movetime=per_move_budget)
        provider = task.get("provider", "unknown")
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        score_i = float(task.get("score", 0) or 0)
        mover_white = (i % 2 == 0)
        white_eval = score_i if mover_white else -score_i
        results.append({
            "i": i,
            "fen": fen,
            "eval": white_eval,
            "best": task.get("bestmove"),
            "played": ucis[i],
            "provider": "volunteer" if task.get("is_volunteer") else "server",
            "tag": "good"
        })

    reviews = []
    acc_sum = {"w": [], "b": []}
    tag_counts = {"blunder": 0, "mistake": 0, "inaccuracy": 0, "good": 0}
    for i in range(total):
        entry = results[i]
        mover = "w" if (i % 2 == 0) else "b"
        win_before = win_percent(entry["eval"])
        if i + 1 < total:
            loss = entry["eval"] - results[i + 1]["eval"]
            loss = max(0.0, loss if mover == "w" else -loss)
            win_after = win_percent(results[i + 1]["eval"] if mover == "w" else -results[i + 1]["eval"])
            entry["loss"] = round(loss)
        else:
            loss = 0.0
            win_after = win_percent(entry["eval"])
        tag = move_quality_tag(loss)
        entry["tag"] = tag
        tag_counts[tag] = tag_counts.get(tag, 0) + 1
        acc_sum[mover].append(move_accuracy(win_before, win_after))
        reviews.append(entry)

    avg = lambda lst: round(sum(lst) / len(lst), 1) if lst else 0
    summary = {
        "accuracy": {
            "w": avg(acc_sum["w"]),
            "b": avg(acc_sum["b"])
        },
        "counts": tag_counts
    }

    return web.json_response({
        "ok": True,
        "moves": reviews,
        "summary": summary,
        "providers": provider_counts
    })

# ==================== VOLUNTEER WORKER WEBSOCKET ====================

async def handle_worker_ws(request):
    ws = web.WebSocketResponse(heartbeat=20.0)
    await ws.prepare(request)
    worker_id = secrets.token_hex(8)

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue

                mtype = data.get("type")
                if mtype == "register":
                    worker_token = data.get("token", "").strip()
                    user = db_get_worker_user(worker_token)
                    if not user:
                        await ws.send_json({
                            "type": "auth_error",
                            "message": "A valid 8Chess account is required to donate CPU. Log in on the website to get your worker token."
                        })
                        await ws.close()
                        return ws

                    name = user["username"][:32]
                    sys_info = data.get("system", platform.platform())[:64]
                    try:
                        requested_threads = int(data.get("threads", 1))
                    except (TypeError, ValueError):
                        requested_threads = 1
                    threads = max(1, min(requested_threads, 64))
                    worker_pool.add(worker_id, ws, name, user["username"], user["id"], sys_info, threads)
                    print(f"[WorkerWS] Authenticated donor @{user['username']} ({threads}T)", flush=True)
                    await ws.send_json({
                        "type": "registered",
                        "worker_id": worker_id,
                        "name": name,
                        "account": user["username"],
                    })

                elif mtype == "result":
                    task_id = data.get("task_id")
                    if task_id:
                        worker_pool.resolve_task(task_id, data)

            elif msg.type == aiohttp.WSMsgType.ERROR:
                print(f"[WorkerWS] Connection error: {ws.exception()}", flush=True)
    finally:
        worker_pool.remove(worker_id)

    return ws

# ==================== PLAYER GAME WEBSOCKET ====================

active_games: Dict[str, dict] = {}

async def handle_play_ws(request):
    ws = web.WebSocketResponse(heartbeat=25.0)
    await ws.prepare(request)

    token = request.query.get("token", "")
    user = db_get_user(token)
    if not user:
        await ws.send_json({"type": "auth_error", "message": "Login required to play. Sign up instantly without limits!"})
        await ws.close()
        return ws

    game_id = None

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue

                action = data.get("action")

                if action == "new_game":
                    if game_id in active_games:
                        active_games.pop(game_id, None)
                    game_id = secrets.token_hex(8)
                    chosen_color = data.get("color", "white")
                    if chosen_color not in ("white", "black"):
                        chosen_color = secrets.choice(["white", "black"])

                    board = chess.Board()
                    active_games[game_id] = {
                        "user_id": user["id"],
                        "board": board,
                        "player_color": chosen_color,
                        "moves": [],
                        "status": "active"
                    }
                    db_new_game(game_id, user["id"], chosen_color)

                    await ws.send_json({
                        "type": "game_started",
                        "game_id": game_id,
                        "fen": board.fen(),
                        "player_color": chosen_color,
                        "orientation": chosen_color
                    })

                    # If player is black, 8chess plays first move
                    if chosen_color == "black":
                        await ws.send_json({
                            "type": "engine_thinking",
                            "provider": "Selecting volunteer CPU or server engine..."
                        })
                        move_info = await get_engine_move(board.fen(), [])
                        uci = move_info.get("bestmove")
                        if uci and uci != "(none)":
                            try:
                                mv = chess.Move.from_uci(uci)
                                if mv in board.legal_moves:
                                    san = board.san(mv)
                                    board.push(mv)
                                    active_games[game_id]["moves"].append(uci)
                                    db_update_game(game_id, active_games[game_id]["moves"],
                                                   worker_info=move_info.get("provider"))
                                    await ws.send_json({
                                        "type": "move_made",
                                        "by": "engine",
                                        "uci": uci,
                                        "san": san,
                                        "fen": board.fen(),
                                        "provider": move_info.get("provider"),
                                        "is_volunteer": move_info.get("is_volunteer", False),
                                        "eval": move_info.get("score", 0),
                                        "is_game_over": board.is_game_over()
                                    })
                            except Exception as e:
                                print("[PlayWS] Engine first move error:", e, flush=True)

                elif action == "move":
                    if not game_id or game_id not in active_games:
                        await ws.send_json({"type": "error", "message": "No active game."})
                        continue

                    g = active_games[game_id]
                    board: chess.Board = g["board"]
                    uci = data.get("uci", "")

                    try:
                        mv = chess.Move.from_uci(uci)
                    except Exception:
                        await ws.send_json({"type": "error", "message": f"Malformed UCI move: {uci}", "fen": board.fen()})
                        continue

                    if mv not in board.legal_moves:
                        await ws.send_json({"type": "error", "message": "Illegal move.", "fen": board.fen()})
                        continue

                    # Apply player move
                    san = board.san(mv)
                    board.push(mv)
                    g["moves"].append(uci)

                    is_over = board.is_game_over()
                    result_desc = None
                    if is_over:
                        result_desc = board.result(claim_draw=True)
                        g["status"] = "finished"
                    db_update_game(game_id, g["moves"], result_desc, g["status"])

                    await ws.send_json({
                        "type": "move_made",
                        "by": "player",
                        "uci": uci,
                        "san": san,
                        "fen": board.fen(),
                        "is_game_over": is_over,
                        "result": result_desc
                    })

                    if is_over:
                        continue

                    # Engine's turn to answer
                    await ws.send_json({
                        "type": "engine_thinking",
                        "provider": "Volunteer network is calculating..."
                    })

                    move_info = await get_engine_move(chess.STARTING_FEN, g["moves"])
                    best_uci = move_info.get("bestmove")

                    if not best_uci or best_uci in ("(none)", "0000"):
                        # Resignation / no moves
                        db_update_game(game_id, g["moves"], "1-0", "finished")
                        await ws.send_json({"type": "game_over", "result": "1-0", "reason": "Engine has no legal moves"})
                        continue

                    try:
                        emv = chess.Move.from_uci(best_uci)
                        if emv in board.legal_moves:
                            esan = board.san(emv)
                            board.push(emv)
                            g["moves"].append(best_uci)
                            is_over = board.is_game_over()
                            result_desc = board.result(claim_draw=True) if is_over else None
                            if is_over:
                                g["status"] = "finished"
                            db_update_game(game_id, g["moves"], result_desc, g["status"],
                                           move_info.get("provider"))

                            await ws.send_json({
                                "type": "move_made",
                                "by": "engine",
                                "uci": best_uci,
                                "san": esan,
                                "fen": board.fen(),
                                "provider": move_info.get("provider"),
                                "is_volunteer": move_info.get("is_volunteer", False),
                                "eval": move_info.get("score", 0),
                                "depth": move_info.get("depth", 16),
                                "is_game_over": is_over,
                                "result": result_desc
                            })
                    except Exception as e:
                        print(f"[PlayWS] Move apply error: {e}", flush=True)

                elif action == "resign":
                    if game_id and game_id in active_games:
                        active_games[game_id]["status"] = "finished"
                        db_update_game(game_id, active_games[game_id]["moves"], "0-1", "finished")
                        await ws.send_json({"type": "game_over", "result": "0-1", "reason": "Player resigned."})

    finally:
        if game_id in active_games:
            g = active_games.pop(game_id, None)
            if g and g.get("status") == "active":
                conn = sqlite3.connect(DB_PATH)
                try:
                    conn.execute("UPDATE games SET status = 'aborted' WHERE id = ? AND status = 'active'", (game_id,))
                    conn.commit()
                finally:
                    conn.close()

    return ws

# ==================== APP FACTORY ====================

def create_app():
    init_db()
    app = web.Application()

    app.router.add_get("/", handle_index)
    app.router.add_post("/api/auth/register", handle_auth_register)
    app.router.add_post("/api/auth/login", handle_auth_login)
    app.router.add_get("/api/auth/me", handle_auth_me)
    app.router.add_get("/api/stats", handle_stats)
    app.router.add_get("/api/worker/token", handle_worker_token)
    app.router.add_post("/api/worker/device/start", handle_worker_device_start)
    app.router.add_get("/api/worker/device/poll", handle_worker_device_poll)
    app.router.add_post("/api/worker/device/approve", handle_worker_device_approve)
    app.router.add_post("/api/review", handle_review)
    app.router.add_get("/worker.py", handle_worker_script)

    app.router.add_get("/ws/worker", handle_worker_ws)
    app.router.add_get("/ws/play", handle_play_ws)

    # Static files
    app.router.add_static("/", STATIC_DIR, show_index=True)

    return app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[*] Starting 8Chess CpuPlay server on port {port}...")
    engine_found = find_engine_path()
    print(f"[*] Local fallback engine: {engine_found or 'None found (will use volunteer/random)'}")
    web.run_app(create_app(), host="0.0.0.0", port=port)
