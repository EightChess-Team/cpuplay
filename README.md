# 8Chess CpuPlay

Play the 8Chess NNUE engine live in your browser while a network of
volunteer donor CPUs computes the moves. Donors sign in with an 8Chess
account, approve their worker script in one click, and their account name
appears live on players' boards and the donor leaderboard.

- Browser front-end: chess.com-inspired UI on
  [Chessground](https://github.com/lichess-org/chessground) pieces +
  [chess.js](https://github.com/jhlywa/chess.js) — eval gauge, live
  donor nodes, promotion picker, sounds, worker authorization, and a
  volunteer-powered **game review** (accuracy, blunders/mistakes,
  best moves).
- Coordinator (`server.py`): aiohttp + python-chess. Accounts, SQLite
  persistence, one WebSocket per player (`/ws/play`), one WebSocket per
  donor (`/ws/worker`), a server-side fallback engine node, and
  `/api/review` game analysis.
- Donor client (`worker.py`): pure-Python. Auto-downloads the official
  8Chess engine binary from the release page, asks the server for a
  device code, you approve it on the website mid-click, then it donates
  under your account. No anonymous donors.

The full engine lives at [EightChess-Team/8chess](https://github.com/EightChess-Team/8chess).

## Run your own node

```sh
pip install aiohttp chess
python3 server.py                 # http://localhost:8080
```

`PORT` overrides the port (default `8080`). The SQLite database
(`cpuplay.db`) is created automatically next to `server.py`.

Fallback engine search order for the server-side node: `bin/eightchess`
(next to the server) → `../target/release/eightchess` →
`/opt/cpu_play/bin/eightchess` → `$PATH/eightchess`.

Donate
------
Requires a signed-in 8Chess account (either on your running node or the
official deployment):

```sh
curl -sSL https://<cpuplay-host>/worker.py | python3 - --server https://<cpuplay-host>
```

1. The script prints a one-click authorization link and code.
2. Opening the link pops "A CPU wants to donate" on the website — click
   **Authorize** (or paste the code into the Donate modal).
3. The worker reconnects and donates under your account until stopped.
   Pre-authorized tokens are also supported:

```sh
curl -sSL https://<cpuplay-host>/worker.py | python3 - \
    --server https://<cpuplay-host> --token <worker-token>
```

Handy flags: `--threads N` (default: all cores), `--open` (auto-open
the authorization page), `--engine /path/to/eightchess`.

HTTP API summary
----------------

```
POST /api/auth/register     { username, password } -> session token
POST /api/auth/login        { username, password } -> session token
GET  /api/auth/me
GET  /api/stats             games, donor leaderboard, live worker list
POST /api/worker/device/start        -> device_code + user_code + verify_url
GET  /api/worker/device/poll?code=<device_code>  -> token when approved
POST /api/worker/device/approve { user_code, allow }   (auth)
POST /api/review            { moves: [uci...], movetime } (auth)
GET  /worker.py             the donor client, served live
WS   /ws/play?token=<session>      player game channel
WS   /ws/worker                    authenticated donor channel
```

Vendored assets (in `static/vendor/`): Chessground (GPL-3.0), chess.js
(BSD-2-Clause).

License
-------

AGPL-3.0 — see [LICENSE](LICENSE). CpuPlay is based on concepts from the
[8Chess](https://github.com/EightChess-Team/8chess) engine project.
