import { Chessground } from "/vendor/chessground.min.js";

const $ = (id) => document.getElementById(id);

const PIECE_GLYPH = {
  w: { p: "♙", n: "♘", b: "♗", r: "♖", q: "♕", k: "♔" },
  b: { p: "♟", n: "♞", b: "♝", r: "♜", q: "♛", k: "♚" }
};
const PIECE_VALUE = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 0 };
const INITIAL_COUNTS = { p: 8, n: 2, b: 2, r: 2, q: 1 };
const PROMO_GLYPH = { w: { q: "♕", r: "♖", b: "♗", n: "♘" }, b: { q: "♛", r: "♜", b: "♝", n: "♞" } };

const chess = new window.Chess();
let ground = null;
let ws = null;
let token = localStorage.getItem("cpuplay_token") || "";
let currentUser = null;
let playerColor = null;
let colorPref = "white";
let gameActive = false;
let thinking = false;
let lastMoveSquares = null;
let soundOn = localStorage.getItem("cpuplay_sound") !== "off";
let lastEvalCp = 0;
let statsTimer = null;
let gameOverShown = false;

const els = {
  workerCountText: $("workerCountText"),
  authContainer: $("authContainer"),
  authModal: $("authModal"),
  donateModal: $("donateModal"),
  confirmModal: $("confirmModal"),
  authForm: $("authForm"),
  authError: $("authError"),
  authSubmitBtn: $("authSubmitBtn"),
  tabLogin: $("tabLogin"),
  tabRegister: $("tabRegister"),
  startBtn: $("startBtn"),
  resignBtn: $("resignBtn"),
  flipBtn: $("flipBtn"),
  overlay: $("boardOverlay"),
  overlayTitle: $("overlayTitle"),
  overlaySub: $("overlaySub"),
  overlayResult: $("overlayResult"),
  overlayRematch: $("overlayRematch"),
  overlayCard: document.querySelector(".overlay-card"),
  promotionPicker: $("promotionPicker"),
  promoOptions: $("promoOptions"),
  engineThinking: $("engineThinking"),
  providerText: $("providerText"),
  providerChip: $("providerChip"),
  cardProviderType: $("cardProviderType"),
  cardProviderDetails: $("cardProviderDetails"),
  nodeList: $("nodeList"),
  evalFill: $("evalFill"),
  evalGauge: $("evalGauge"),
  turnIndicator: $("turnIndicator"),
  humanPlayerName: $("humanPlayerName"),
  humanColorTag: $("humanColorTag"),
  youAvatar: $("youAvatar"),
  capturedYou: $("capturedYou"),
  capturedEngine: $("capturedEngine"),
  movesBody: $("movesBody"),
  movesScroll: $("movesScroll"),
  moveCountBadge: $("moveCountBadge"),
  lastMoveBadge: $("lastMoveBadge"),
  statGames: $("statGames"),
  statMoves: $("statMoves"),
  statWorkers: $("statWorkers"),
  donorsTableWrap: $("donorsTableWrap"),
  donateWorkerCount: $("donateWorkerCount"),
  workerCmdCode: $("workerCmdCode"),
  copyCmdBtn: $("copyCmdBtn"),
  workerCodeInput: $("workerCodeInput"),
  approveWorkerBtn: $("approveWorkerBtn"),
  workerAuthError: $("workerAuthError"),
  workerAuthModal: $("workerAuthModal"),
  workerAuthCode: $("workerAuthCode"),
  workerAuthAccount: $("workerAuthAccount"),
  workerAuthAllow: $("workerAuthAllow"),
  workerAuthDeny: $("workerAuthDeny"),
  reviewBtn: $("reviewBtn"),
  reviewBtnLabel: $("reviewBtnLabel"),
  reviewBadge: $("reviewBadge"),
  reviewIntro: $("reviewIntro"),
  reviewProgress: $("reviewProgress"),
  reviewBarFill: $("reviewBarFill"),
  reviewProgressText: $("reviewProgressText"),
  reviewSummary: $("reviewSummary"),
  reviewGraph: $("reviewGraph"),
  reviewList: $("reviewList"),
  soundToggle: $("soundToggle"),
  toasts: $("toasts"),
  confirmTitle: $("confirmTitle"),
  confirmText: $("confirmText"),
  confirmYes: $("confirmYes"),
  confirmNo: $("confirmNo")
};

/* ---------------- Audio ---------------- */
let audioCtx = null;
function ensureAudio() {
  if (!audioCtx) {
    try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { audioCtx = null; }
  }
  if (audioCtx && audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
  return audioCtx;
}
function tone(freq, dur, type = "sine", gain = 0.09, when = 0) {
  if (!soundOn) return;
  const ctx = ensureAudio();
  if (!ctx) return;
  const t0 = ctx.currentTime + when;
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  osc.frequency.exponentialRampToValueAtTime(Math.max(60, freq * 0.82), t0 + dur);
  g.gain.setValueAtTime(gain, t0);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  osc.connect(g).connect(ctx.destination);
  osc.start(t0);
  osc.stop(t0 + dur + 0.02);
}
const sound = {
  move: () => { tone(620, 0.06, "triangle", 0.07); tone(380, 0.05, "sine", 0.05, 0.02); },
  capture: () => { tone(300, 0.09, "square", 0.05); tone(180, 0.12, "triangle", 0.06, 0.02); },
  check: () => { tone(880, 0.09, "sine", 0.07); tone(1100, 0.1, "sine", 0.05, 0.08); },
  end: () => { tone(520, 0.12, "sine", 0.07); tone(660, 0.14, "sine", 0.07, 0.1); tone(790, 0.2, "sine", 0.06, 0.2); },
  start: () => { tone(440, 0.08, "sine", 0.06); tone(660, 0.12, "sine", 0.06, 0.07); }
};

/* ---------------- Toasts ---------------- */
function toast(message, type = "info", ms = 3800) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const dot = document.createElement("span");
  dot.className = "t-dot";
  const text = document.createElement("div");
  text.textContent = message;
  el.append(dot, text);
  els.toasts.appendChild(el);
  setTimeout(() => {
    el.classList.add("out");
    setTimeout(() => el.remove(), 220);
  }, ms);
}

/* ---------------- Modals ---------------- */
function openModal(id) {
  const el = $(id);
  if (!el) return;
  el.hidden = false;
  const focusable = el.querySelector("input, button");
  if (focusable) setTimeout(() => focusable.focus(), 40);
}
function closeModal(id) {
  const el = $(id);
  if (el) el.hidden = true;
}
function anyModalOpen() {
  return ["authModal", "donateModal", "confirmModal", "workerAuthModal"].some((id) => !$(id).hidden);
}
function closeTopModal() {
  if (!els.confirmModal.hidden) { resolveConfirm(false); return; }
  if (!els.workerAuthModal.hidden) { closeModal("workerAuthModal"); return; }
  if (!els.donateModal.hidden) { closeModal("donateModal"); return; }
  if (!els.authModal.hidden) closeModal("authModal");
}

let confirmResolver = null;
function resolveConfirm(value) {
  closeModal("confirmModal");
  if (confirmResolver) { const r = confirmResolver; confirmResolver = null; r(value); }
}
function askConfirm(title, text, yesLabel = "Confirm") {
  els.confirmTitle.textContent = title;
  els.confirmText.textContent = text;
  els.confirmYes.textContent = yesLabel;
  openModal("confirmModal");
  return new Promise((resolve) => { confirmResolver = resolve; });
}

/* ---------------- Worker authorization (device flow) ---------------- */
let pendingWorkerCode = "";

function normalizeWorkerCode(raw) {
  return (raw || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
}
function formatCode(code) {
  return code ? `${code.slice(0, 4)} ${code.slice(4)}` : "—";
}
async function approveWorkerCode(userCode, allowed) {
  try {
    const res = await fetch("/api/worker/device/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ user_code: userCode, allow: allowed })
    });
    const data = await res.json();
    if (res.ok && data.ok) return { ok: true, status: data.status };
    return { ok: false, error: (data && data.error) || "Authorization failed." };
  } catch (e) {
    return { ok: false, error: "Network error while authorizing. Try again." };
  }
}
function consumePendingWorkerCode() {
  let urlParam = "";
  try {
    const url = new URL(location.href);
    urlParam = url.searchParams.get("worker") || "";
    if (url.searchParams.has("worker")) {
      url.searchParams.delete("worker");
      const qs = url.search ? `${url.search}` : "";
      history.replaceState(null, "", url.pathname + qs + url.hash);
    }
  } catch (e) { /* keep param */ }
  return normalizeWorkerCode(urlParam || pendingWorkerCode);
}
function maybeOfferWorkerAuth() {
  const code = consumePendingWorkerCode();
  if (code && currentUser) {
    pendingWorkerCode = "";
    openWorkerAuth(code);
  }
}
function openWorkerAuth(code) {
  if (!els.workerAuthModal) {
    if (els.donateModal) {
      if (els.workerAuthError) els.workerAuthError.textContent = "";
      refreshStats();
      openModal("donateModal");
      els.workerCodeInput?.focus();
    }
    toast(`Approve worker code ${formatCode(code)} from the Donate CPU modal.`, "success", 5200);
    return;
  }
  els.workerAuthCode.textContent = formatCode(code);
  els.workerAuthAccount.textContent = `@${currentUser.username}`;
  els.workerAuthError.textContent = "";
  openModal("workerAuthModal");
}
async function handleWorkerAuthDecision(allowed) {
  if (!els.workerAuthCode) return;
  els.workerAuthError.textContent = "";
  const code = normalizeWorkerCode(els.workerAuthCode.textContent);
  closeModal("workerAuthModal");
  if (!code) return;
  const result = await approveWorkerCode(code, allowed);
  if (result.ok) {
    if (allowed) toast(`Worker authorized! It will donate as @${currentUser.username}.`, "success", 5000);
    else toast("Worker request denied.", "info", 3000);
    refreshStats();
  } else {
    pendingWorkerCode = code;
    toast(result.error, "error", 5200);
  }
}
async function handleManualApprove() {
  if (!currentUser) {
    openAuth(true);
    toast("Log in first — only account owners can authorize donors.", "info", 4200);
    return;
  }
  if (!els.workerCodeInput) return;
  els.workerAuthError.textContent = "";
  const code = normalizeWorkerCode(els.workerCodeInput.value);
  if (code.length < 6) {
    els.workerAuthError.textContent = "Enter the 8-character code printed by the worker script.";
    return;
  }
  els.approveWorkerBtn.disabled = true;
  const result = await approveWorkerCode(code, true);
  els.approveWorkerBtn.disabled = false;
  if (result.ok) {
    els.workerCodeInput.value = "";
    toast(`Worker authorized! It will donate as @${currentUser.username}.`, "success", 5000);
    refreshStats();
  } else {
    els.workerAuthError.textContent = result.error;
  }
}

/* ---------------- Board ---------------- */
function legalDests() {
  const dests = new Map();
  chess.SQUARES.forEach((sq) => {
    const moves = chess.moves({ square: sq, verbose: true });
    if (moves.length) dests.set(sq, moves.map((m) => m.to));
  });
  return dests;
}
function boardState() {
  const orientation = ground ? ground.state.orientation : (playerColor || "white");
  const canMove = gameActive && !thinking && !gameOverShown;
  return {
    fen: chess.fen(),
    orientation,
    turnColor: chess.turn() === "w" ? "white" : "black",
    check: chess.in_check(),
    lastMove: lastMoveSquares || undefined,
    movable: {
      free: false,
      color: canMove ? playerColor : undefined,
      dests: canMove ? legalDests() : new Map()
    },
    animation: { enabled: true, duration: 190 },
    highlight: { lastMove: true, check: true },
    events: {
      after: (orig, dest) => onPlayerMove(orig, dest)
    }
  };
}
function initBoard(orientation) {
  if (!ground) {
    ground = Chessground($("chessground"), { ...boardState(), orientation });
    ground.state.orientation = orientation;
  } else {
    ground.set({ ...boardState(), orientation });
  }
}
function syncBoard() {
  if (ground) ground.set(boardState());
}

/* ---------------- Move handling ---------------- */
async function onPlayerMove(orig, dest) {
  if (gameOverShown || thinking) { syncBoard(); return; }
  if (!gameActive) {
    syncBoard();
    toast("No game running — press New game to start.", "info", 3400);
    return;
  }

  const piece = chess.get(orig);
  const isPromotion = piece && piece.type === "p" && (dest[1] === "8" || dest[1] === "1");
  let promotion;
  if (isPromotion) {
    promotion = await askPromotion(piece.color);
    if (!promotion) { syncBoard(); return; }
  }

  let move;
  try {
    move = chess.move({ from: orig, to: dest, promotion });
  } catch (e) {
    syncBoard();
    return;
  }
  if (!move) { syncBoard(); return; }

  lastMoveSquares = [orig, dest];
  thinking = true;
  if (move.captured || isPromotion) sound.capture(); else sound.move();
  if (chess.in_check()) sound.check();

  renderAll();
  const uci = orig + dest + (move.promotion || "");
  const sent = send({ action: "move", uci });
  if (!sent) {
    thinking = false;
    toast("Connection lost. Reconnecting before your next move.", "error");
    syncBoard();
    return;
  }
  showThinking("Routing your move…", "Finding an available volunteer CPU.");
}

async function askPromotion(color) {
  return new Promise((resolve) => {
    els.promoOptions.innerHTML = "";
    const options = ["q", "r", "b", "n"];
    options.forEach((p) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "promo-opt";
      btn.innerHTML = `<span class="${color === "w" ? "light" : "dark"}">${PROMO_GLYPH[color][p]}</span>`;
      btn.addEventListener("click", () => {
        els.promotionPicker.hidden = true;
        cleanup();
        resolve(p);
      });
      els.promoOptions.appendChild(btn);
    });
    const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); done(null); } };
    const done = (value) => { els.promotionPicker.hidden = true; cleanup(); resolve(value); };
    function cleanup() {
      document.removeEventListener("keydown", onKey);
      els.promotionPicker.onclick = null;
    }
    document.addEventListener("keydown", onKey);
    els.promotionPicker.onclick = (e) => { if (e.target === els.promotionPicker) done(null); };
    els.promotionPicker.hidden = false;
    els.promoOptions.firstChild?.focus();
  });
}

/* ---------------- WebSocket ---------------- */
function wsUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/play?token=${encodeURIComponent(token)}`;
}
function send(payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  ws.send(JSON.stringify(payload));
  return true;
}
function ensureSocket() {
  return new Promise((resolve, reject) => {
    if (ws && ws.readyState === WebSocket.OPEN) { resolve(true); return; }
    if (ws && ws.readyState === WebSocket.CONNECTING) {
      const waitOpen = () => {
        if (ws.readyState === WebSocket.OPEN) resolve(true);
        else reject(new Error("Socket closed"));
      };
      ws.addEventListener("open", waitOpen, { once: true });
      ws.addEventListener("error", () => reject(new Error("Socket error")), { once: true });
      return;
    }

    let settled = false;
    const socket = new WebSocket(wsUrl());
    ws = socket;

    socket.addEventListener("open", () => {
      settled = true;
      resolve(true);
    });

    socket.addEventListener("message", (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      if (data.type === "auth_error") {
        if (!settled) { settled = true; reject(new Error("auth")); }
        clearSession();
        toast("Session expired. Please log in again.", "error");
        openAuth(true);
        return;
      }
      handleServerMessage(data);
    });

    socket.addEventListener("close", () => {
      if (!settled) { settled = true; reject(new Error("closed")); }
      handleSocketClosed();
    });

    socket.addEventListener("error", () => {
      if (!settled) { settled = true; reject(new Error("error")); }
    });
  });
}
function handleSocketClosed() {
  const wasActive = gameActive;
  gameActive = false;
  thinking = false;
  els.engineThinking.classList.remove("on");
  const dests = new Map();
  if (ground) ground.set({ movable: { color: undefined, dests } });
  els.resignBtn.disabled = true;
  if (wasActive) {
    hideOverlay();
    toast("Game connection lost. Start a new game to continue.", "warn", 5000);
  }
  updateTurn();
}

async function connectAndStart() {
  try {
    await ensureSocket();
    if (!send({ action: "new_game", color: colorPref })) {
      toast("Could not reach the game server.", "error");
      return;
    }
    showThinking("Setting up your match…", "Warming up the engine network.");
  } catch (e) {
    if (e.message === "auth") return;
    toast("Could not connect. Please try again.", "error");
  }
}

async function startNewGame() {
  if (!currentUser) {
    openAuth(true);
    toast("Create an instant account to play. No limits.", "info");
    return;
  }
  if (gameActive && !gameOverShown) {
    const ok = await askConfirm("Abandon current game?", "Starting a new game will end the one in progress.", "Start new game");
    if (!ok) return;
  }
  resetGameState();
  await connectAndStart();
}

function resetGameState() {
  gameActive = false;
  thinking = false;
  gameOverShown = false;
  lastMoveSquares = null;
  lastEvalCp = 0;
  chess.reset();
  els.engineThinking.classList.remove("on");
  els.resignBtn.disabled = true;
  setEval(0);
  clearReview();
  hideOverlay();
  renderAll();
}

/* ---------------- Server events ---------------- */
function handleServerMessage(msg) {
  switch (msg.type) {
    case "game_started": {
      gameActive = true;
      thinking = false;
      gameOverShown = false;
      playerColor = msg.player_color;
      chess.reset();
      lastMoveSquares = null;
      lastEvalCp = 0;
      els.resignBtn.disabled = false;
      els.engineThinking.classList.remove("on");
      setEval(0);
      initBoard(playerColor);
      renderAll();
      updatePlayerIdentity();
      providerIdle();
      hideOverlay();
      if (playerColor === "black") {
        showThinking("8Chess moves first", "Selecting a volunteer CPU for the opening move.");
      }
      sound.start();
      toast(`New game — you play ${playerColor}.`, "info", 2600);
      break;
    }
    case "engine_thinking": {
      thinking = true;
      els.engineThinking.classList.add("on");
      els.providerChip.textContent = "computing";
      els.providerChip.classList.remove("chip-live");
      showThinking("8Chess is thinking", msg.provider || "Routing to a volunteer CPU…");
      updateTurn();
      syncBoard();
      break;
    }
    case "move_made": {
      if (msg.by === "engine") {
        applyEngineMove(msg);
      }
      if (msg.is_game_over) {
        endGame(msg.result, msg.by === "engine" ? "The engine finished the game." : "Game finished.");
      }
      break;
    }
    case "game_over": {
      endGame(msg.result, msg.reason || "Game over");
      break;
    }
    case "error": {
      thinking = false;
      els.engineThinking.classList.remove("on");
      hideOverlay();
      if (msg.fen) {
        try { chess.load(msg.fen); } catch (e) { /* keep local state */ }
      }
      syncBoard();
      updateTurn();
      toast(msg.message || "The move was rejected.", "error");
      break;
    }
    case "auth_error": {
      clearSession();
      openAuth(true);
      break;
    }
  }
}

function applyEngineMove(msg) {
  const uci = msg.uci || "";
  const from = uci.slice(0, 2);
  const to = uci.slice(2, 4);
  const promotion = uci.length > 4 ? uci[4] : undefined;

  let move = null;
  try { move = chess.move({ from, to, promotion }); } catch (e) { move = null; }

  if (!move && msg.fen) {
    try { chess.load(msg.fen); } catch (e) { /* ignore */ }
  }

  lastMoveSquares = [from, to];
  thinking = false;
  gameActive = !msg.is_game_over;
  els.engineThinking.classList.remove("on");
  if (move) {
    if (move.captured) sound.capture(); else sound.move();
    if (chess.in_check()) sound.check();
  }
  updateProvider(msg);
  setEval(msg.eval);
  renderAll();
  hideOverlay();
  if (!msg.is_game_over) {
    els.providerChip.textContent = msg.is_volunteer ? "volunteer" : "server node";
    els.providerChip.classList.add("chip-live");
  }
  syncBoard();
  updateTurn();
}

function endGame(result, reason) {
  if (gameOverShown) return;
  gameOverShown = true;
  gameActive = false;
  thinking = false;
  els.engineThinking.classList.remove("on");
  els.resignBtn.disabled = true;
  sound.end();
  syncBoard();
  updateTurn();

  const text = resultText(result);
  els.overlayCard.classList.add("gameover");
  els.overlayTitle.textContent = "Game over";
  els.overlaySub.textContent = reason || "";
  els.overlayResult.hidden = false;
  els.overlayResult.textContent = text;
  els.overlayResult.style.color = result === playerWinResult() ? "var(--lime)" : (result === "1/2-1/2" ? "var(--muted)" : "var(--amber)");
  els.overlayRematch.hidden = false;
  els.overlay.hidden = false;
  updateReviewAvailability();
  refreshStats();
}

function resultText(result) {
  if (!result) return "Finished";
  if (result === "1/2-1/2") return "Draw";
  const playerWon = result === playerWinResult();
  return playerWon ? "You win" : "8Chess wins";
}
function playerWinResult() {
  return playerColor === "white" ? "1-0" : "0-1";
}

/* ---------------- Overlay ---------------- */
function showThinking(title, sub) {
  els.overlayCard.classList.remove("gameover");
  els.overlayTitle.textContent = title;
  els.overlaySub.textContent = sub || "";
  els.overlayResult.hidden = true;
  els.overlayRematch.hidden = true;
  els.overlay.hidden = false;
}
function hideOverlay() {
  els.overlay.hidden = true;
}

/* ---------------- Render ---------------- */
function renderAll() {
  renderMoves();
  renderCaptured();
  updateTurn();
  updateReviewAvailability();
}

function renderMoves() {
  const history = chess.history();
  els.moveCountBadge.textContent = `${history.length} ${history.length === 1 ? "move" : "moves"}`;
  if (!history.length) {
    els.movesBody.innerHTML = '<tr class="empty-row"><td colspan="3">Make a move to start the game</td></tr>';
    els.lastMoveBadge.textContent = "—";
    return;
  }
  const rows = [];
  for (let i = 0; i < history.length; i += 2) {
    const num = i / 2 + 1;
    const white = history[i];
    const black = history[i + 1];
    const isLastWhite = i === history.length - 1;
    const isLastBlack = i + 1 === history.length - 1;
    rows.push(`<tr>
      <td class="num">${num}.</td>
      <td class="san ${isLastWhite ? "latest" : ""}">${white || ""}</td>
      <td class="san ${isLastBlack ? "latest" : ""}">${black || ""}</td>
    </tr>`);
  }
  els.movesBody.innerHTML = rows.join("");
  els.lastMoveBadge.textContent = history[history.length - 1];
  els.movesScroll.scrollTop = els.movesScroll.scrollHeight;
}

function renderCaptured() {
  const board = chess.board();
  const remaining = { w: {}, b: {} };
  for (const row of board) {
    for (const sq of row) {
      if (!sq) continue;
      remaining[sq.color][sq.type] = (remaining[sq.color][sq.type] || 0) + 1;
    }
  }
  const captured = { w: [], b: [] };
  let capturedValue = { w: 0, b: 0 };
  for (const color of ["w", "b"]) {
    for (const type of Object.keys(INITIAL_COUNTS)) {
      const missing = Math.max(0, INITIAL_COUNTS[type] - (remaining[color][type] || 0));
      for (let i = 0; i < missing; i++) {
        captured[color].push({ type, glyph: PIECE_GLYPH[color][type] });
        capturedValue[color] += PIECE_VALUE[type];
      }
    }
  }

  const playerIsWhite = playerColor === "white";
  const playerColorCode = playerIsWhite ? "w" : "b";
  const engineColorCode = playerIsWhite ? "b" : "w";

  const youCaptured = captured[engineColorCode];
  const engineCaptured = captured[playerColorCode];

  const youDiff = capturedValue[engineColorCode] - capturedValue[playerColorCode];
  const engineDiff = -youDiff;

  els.capturedYou.innerHTML = chips(youCaptured, youDiff);
  els.capturedEngine.innerHTML = chips(engineCaptured, engineDiff);
}
function chips(list, diff) {
  const pieces = list.map((p) => `<span class="cap">${p.glyph}</span>`).join("");
  const adv = diff > 0 ? `<span class="adv">+${diff}</span>` : "";
  return pieces + adv;
}

function updateTurn() {
  if (!playerColor) {
    els.turnIndicator.textContent = currentUser ? "Choose a side and start a game." : "Log in to play. No limits, ever.";
    return;
  }
  if (gameOverShown) {
    els.turnIndicator.textContent = "Game finished — start a new game.";
    return;
  }
  if (!gameActive) {
    els.turnIndicator.textContent = "Ready when you are.";
    return;
  }
  const isPlayerTurn = (chess.turn() === "w" && playerColor === "white") || (chess.turn() === "b" && playerColor === "black");
  if (thinking) {
    els.turnIndicator.textContent = "8Chess is computing a reply…";
  } else if (isPlayerTurn) {
    els.turnIndicator.textContent = "Your turn.";
  } else {
    els.turnIndicator.textContent = "Waiting for 8Chess…";
  }
}

function updatePlayerIdentity() {
  if (currentUser) {
    els.humanPlayerName.textContent = currentUser.username;
    els.youAvatar.textContent = currentUser.username.slice(0, 1).toUpperCase();
  }
  if (playerColor) {
    els.humanColorTag.textContent = `playing ${playerColor}`;
    els.humanColorTag.classList.remove("ghost");
  }
}

function updateProvider(msg) {
  const provider = msg.provider || "8Chess";
  const isVolunteer = !!msg.is_volunteer;
  els.providerText.textContent = provider;
  els.cardProviderType.textContent = isVolunteer ? "Volunteer node" : "Server node";
  els.cardProviderType.style.color = isVolunteer ? "var(--lime)" : "var(--blue)";
  els.cardProviderDetails.textContent = isVolunteer
    ? `This move was calculated by ${provider}. Thank a donor by running a worker yourself.`
    : "No idle volunteer was available, so the server-side 8Chess node calculated this move instantly.";
  if (msg.depth) {
    els.cardProviderDetails.textContent += ` Depth ${msg.depth}.`;
  }
  els.providerChip.textContent = isVolunteer ? "volunteer" : "server node";
  els.providerChip.classList.add("chip-live");
}
function providerIdle() {
  els.providerText.textContent = "Distributed engine network";
  els.providerChip.textContent = "standby";
  els.providerChip.classList.remove("chip-live");
  els.cardProviderType.textContent = "Waiting for a game";
  els.cardProviderType.style.color = "var(--text)";
  els.cardProviderDetails.textContent = "Moves are calculated by volunteer CPUs. If the network is idle, a server-side 8Chess node answers instantly.";
}

function setEval(cp) {
  lastEvalCp = typeof cp === "number" ? cp : 0;
  let whiteCp = lastEvalCp;
  if (playerColor) {
    const engineColor = playerColor === "white" ? "b" : "w";
    if (engineColor === "b") whiteCp = -lastEvalCp;
  }
  const winProb = 1 / (1 + Math.pow(10, -whiteCp / 400));
  const pct = Math.max(5, Math.min(95, winProb * 100));
  els.evalFill.style.height = `${pct}%`;
  const display = (whiteCp / 100).toFixed(2);
  els.evalGauge.title = `Engine evaluation: ${whiteCp > 0 ? "+" : ""}${display}`;
  els.evalGauge.classList.toggle("black-edge", whiteCp < 0);
}

/* ---------------- Auth ---------------- */
function clearSession() {
  token = "";
  currentUser = null;
  gameActive = false;
  thinking = false;
  localStorage.removeItem("cpuplay_token");
  clearReview();
  if (ws) { try { ws.close(); } catch (e) {} ws = null; }
  renderLoggedOut();
}
function renderLoggedIn(user) {
  currentUser = user;
  els.humanPlayerName.textContent = user.username;
  els.youAvatar.textContent = user.username.slice(0, 1).toUpperCase();
  els.authContainer.innerHTML = `
    <span class="user-chip" title="Signed in as ${escapeHtml(user.username)}">${escapeHtml(user.username)}</span>
    <button class="icon-btn" id="logoutBtn" title="Log out" aria-label="Log out">
      <svg viewBox="0 0 24 24" fill="none"><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 8l4 4-4 4M14 12H4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>`;
  $("logoutBtn").addEventListener("click", logout);
}
function renderLoggedOut() {
  els.humanPlayerName.textContent = "Guest";
  els.humanColorTag.textContent = "not signed in";
  els.humanColorTag.classList.add("ghost");
  els.youAvatar.textContent = "?";
  els.authContainer.innerHTML = '<button class="btn btn-primary" id="openLoginBtn">Log in</button>';
  $("openLoginBtn").addEventListener("click", () => openAuth(true));
}
async function checkAuth() {
  if (!token) { renderLoggedOut(); return; }
  try {
    const res = await fetch("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } });
    const data = await res.json();
    if (data.ok && data.user) {
      renderLoggedIn(data.user);
    } else {
      token = "";
      localStorage.removeItem("cpuplay_token");
      renderLoggedOut();
    }
  } catch (e) {
    renderLoggedOut();
  }
}
async function logout() {
  if (gameActive) {
    const ok = await askConfirm("Log out?", "Your current game will end.", "Log out");
    if (!ok) return;
  }
  clearSession();
  resetGameState();
  toast("Signed out.", "info", 2200);
}
function openAuth(loginMode = true) {
  setAuthMode(loginMode);
  els.authError.textContent = "";
  els.authForm.reset();
  openModal("authModal");
  setTimeout(() => $("authUsername").focus(), 60);
}
function setAuthMode(loginMode) {
  els.authSubmitBtn.dataset.mode = loginMode ? "login" : "register";
  els.authSubmitBtn.textContent = loginMode ? "Log in" : "Create account";
  els.tabLogin.classList.toggle("active", loginMode);
  els.tabRegister.classList.toggle("active", !loginMode);
  const pw = $("authPassword");
  pw.autocomplete = loginMode ? "current-password" : "new-password";
  els.authError.textContent = "";
}
async function submitAuth(e) {
  e.preventDefault();
  const mode = els.authSubmitBtn.dataset.mode || "login";
  const username = $("authUsername").value.trim();
  const password = $("authPassword").value;
  if (!username || password.length < 4) {
    els.authError.textContent = "Enter a username and a password of at least 4 characters.";
    return;
  }
  els.authSubmitBtn.disabled = true;
  els.authError.textContent = "";
  try {
    const res = await fetch(`/api/auth/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (!data.ok) {
      els.authError.textContent = data.error || "Authentication failed.";
      return;
    }
    token = data.token;
    localStorage.setItem("cpuplay_token", token);
    renderLoggedIn({ id: data.user_id, username: data.username });
    updatePlayerIdentity();
    closeModal("authModal");
    toast(mode === "register" ? `Welcome, ${data.username}!` : `Welcome back, ${data.username}.`, "info");
    maybeOfferWorkerAuth();
    updateReviewAvailability();
  } catch (err) {
    els.authError.textContent = "Network error. Please try again.";
  } finally {
    els.authSubmitBtn.disabled = false;
  }
}
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}

/* ---------------- Stats ---------------- */
async function refreshStats() {
  try {
    const res = await fetch("/api/stats", { cache: "no-store" });
    const data = await res.json();
    if (!data.ok) return;
    const online = data.workers_online || 0;
    els.workerCountText.textContent = `${online} CPU${online === 1 ? "" : "s"} online`;
    els.donateWorkerCount.textContent = `${online} online`;
    els.statGames.textContent = data.total_games ?? "—";
    els.statMoves.textContent = data.volunteer_moves ?? "—";
    els.statWorkers.textContent = online;

    const origin = location.origin;
    const cmd = `curl -sSL ${origin}/worker.py | python3 - --server ${origin}`;
    els.workerCmdCode.textContent = cmd;
    document.querySelectorAll(".origin-text").forEach((el) => { el.textContent = origin; });

    renderNodes(data.workers || []);
    renderDonors(data.top_donors || [], data.workers || []);
  } catch (e) {
    /* offline stats are non-critical */
  }
}
function renderNodes(workers) {
  if (!workers.length) {
    els.nodeList.innerHTML = '<span class="node-empty">No donors online — the server node is covering moves.</span>';
    return;
  }
  els.nodeList.innerHTML = workers.map((w) => `
    <span class="node-chip ${w.busy ? "busy" : ""}" title="${escapeHtml(w.system || "")}">
      <span class="dot"></span>${escapeHtml(w.name)} · ${w.threads}T
    </span>`).join("");
}
function renderDonors(donors, workers) {
  const onlineNames = new Set(workers.map((w) => w.name));
  if (!donors.length) {
    els.donorsTableWrap.innerHTML = '<p class="empty-text">No moves served yet. Be the first donor.</p>';
    return;
  }
  const rows = donors.map((d) => `
    <tr>
      <td class="donor-name">${escapeHtml(d.name)}${onlineNames.has(d.name) ? ' <span class="chip chip-live">online</span>' : ""}</td>
      <td>${escapeHtml(d.system || "")}</td>
      <td>${d.threads}T</td>
      <td class="donor-moves">${d.moves}</td>
    </tr>`).join("");
  els.donorsTableWrap.innerHTML = `
    <table class="donor-table">
      <thead><tr><th>Donor</th><th>System</th><th>Threads</th><th>Moves</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

/* ---------------- Game review (volunteer-powered) ---------------- */
let reviewBusy = false;

function clearReview() {
  if (!els.reviewBtn) return;
  els.reviewBadge.textContent = "idle";
  els.reviewBtn.disabled = true;
  els.reviewBtnLabel.textContent = "Review the game";
  els.reviewProgress.hidden = true;
  els.reviewSummary.hidden = true;
  els.reviewGraph.hidden = true;
  els.reviewList.hidden = true;
  els.reviewSummary.innerHTML = "";
  els.reviewGraph.innerHTML = "";
  els.reviewList.innerHTML = "";
  els.reviewIntro.hidden = false;
}

function updateReviewAvailability() {
  if (!els.reviewBtn) return;
  const n = chess.history().length;
  const ready = !!currentUser && n >= 2 && !reviewBusy;
  els.reviewBtn.disabled = !ready;
  if (!reviewBusy) {
    els.reviewBtnLabel.textContent = (n >= 2 && !gameActive) || gameOverShown
      ? "Review this game"
      : "Analyze so far";
  }
  els.reviewBadge.textContent = gameOverShown ? "game over" : (n > 0 ? "live" : "idle");
}

async function reviewGame() {
  if (!currentUser) {
    openAuth(true);
    toast("Log in to use volunteer-powered game review.", "info", 4000);
    return;
  }
  if (reviewBusy) return;
  const verboose = chess.history({ verbose: true });
  if (verboose.length < 2) return;
  if (gameActive && !gameOverShown) {
    const ok = await askConfirm("Analyze mid-game?", "The current position will be reviewed. Continue?", "Analyze");
    if (!ok) return;
  }

  const uciMoves = verboose.map((m) => m.from + m.to + (m.promotion || ""));
  reviewBusy = true;
  els.reviewBtn.disabled = true;
  els.reviewIntro.hidden = true;
  els.reviewProgress.hidden = false;
  els.reviewBadge.textContent = "analyzing";
  els.reviewProgressText.textContent = "Routing positions to the volunteer network…";
  els.reviewBarFill.style.width = "12%";

  try {
    const res = await fetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ moves: uciMoves, movetime: 250 })
    });
    const data = await res.json();
    els.reviewBarFill.style.width = "92%";
    if (!res.ok || !data.ok) {
      toast(data.error || "Review failed. Try again shortly.", "error", 5000);
      els.reviewProgress.hidden = true;
      return;
    }
    renderReview(data.moves || [], data.summary || null, data.providers || {});
  } catch (e) {
    els.reviewProgress.hidden = true;
    toast("Network error while reviewing. Please try again.", "error");
  } finally {
    reviewBusy = false;
    updateReviewAvailability();
  }
}

function evalToY(cp) {
  const clamped = Math.max(-800, Math.min(800, cp));
  return 50 - (clamped / 800) * 46;
}

function renderReview(moveData, summary, providers) {
  els.reviewProgress.hidden = true;
  els.reviewProgressText.textContent = "Analyzing…";
  els.reviewBarFill.style.width = "100%";
  setTimeout(() => { els.reviewProgress.hidden = true; els.reviewBarFill.style.width = "12%"; }, 400);

  const sans = chess.history();
  const total = moveData.length;

  // Summary chips
  if (summary) {
    const acc = summary.accuracy || { w: 0, b: 0 };
    const counts = summary.counts || {};
    const myColor = playerColor === "black" ? "b" : "w";
    const myAcc = acc[myColor] ?? "—";
    els.reviewSummary.hidden = false;
    els.reviewSummary.innerHTML = `
      <div class="rs-item big"><span class="rs-value" id="reviewMyAcc">${myAcc}%</span><span class="rs-label">your accuracy</span></div>
      <div class="rs-item"><span class="rs-value">${acc[myColor === "w" ? "b" : "w"] ?? "—"}%</span><span class="rs-label">8Chess</span></div>
      <div class="rs-item"><span class="rs-value danger">${counts.blunder || 0}</span><span class="rs-label">blunders</span></div>
      <div class="rs-item"><span class="rs-value warn">${counts.mistake || 0}</span><span class="rs-label">mistakes</span></div>
      <div class="rs-item"><span class="rs-value ok">${counts.inaccuracy || 0}</span><span class="rs-label">inaccuracies</span></div>`;
  }

  // Eval graph (white advantage, top = up for white)
  if (total > 1) {
    const w = Math.max(120, Math.min(720, total * 26));
    let pts = "";
    let marks = "";
    moveData.forEach((mv, idx) => {
      const x = (idx / (total - 1)) * w;
      const y = evalToY(mv.eval);
      pts += `${x.toFixed(1)},${y.toFixed(1)} `;
      if (mv.tag && mv.tag !== "good") {
        const cls = mv.tag === "blunder" ? "g-blunder" : (mv.tag === "mistake" ? "g-mistake" : "g-inacc");
        marks += `<circle class="${cls}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.2"/>`;
      }
    });
    els.reviewGraph.hidden = false;
    els.reviewGraph.innerHTML = `
      <svg viewBox="0 0 ${w} 100" preserveAspectRatio="none" class="rgraph">
        <line x1="0" y1="50" x2="${w}" y2="50" class="rg-zero"/>
        <polyline points="${pts}" class="rg-line"/>
        ${marks}
      </svg>`;
  }

  // Per-move rows (worst first)
  const TAG_LABEL = { blunder: "Blunder", mistake: "Mistake", inaccuracy: "Inaccuracy", good: "Good" };
  const rows = moveData
    .map((mv, idx) => ({ mv, idx }))
    .sort((a, b) => (b.mv.loss || 0) - (a.mv.loss || 0))
    .slice(0, 24);

  if (rows.length) {
    const items = rows.map(({ mv, idx }) => {
      const moveNo = Math.floor(idx / 2) + 1;
      const dot = idx % 2 === 0 ? "." : "…";
      const san = sans[idx] || mv.played;
      const tag = mv.tag || "good";
      const best = bestMoveSan(idx, mv.best, mv.played);
      const bestHtml = (best && best !== san)
        ? `<span class="rev-best">best: ${escapeHtml(best)}</span>`
        : "";
      return `<div class="rev-row ${tag}">
        <span class="rev-no">${moveNo}${dot}</span>
        <span class="rev-san">${escapeHtml(String(san))}</span>
        <span class="rev-tag t-${tag}">${TAG_LABEL[tag] || "Good"}</span>
        <span class="rev-eval">${fmtEval(mv.eval, idx)}</span>
        ${bestHtml}
      </div>`;
    });
    els.reviewList.hidden = false;
    els.reviewList.innerHTML = items.join("");
  }

  const provNames = Object.keys(providers);
  els.reviewBadge.textContent = total ? `${total} positions` : "idle";
  if (provNames.length) {
    els.reviewIntro.hidden = false;
    els.reviewIntro.textContent = provNames.map((p) => `${p} · ${providers[p]}`).join("  ·  ");
  }
}

function fmtEval(cpWhite, moveIdx) {
  const myWhite = playerColor !== "black";
  const myCp = myWhite ? cpWhite : -cpWhite;
  const sign = myCp > 0 ? "+" : (myCp < 0 ? "−" : "");
  const cp = (Math.abs(myCp) / 100).toFixed(2);
  const cls = myCp > 40 ? "pos" : (myCp < -40 ? "neg" : "");
  return `<span class="rev-cp ${cls}">${sign}${cp}</span>`;
}

function bestMoveSan(idx, bestUci, playedUci) {
  try {
    const t = new window.Chess();
    for (let i = 0; i < idx; i++) {
      const m = chess.history()[i];
      t.move(m);
    }
    const mv = t.move({
      from: bestUci.slice(0, 2),
      to: bestUci.slice(2, 4),
      promotion: bestUci.length > 4 ? bestUci[4] : undefined
    });
    return mv ? mv.san : (bestUci || "");
  } catch (e) {
    return bestUci || "";
  }
}

/* ---------------- Wire up ---------------- */
function wireEvents() {
  document.querySelectorAll(".seg").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".seg").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      colorPref = btn.dataset.color;
    });
  });

  els.startBtn.addEventListener("click", startNewGame);
  els.overlayRematch.addEventListener("click", () => {
    resetGameState();
    connectAndStart();
  });
  els.resignBtn.addEventListener("click", async () => {
    if (!gameActive) return;
    const ok = await askConfirm("Resign this game?", "The game will be recorded as a loss.", "Resign");
    if (ok) send({ action: "resign" });
  });
  els.flipBtn.addEventListener("click", () => { if (ground) ground.toggleOrientation(); });

  function openDonate() {
    if (!currentUser) {
      openAuth(true);
      toast("Log in first — donors must own their 8Chess account.", "info", 4200);
      return;
    }
    refreshStats();
    openModal("donateModal");
  }
  $("openDonateBtn").addEventListener("click", openDonate);
  $("footerHow").addEventListener("click", (e) => {
    e.preventDefault();
    openDonate();
  });

  if (els.approveWorkerBtn) els.approveWorkerBtn.addEventListener("click", handleManualApprove);
  if (els.workerCodeInput) els.workerCodeInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); handleManualApprove(); }
  });
  if (els.workerAuthAllow) els.workerAuthAllow.addEventListener("click", () => handleWorkerAuthDecision(true));
  if (els.workerAuthDeny) els.workerAuthDeny.addEventListener("click", () => handleWorkerAuthDecision(false));

  if (els.reviewBtn) els.reviewBtn.addEventListener("click", reviewGame);

  els.authForm.addEventListener("submit", submitAuth);
  els.tabLogin.addEventListener("click", () => setAuthMode(true));
  els.tabRegister.addEventListener("click", () => setAuthMode(false));

  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(btn.dataset.close));
  });
  document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
    backdrop.addEventListener("click", (e) => {
      if (e.target !== backdrop) return;
      if (backdrop.id === "confirmModal") resolveConfirm(false);
      else closeModal(backdrop.id);
    });
  });

  els.confirmYes.addEventListener("click", () => resolveConfirm(true));
  els.confirmNo.addEventListener("click", () => resolveConfirm(false));

  els.copyCmdBtn.addEventListener("click", async () => {
    const text = els.workerCmdCode.textContent;
    try {
      await navigator.clipboard.writeText(text);
      els.copyCmdBtn.textContent = "Copied";
    } catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      els.copyCmdBtn.textContent = "Copied";
    }
    setTimeout(() => { els.copyCmdBtn.textContent = "Copy"; }, 1800);
  });

  els.soundToggle.addEventListener("click", () => {
    soundOn = !soundOn;
    localStorage.setItem("cpuplay_sound", soundOn ? "on" : "off");
    els.soundToggle.classList.toggle("muted", !soundOn);
    els.soundToggle.setAttribute("aria-pressed", String(soundOn));
    if (soundOn) { ensureAudio(); sound.move(); }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && anyModalOpen()) { closeTopModal(); return; }
    if (e.key.toLowerCase() === "f" && !anyModalOpen() && document.activeElement.tagName !== "INPUT") {
      if (ground) ground.toggleOrientation();
    }
  });
}

/* ---------------- Init ---------------- */
function init() {
  els.soundToggle.classList.toggle("muted", !soundOn);
  els.soundToggle.setAttribute("aria-pressed", String(soundOn));
  wireEvents();
  initBoard("white");
  renderAll();
  checkAuth().then(() => maybeOfferWorkerAuth());
  refreshStats();
  statsTimer = setInterval(refreshStats, 10000);
  updateTurn();
}

init();
