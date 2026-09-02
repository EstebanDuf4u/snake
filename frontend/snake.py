from browser import document, window, aio
import json
import math
import random

from parser import WSFrontParser


# ── DOM / canvas ──────────────────────────────────────────────────────────────
lb        = document["lb"]
status_el = document["status"] if "status" in document else None
score_el  = document["score"]

cv  = document["cv"]
ctx = cv.getContext("2d")

GRID = 30
CELL = cv.width // GRID

# ── State ─────────────────────────────────────────────────────────────────────
t0   = 0
ws   = None
mode = "solo"
auth_token = window.localStorage.getItem("snake_token")
auth_username = window.localStorage.getItem("snake_username")

game_state = {
    "snake": [(5, 5), (6, 5), (7, 5)],
    "apple": (10, 10),
    "score": 0,
    "direction": "right",
    "running": False,
    "mode": "solo",
    "game_over": False,
    "countdown": 0,
    "snakes": {},
    "apples": [],
    "scores": {},
    "directions": {},
    "alive": {},
    "my_player_id": None,
    "names": {},
    "winner_id": None,
    "powerups": [],
    "slow_ticks": {},
    "lobby": False,
    "lobby_players": [],
    "lobby_room_id": "",
}

# ── Animation state ───────────────────────────────────────────────────────────
particles    = []
score_popups = []
apple_pulse  = 0.0
_last_ts     = [0.0]
_current_ts  = [0.0]
_prev_score  = [0]
_prev_scores = [{}]
_death_ts      = {}   # pid -> timestamp (ms) quand le serpent est mort
_prev_countdown  = [0]
_prev_game_over  = [False]
_prev_slow_ticks = [{}]

# ── Interpolation ──────────────────────────────────────────────────────────────
_it_solo_prev = [None]   # snapshot avant le tick
_it_solo_curr = [None]   # snapshot après le tick
_it_solo_ts   = [0.0]    # timestamp du dernier tick
_it_solo_iv   = [220.0]  # intervalle estimé (ms)

_it_multi_prev = [{}]
_it_multi_curr = [{}]
_it_multi_ts   = [0.0]
_it_multi_iv   = [150.0]


def _lerp_snake(prev, curr, t):
    result = []
    for i, pos in enumerate(curr):
        if i < len(prev):
            px, py = prev[i]
            cx, cy = pos
            result.append((px + (cx - px) * t, py + (cy - py) * t))
        else:
            result.append(pos)
    return result


def _predict_snake(snake, direction):
    """Prédit la position au prochain tick pour l'extrapolation."""
    if not snake:
        return snake
    delta = {"up": (0,-1), "down": (0,1), "left": (-1,0), "right": (1,0)}.get(direction, (1,0))
    hx, hy = snake[-1]
    new_head = (hx + delta[0], hy + delta[1])
    return list(snake[1:]) + [new_head]


# ── localStorage : restaurer le pseudo ───────────────────────────────────────
_saved_name = window.localStorage.getItem("snake_pseudo")
if _saved_name and _saved_name.lower() != "player":
    document["name"].value = _saved_name


# ── API ───────────────────────────────────────────────────────────────────────
_lb_period = ["all"]

async def load_leaderboard(period=None):
    if period is None:
        period = _lb_period[0]
    r = await window.fetch(f"/api/leaderboard?limit=10&period={period}")
    if not r.ok:
        lb.html = '<div class="lb-empty">API indisponible</div>'
        return
    data = await r.json()
    if not data:
        lb.html = '<div class="lb-empty">aucun score encore</div>'
        return
    medals = ["rank-1", "rank-2", "rank-3"]
    rows = []
    for i, x in enumerate(data):
        rank_cls = medals[i] if i < 3 else "rank-n"
        rank_sym = ["🥇", "🥈", "🥉"][i] if i < 3 else str(i + 1)
        rows.append(
            f'<div class="lb-row">'
            f'<span class="lb-rank {rank_cls}">{rank_sym}</span>'
            f'<span class="lb-name">{x["name"]}</span>'
            f'<span class="lb-score">{x["score"]}</span>'
            f'</div>'
        )
    lb.html = "".join(rows)


async def submit_score(name, score_value, duration_ms):
    payload = {"name": name, "score": score_value, "duration_ms": duration_ms}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}",
    }
    r = await window.fetch("/api/score", {
        "method": "POST",
        "headers": headers,
        "body": json.dumps(payload),
    })
    if not r.ok:
        raise Exception(await r.text())


# ── Particles ─────────────────────────────────────────────────────────────────
def spawn_particles(cx, cy, color, count=12):
    for _ in range(count):
        angle = random.uniform(0, math.pi * 2)
        speed = random.uniform(60, 200)
        life  = random.uniform(0.25, 0.55)
        particles.append({
            "x": cx, "y": cy,
            "vx": math.cos(angle) * speed,
            "vy": math.sin(angle) * speed,
            "life": life, "max_life": life,
            "r": random.uniform(2, 4.5),
            "color": color,
        })

def update_and_draw_particles(dt):
    for p in particles[:]:
        p["life"] -= dt
        if p["life"] <= 0:
            particles.remove(p)
            continue
        p["x"] += p["vx"] * dt
        p["y"] += p["vy"] * dt
        a = p["life"] / p["max_life"]
        ctx.globalAlpha = a
        ctx.shadowBlur  = 6
        ctx.shadowColor = p["color"]
        ctx.beginPath()
        ctx.fillStyle = p["color"]
        ctx.arc(p["x"], p["y"], p["r"] * a + 0.5, 0, math.pi * 2)
        ctx.fill()
    ctx.globalAlpha = 1.0
    ctx.shadowBlur  = 0


# ── Score popups (+1) ─────────────────────────────────────────────────────────
def spawn_score_popup(cx, cy):
    score_popups.append({"x": cx, "y": cy, "life": 0.75, "max_life": 0.75})

def draw_score_popups(dt):
    ctx.font      = "bold 14px ui-monospace, monospace"
    ctx.textAlign = "center"
    for p in score_popups[:]:
        p["life"] -= dt
        if p["life"] <= 0:
            score_popups.remove(p)
            continue
        p["y"] -= dt * 45
        a = p["life"] / p["max_life"]
        ctx.globalAlpha = a
        ctx.shadowBlur  = 8
        ctx.shadowColor = "#FFD43B"
        ctx.fillStyle   = "#FFD43B"
        ctx.fillText("+1", p["x"], p["y"])
    ctx.globalAlpha = 1.0
    ctx.shadowBlur  = 0


# ── Audio ─────────────────────────────────────────────────────────────────────
_ac = [None]

def _get_ac():
    if _ac[0] is None:
        try:
            _ac[0] = window.AudioContext.new()
        except Exception:
            try:
                _ac[0] = window.webkitAudioContext.new()
            except Exception:
                pass
    return _ac[0]

def play_beep(freq=440, dur=0.1, vol=0.18, shape="sine"):
    ac = _get_ac()
    if not ac:
        return
    try:
        if ac.state == "suspended":
            ac.resume()
        osc  = ac.createOscillator()
        gain = ac.createGain()
        osc.connect(gain)
        gain.connect(ac.destination)
        osc.type = shape
        osc.frequency.value = freq
        gain.gain.setValueAtTime(vol, ac.currentTime)
        gain.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + dur)
        osc.start(ac.currentTime)
        osc.stop(ac.currentTime + dur + 0.01)
    except Exception:
        pass


# ── Power-ups ─────────────────────────────────────────────────────────────────
def draw_powerup(x, y, ptype):
    cx = x * CELL + CELL / 2
    cy = y * CELL + CELL / 2
    if ptype == "gold":
        r = 5 + math.sin(apple_pulse * 1.4) * 1.8
        ctx.shadowBlur  = 24
        ctx.shadowColor = "#FFD43B"
        ctx.beginPath()
        ctx.fillStyle = "#FFD43B"
        ctx.arc(cx, cy, r, 0, math.pi * 2)
        ctx.fill()
        ctx.shadowBlur = 0
        ctx.font         = "bold 8px ui-monospace, monospace"
        ctx.textAlign    = "center"
        ctx.textBaseline = "middle"
        ctx.fillStyle    = "#0d1117"
        ctx.fillText("x3", cx, cy)
        ctx.textBaseline = "alphabetic"
    elif ptype == "slow":
        r = 5 + math.sin(apple_pulse * 0.9) * 1.4
        ctx.shadowBlur  = 20
        ctx.shadowColor = "#64b5f6"
        ctx.beginPath()
        ctx.fillStyle = "#64b5f6"
        ctx.arc(cx, cy, r, 0, math.pi * 2)
        ctx.fill()
        ctx.shadowBlur = 0
        ctx.font         = "bold 9px ui-monospace, monospace"
        ctx.textAlign    = "center"
        ctx.textBaseline = "middle"
        ctx.fillStyle    = "#0d1117"
        ctx.fillText("~", cx, cy)
        ctx.textBaseline = "alphabetic"


# ── Background ────────────────────────────────────────────────────────────────
def draw_background():
    ctx.fillStyle = "#0d1117"
    ctx.fillRect(0, 0, cv.width, cv.height)
    ctx.fillStyle = "rgba(55, 118, 171, 0.1)"
    for gx in range(1, GRID):
        for gy in range(1, GRID):
            ctx.beginPath()
            ctx.arc(gx * CELL, gy * CELL, 0.9, 0, math.pi * 2)
            ctx.fill()


# ── Segments ──────────────────────────────────────────────────────────────────
def draw_segment(x, y, color, radius=6):
    px, py = x * CELL, y * CELL
    ctx.beginPath()
    ctx.fillStyle = color
    ctx.moveTo(px + radius, py)
    ctx.lineTo(px + CELL - radius, py)
    ctx.quadraticCurveTo(px + CELL, py, px + CELL, py + radius)
    ctx.lineTo(px + CELL, py + CELL - radius)
    ctx.quadraticCurveTo(px + CELL, py + CELL, px + CELL - radius, py + CELL)
    ctx.lineTo(px + radius, py + CELL)
    ctx.quadraticCurveTo(px, py + CELL, px, py + CELL - radius)
    ctx.lineTo(px, py + radius)
    ctx.quadraticCurveTo(px, py, px + radius, py)
    ctx.fill()

def draw_head(x, y, direction, color="#FFD54F"):
    draw_segment(x, y, color, radius=8)
    delta = {"up": (0,-1), "down": (0,1), "left": (-1,0), "right": (1,0)}.get(direction, (1,0))
    cx = x * CELL + CELL / 2
    cy = y * CELL + CELL / 2
    ctx.beginPath()
    ctx.fillStyle = "black"
    ctx.arc(cx + delta[0] * 4, cy + delta[1] * 4, 2, 0, math.pi * 2)
    ctx.fill()


# ── Apple ─────────────────────────────────────────────────────────────────────
def draw_apple(x, y):
    cx = x * CELL + CELL / 2
    cy = y * CELL + CELL / 2
    r  = 4.5 + math.sin(apple_pulse) * 1.5
    ctx.shadowBlur  = 20
    ctx.shadowColor = "#ff2222"
    ctx.beginPath()
    ctx.fillStyle = "#ff4d4d"
    ctx.arc(cx, cy, r, 0, math.pi * 2)
    ctx.fill()
    ctx.shadowBlur = 0
    ctx.beginPath()
    ctx.fillStyle = "rgba(255,220,220,0.75)"
    ctx.arc(cx - r * 0.28, cy - r * 0.28, r * 0.35, 0, math.pi * 2)
    ctx.fill()


# ── Snake palettes ────────────────────────────────────────────────────────────
SNAKE_PALETTES = [
    lambda t: f"rgb({int(55+200*t)},{int(118+95*t)},{int(171-92*t)})",
    lambda t: f"rgb({int(200+55*t)},{int(80+120*t)},{int(20+40*t)})",
    lambda t: f"rgb({int(40+100*t)},{int(180+50*t)},{int(80+60*t)})",
    lambda t: f"rgb({int(160+80*t)},{int(40+80*t)},{int(180+50*t)})",
]

def snake_color(player_idx, i, length):
    t = i / max(1, length - 1)
    return SNAKE_PALETTES[player_idx % len(SNAKE_PALETTES)](t)


def render_snake(snake, direction, player_idx, dead=False, alpha=1.0, slowed=False):
    length = len(snake)
    if slowed and not dead:
        alpha *= 0.4 + 0.6 * ((math.sin(_current_ts[0] * 0.025) + 1) / 2)
    ctx.globalAlpha = alpha
    for i, (x, y) in enumerate(snake):
        if dead:
            color = "#252525"
            ctx.shadowBlur = 0
        else:
            color = snake_color(player_idx, i, length)
            ctx.shadowBlur  = 5
            ctx.shadowColor = color

        if i == length - 1:
            head_color = "#444" if dead else "#FFD54F"
            ctx.shadowBlur  = 0 if dead else 16
            ctx.shadowColor = head_color
            draw_head(x, y, direction, head_color)
            ctx.shadowBlur = 0
        else:
            draw_segment(x, y, color)
            ctx.shadowBlur = 0
    ctx.globalAlpha = 1.0


# ── Player list (left overlay) ────────────────────────────────────────────────
def draw_player_list():
    cur_mode = game_state.get("mode", "solo")

    if cur_mode == "multi":
        snakes_d = game_state.get("snakes", {})
        names_d  = game_state.get("names", {})
        alive_d  = game_state.get("alive", {})
        players  = [
            (pid, int(pid) if pid.isdigit() else 0,
             names_d.get(pid, f"P{pid}"),
             not alive_d.get(pid, True))
            for pid in sorted(snakes_d.keys())
        ]
    else:
        solo_name = document["name"].value.strip() or "Player"
        players   = [("0", 0, solo_name, False)]

    if not players:
        return

    TILE   = 9   # px per mini-tile
    GAP    = 2   # gap between tiles
    PAD_X  = 8
    PAD_Y  = 7
    ROW_H  = 22
    NAME_X = PAD_X + 3 * (TILE + GAP) + 6

    # measure longest name to size the panel
    ctx.font = "bold 11px ui-monospace, monospace"
    max_name_w = max((len(name) * 7) for _, _, name, _ in players)
    panel_w = NAME_X + max_name_w + PAD_X
    panel_h = PAD_Y * 2 + len(players) * ROW_H - (ROW_H - TILE) // 2

    # background rounded rect
    x0, y0, r = 6, 6, 6
    w, h = panel_w, panel_h
    ctx.fillStyle = "rgba(13,17,23,0.78)"
    ctx.beginPath()
    ctx.moveTo(x0 + r, y0)
    ctx.lineTo(x0 + w - r, y0)
    ctx.quadraticCurveTo(x0 + w, y0,     x0 + w, y0 + r)
    ctx.lineTo(x0 + w, y0 + h - r)
    ctx.quadraticCurveTo(x0 + w, y0 + h, x0 + w - r, y0 + h)
    ctx.lineTo(x0 + r, y0 + h)
    ctx.quadraticCurveTo(x0, y0 + h,     x0, y0 + h - r)
    ctx.lineTo(x0, y0 + r)
    ctx.quadraticCurveTo(x0, y0,         x0 + r, y0)
    ctx.fill()

    ctx.textAlign    = "left"
    ctx.textBaseline = "middle"
    ctx.font         = "bold 11px ui-monospace, monospace"

    for i, (pid, pidx, name, is_dead) in enumerate(players):
        row_y  = y0 + PAD_Y + i * ROW_H
        tile_y = row_y
        mid_y  = tile_y + TILE / 2

        ctx.globalAlpha = 0.4 if is_dead else 1.0

        # 3 mini snake tiles
        for j in range(3):
            tx = x0 + PAD_X + j * (TILE + GAP)
            color = "#555" if is_dead else snake_color(pidx, j, 3)
            ctx.fillStyle = color
            ctx.shadowBlur  = 0 if is_dead else 4
            ctx.shadowColor = color
            ctx.beginPath()
            ctx.roundRect(tx, tile_y, TILE, TILE, 2)
            ctx.fill()
            ctx.shadowBlur = 0

        # username
        ctx.fillStyle = "#888" if is_dead else "#FFD43B"
        ctx.fillText(name, x0 + NAME_X, mid_y)

    ctx.globalAlpha  = 1.0
    ctx.textBaseline = "alphabetic"
    ctx.textAlign    = "left"


# ── Overlays ──────────────────────────────────────────────────────────────────
def draw_lobby():
    ctx.fillStyle = "#0d1117"
    ctx.fillRect(0, 0, cv.width, cv.height)

    ctx.textAlign    = "center"
    ctx.textBaseline = "middle"

    # Titre
    ctx.font        = "bold 30px ui-monospace, monospace"
    ctx.shadowBlur  = 18
    ctx.shadowColor = "#3776AB"
    ctx.fillStyle   = "#3776AB"
    ctx.fillText("LOBBY", cv.width / 2, 72)
    ctx.shadowBlur  = 0

    # Code room
    room_id = game_state.get("lobby_room_id", "")
    ctx.font      = "13px ui-monospace, monospace"
    ctx.fillStyle = "rgba(139,180,220,0.45)"
    ctx.fillText(f"# room : {room_id}", cv.width / 2, 108)

    # Séparateur
    ctx.strokeStyle = "rgba(55,118,171,0.2)"
    ctx.lineWidth   = 1
    ctx.beginPath()
    ctx.moveTo(cv.width / 2 - 120, 128)
    ctx.lineTo(cv.width / 2 + 120, 128)
    ctx.stroke()

    # Liste des joueurs
    players = game_state.get("lobby_players", [])
    my_id   = game_state.get("my_player_id")
    y = 175
    for p in players:
        is_me = str(p["id"]) == str(my_id)
        ready = p["ready"]

        # Indicateur prêt
        if ready:
            ctx.fillStyle   = "#4caf50"
            ctx.shadowBlur  = 10
            ctx.shadowColor = "#4caf50"
            indicator = "✓"
        else:
            ctx.fillStyle  = "rgba(139,180,220,0.35)"
            ctx.shadowBlur = 0
            indicator = "○"
        ctx.font = "bold 20px ui-monospace, monospace"
        ctx.fillText(indicator, cv.width / 2 - 90, y)
        ctx.shadowBlur = 0

        # Nom
        name = p["name"]
        if p.get("is_bot"):
            name += " [bot]"
        suffix = "  ← vous" if is_me else ""
        ctx.font      = "15px ui-monospace, monospace"
        ctx.fillStyle = "#FFD43B" if is_me else "rgba(215,227,255,0.85)"
        ctx.shadowBlur  = 6 if is_me else 0
        ctx.shadowColor = "#FFD43B"
        ctx.fillText(name + suffix, cv.width / 2 + 30, y)
        ctx.shadowBlur = 0

        # Statut texte
        ctx.font      = "11px ui-monospace, monospace"
        ctx.fillStyle = "#4caf50" if ready else "rgba(139,180,220,0.4)"
        ctx.fillText("prêt" if ready else "en attente...", cv.width / 2 + 30, y + 18)

        y += 62

    # Hint bas
    ctx.font      = "11px ui-monospace, monospace"
    ctx.fillStyle = "rgba(139,180,220,0.3)"
    ctx.fillText("Clique sur Prêt ! quand tu es prêt à jouer", cv.width / 2, cv.height - 30)


def draw_countdown(value):
    ctx.fillStyle    = "rgba(0,0,0,0.45)"
    ctx.fillRect(0, 0, cv.width, cv.height)
    ctx.textAlign    = "center"
    ctx.textBaseline = "middle"
    ctx.font         = "bold 96px ui-monospace, monospace"
    ctx.shadowBlur   = 40
    ctx.shadowColor  = "#3776AB"
    ctx.fillStyle    = "#FFD43B"
    ctx.fillText(str(value), cv.width / 2, cv.height / 2)
    ctx.shadowBlur   = 0
    ctx.textBaseline = "alphabetic"


def draw_game_over():
    ctx.fillStyle = "rgba(0,0,0,0.70)"
    ctx.fillRect(0, 0, cv.width, cv.height)
    ctx.textAlign   = "center"
    cur_mode = game_state.get("mode", "solo")

    if cur_mode == "multi":
        my_id     = game_state.get("my_player_id", "0")
        winner_id = game_state.get("winner_id")
        i_won     = winner_id == my_id

        if i_won:
            label       = "VICTOIRE !"
            label_color = "#FFD43B"
            glow_color  = "#FFD43B"
        else:
            label       = "DÉFAITE"
            label_color = "#ff4d4d"
            glow_color  = "#ff4d4d"

        ctx.shadowBlur  = 28
        ctx.shadowColor = glow_color
        ctx.fillStyle   = label_color
        ctx.font        = "bold 48px ui-monospace, monospace"
        ctx.fillText(label, cv.width / 2, cv.height / 2 - 50)
        ctx.shadowBlur = 0

        scores  = game_state.get("scores", {})
        names   = game_state.get("names", {})
        ranking = sorted(scores.items(), key=lambda kv: -kv[1])
        medals  = ["1st", "2nd", "3rd"]
        y_pos   = cv.height / 2 + 5
        ctx.font = "16px ui-monospace, monospace"
        for rank, (pid, sc) in enumerate(ranking):
            name  = names.get(pid, f"P{pid}")
            medal = medals[rank] if rank < len(medals) else ""
            ctx.fillStyle   = "#FFD54F" if pid == my_id else "rgba(215,227,255,0.85)"
            ctx.shadowBlur  = 8 if pid == my_id else 0
            ctx.shadowColor = "#FFD54F"
            ctx.fillText(f"{medal}  {name} — {sc}", cv.width / 2, y_pos)
            ctx.shadowBlur = 0
            y_pos += 26
    else:
        ctx.shadowBlur  = 24
        ctx.shadowColor = "#ff4d4d"
        ctx.fillStyle   = "#ff4d4d"
        ctx.font        = "bold 38px ui-monospace, monospace"
        ctx.fillText("GAME OVER", cv.width / 2, cv.height / 2 - 30)
        ctx.shadowBlur = 0
        ctx.font      = "16px ui-monospace, monospace"
        ctx.fillStyle = "rgba(215,227,255,0.85)"
        ctx.fillText(f'Score : {game_state.get("score", 0)}', cv.width / 2, cv.height / 2 + 10)

    ctx.font      = "12px ui-monospace, monospace"
    ctx.fillStyle = "rgba(55,118,171,0.7)"
    ctx.fillText("[ Solo() ou Multi() pour rejouer ]", cv.width / 2, cv.height - 22)


# ── Main animation loop (60 fps) ──────────────────────────────────────────────
def animation_frame(ts):
    global apple_pulse

    dt = min((ts - _last_ts[0]) / 1000.0, 0.05)
    _last_ts[0]    = ts
    _current_ts[0] = ts
    apple_pulse   += dt * 3.5

    # ── lobby ──
    if game_state.get("lobby"):
        draw_lobby()
        window.requestAnimationFrame(animation_frame)
        return

    cur_mode = game_state.get("mode", "solo")

    # ── sons countdown / game over ──
    cd = game_state.get("countdown", 0)
    if cd != _prev_countdown[0]:
        if cd > 0:
            play_beep(440, 0.12)
        elif _prev_countdown[0] > 0:
            play_beep(880, 0.25)
    _prev_countdown[0] = cd

    go = game_state.get("game_over", False)
    if go and not _prev_game_over[0]:
        play_beep(150, 0.45, shape="sawtooth")
    _prev_game_over[0] = go

    # ── détection pomme mangée → particules + popup + son ──
    if cur_mode == "solo":
        cur_score = game_state.get("score", 0)
        if cur_score > _prev_score[0]:
            snake = game_state.get("snake", [])
            if snake:
                hx, hy = snake[-1]
                cx, cy = hx * CELL + CELL/2, hy * CELL + CELL/2
                spawn_particles(cx, cy, "#ff4d4d", 12)
                spawn_score_popup(cx, cy - CELL)
                _flash_score()
            play_beep(880, 0.07)
        _prev_score[0] = cur_score
    else:
        cur_scores = dict(game_state.get("scores", {}))
        snakes_d   = game_state.get("snakes", {})
        my_id      = game_state.get("my_player_id")

        for pid, sc in cur_scores.items():
            prev_sc = _prev_scores[0].get(pid, 0)
            if sc > prev_sc:
                snake = snakes_d.get(pid, [])
                if snake:
                    hx, hy = snake[-1]
                    cx, cy = hx * CELL + CELL/2, hy * CELL + CELL/2
                    pidx = int(pid) if pid.isdigit() else 0
                    col  = SNAKE_PALETTES[pidx % len(SNAKE_PALETTES)](0.7)
                    spawn_particles(cx, cy, col, 12)
                    spawn_score_popup(cx, cy - CELL)
                    _flash_score()
                if pid == my_id:
                    # distinguer pomme normale (+1) et or (+3)
                    if sc - prev_sc >= 3:
                        play_beep(1100, 0.18, shape="triangle")
                    else:
                        play_beep(880, 0.07)
        _prev_scores[0] = cur_scores

        # son quand je me fais ralentir
        slow_d   = game_state.get("slow_ticks", {})
        prev_slow = _prev_slow_ticks[0]
        if my_id and slow_d.get(my_id, 0) > prev_slow.get(my_id, 0):
            play_beep(220, 0.35, shape="square")
        _prev_slow_ticks[0] = dict(slow_d)

        # enregistrer timestamps de mort
        alive_d = game_state.get("alive", {})
        for pid, alive in alive_d.items():
            if not alive and pid not in _death_ts:
                _death_ts[pid] = ts

    # ── interpolation : détecter les ticks et calculer t ──
    if cur_mode == "solo":
        snake_now = game_state.get("snake", [])
        head_now  = snake_now[-1] if snake_now else None
        head_old  = _it_solo_curr[0][-1] if _it_solo_curr[0] else None
        if head_now != head_old:
            _it_solo_prev[0] = _it_solo_curr[0] or list(snake_now)
            _it_solo_curr[0] = list(snake_now)
            if _it_solo_ts[0] > 0:
                iv = ts - _it_solo_ts[0]
                if 40 < iv < 600:
                    # moyenne mobile exponentielle pour lisser l'estimation
                    _it_solo_iv[0] = _it_solo_iv[0] * 0.6 + iv * 0.4
            _it_solo_ts[0] = ts
        elapsed_solo = ts - _it_solo_ts[0]
        iv_solo      = max(1, _it_solo_iv[0])
        t_solo       = min(1.0, elapsed_solo / iv_solo)
        solo_from    = _it_solo_prev[0] or snake_now
        solo_to      = _it_solo_curr[0] or snake_now
    else:
        snakes_now = game_state.get("snakes", {})
        heads_now  = {pid: tuple(s[-1]) if s else None for pid, s in snakes_now.items()}
        heads_old  = {pid: (s[-1] if s else None) for pid, s in _it_multi_curr[0].items()}
        if heads_now != heads_old:
            _it_multi_prev[0] = {pid: list(s) for pid, s in _it_multi_curr[0].items()}
            _it_multi_curr[0] = {pid: list(s) for pid, s in snakes_now.items()}
            if _it_multi_ts[0] > 0:
                iv = ts - _it_multi_ts[0]
                if 40 < iv < 400:
                    _it_multi_iv[0] = _it_multi_iv[0] * 0.6 + iv * 0.4
            _it_multi_ts[0] = ts
        elapsed_multi = ts - _it_multi_ts[0]
        iv_multi      = max(1, _it_multi_iv[0])

    # ── draw ──
    draw_background()

    if cur_mode == "multi":
        for apple in game_state.get("apples", []):
            draw_apple(*apple)
        for pu in game_state.get("powerups", []):
            draw_powerup(pu["pos"][0], pu["pos"][1], pu["type"])

        snakes_d     = game_state.get("snakes", {})
        directions_d = game_state.get("directions", {})
        alive_d      = game_state.get("alive", {})
        slow_d       = game_state.get("slow_ticks", {})
        my_id        = game_state.get("my_player_id")
        ordered      = sorted(snakes_d.keys(), key=lambda pid: (pid == my_id))

        for pid in ordered:
            sn = snakes_d.get(pid, [])
            if not sn:
                continue
            pidx      = int(pid) if pid.isdigit() else 0
            is_dead   = not alive_d.get(pid, True)
            is_slowed = slow_d.get(pid, 0) > 0

            alpha = 1.0
            if is_dead and pid in _death_ts:
                elapsed = (ts - _death_ts[pid]) / 1000.0
                alpha   = max(0.0, 1.0 - elapsed / 1.5)

            curr_s  = _it_multi_curr[0].get(pid, [tuple(c) for c in sn])
            prev_s  = _it_multi_prev[0].get(pid, curr_s)
            t_m     = min(1.0, elapsed_multi / iv_multi)
            sn_draw = _lerp_snake(prev_s, curr_s, t_m)

            render_snake(
                sn_draw,
                directions_d.get(pid, "right"),
                pidx,
                dead=is_dead,
                alpha=alpha,
                slowed=is_slowed,
            )
    else:
        apple = game_state.get("apple")
        if apple:
            draw_apple(*apple)
        snake = game_state.get("snake", [])
        if snake:
            sn_draw = _lerp_snake(solo_from, solo_to, t_solo)
            render_snake(sn_draw, game_state.get("direction", "right"), 0)

    draw_player_list()
    update_and_draw_particles(dt)
    draw_score_popups(dt)

    cd = game_state.get("countdown", 0)
    if cd > 0:
        draw_countdown(cd)

    if game_state.get("game_over"):
        draw_game_over()

    window.requestAnimationFrame(animation_frame)


def _flash_score():
    score_el.classList.add("score-flash")
    window.setTimeout(lambda: score_el.classList.remove("score-flash"), 350)


def render():
    pass  # rAF gère tout


# ── Parser ────────────────────────────────────────────────────────────────────
front_parser = WSFrontParser(
    game_state=game_state,
    render=render,
    score_el=score_el,
    status_el=status_el,
)


def game_stop():
    global ws

    game_state["game_over"] = True
    duration_ms  = int(window.performance.now() - t0)
    name         = document["name"].value.strip() or "Player"
    cur_mode     = game_state.get("mode", "solo")

    if ws is not None:
        ws.close()
        ws = None

    if cur_mode == "solo":
        final_score = game_state["score"]

        async def run():
            try:
                await submit_score(name, final_score, duration_ms)
                await load_leaderboard()
            except Exception as e:
                print("Erreur submit_score:", e)

        aio.run(run())
    else:
        aio.run(load_leaderboard())


def on_lobby_update(msg):
    players = msg.get("players", [])
    my_id   = game_state.get("my_player_id")
    my_info = next((p for p in players if str(p["id"]) == str(my_id)), None)
    btn = document["ready-btn"]
    if my_info and not my_info["ready"]:
        btn.style.display = "block"
        if "disabled" in btn.attrs:
            del btn.attrs["disabled"]
        btn.style.opacity = "1"
        btn.text = "Prêt !"
    elif my_info and my_info["ready"]:
        btn.style.display = "block"
        btn.attrs["disabled"] = True
        btn.style.opacity = "0.4"
        btn.text = "✓ Prêt !"

def game_started():
    game_state["lobby"] = False
    document["ready-btn"].style.display = "none"

front_parser.on_game_over  = game_stop
front_parser.on_game_start = game_started
front_parser.on_lobby_update = on_lobby_update


def game_reset_local_view():
    game_state["snake"]        = [(5, 5), (6, 5), (7, 5)]
    game_state["apple"]        = (10, 10)
    game_state["score"]        = 0
    game_state["direction"]    = "right"
    game_state["running"]      = False
    game_state["game_over"]    = False
    game_state["countdown"]    = 0
    game_state["snakes"]       = {}
    game_state["apples"]       = []
    game_state["scores"]       = {}
    game_state["alive"]        = {}
    game_state["my_player_id"] = None
    game_state["winner_id"]    = None
    game_state["powerups"]     = []
    game_state["slow_ticks"]   = {}
    _prev_score[0]      = 0
    _prev_countdown[0]  = 0
    _prev_game_over[0]  = False
    _prev_slow_ticks[0] = {}
    _it_solo_prev[0]    = None
    _it_solo_curr[0]    = None
    _it_solo_ts[0]      = 0.0
    _it_multi_prev[0]   = {}
    _it_multi_curr[0]   = {}
    _it_multi_ts[0]     = 0.0
    _prev_scores[0] = {}
    _death_ts.clear()
    game_state["lobby"]         = False
    game_state["lobby_players"] = []
    game_state["lobby_room_id"] = ""
    particles.clear()
    score_popups.clear()
    score_el.text = "0"
    document["ready-btn"].style.display = "none"
    if status_el:
        status_el.text = ""


# ── Input clavier ─────────────────────────────────────────────────────────────
def send_direction(direction):
    if ws is not None:
        ws.send(json.dumps({"type": "input", "direction": direction}))

def on_key(ev):
    key_map = {
        "ArrowUp": "up", "ArrowDown": "down",
        "ArrowLeft": "left", "ArrowRight": "right",
    }
    direction = key_map.get(ev.key)
    if direction:
        send_direction(direction)

document.bind("keydown", on_key)


# ── Swipe mobile ──────────────────────────────────────────────────────────────
_touch_start = [0, 0]

def on_touch_start(ev):
    ev.preventDefault()
    _touch_start[0] = ev.touches[0].clientX
    _touch_start[1] = ev.touches[0].clientY

def on_touch_end(ev):
    ev.preventDefault()
    dx = ev.changedTouches[0].clientX - _touch_start[0]
    dy = ev.changedTouches[0].clientY - _touch_start[1]
    if abs(dx) < 15 and abs(dy) < 15:
        return
    if abs(dx) > abs(dy):
        send_direction("right" if dx > 0 else "left")
    else:
        send_direction("down" if dy > 0 else "up")

cv.bind("touchstart", on_touch_start)
cv.bind("touchend",   on_touch_end)


# ── D-pad mobile ──────────────────────────────────────────────────────────────
for _btn in document.select("[data-dir]"):
    _dir = _btn.attrs["data-dir"]
    _btn.bind("click", lambda ev, d=_dir: send_direction(d))


# ── Authentification locale ───────────────────────────────────────────────────
auth_signup = [False]


def show_auth_message(message, error=False):
    el = document["auth-message"]
    el.text = message
    el.style.color = "#ff7777" if error else "#81c784"


def set_authenticated(username, token):
    global auth_token, auth_username
    auth_token = token
    auth_username = username
    window.localStorage.setItem("snake_token", token)
    window.localStorage.setItem("snake_username", username)
    document["name"].value = username
    document["auth-out"].style.display = "none"
    document["auth-in"].style.display = "block"
    document["auth-display-name"].text = username


def clear_authenticated(ev=None):
    global auth_token, auth_username
    auth_token = None
    auth_username = None
    window.localStorage.removeItem("snake_token")
    window.localStorage.removeItem("snake_username")
    document["auth-out"].style.display = "block"
    document["auth-in"].style.display = "none"
    document["name"].value = "Player"


async def submit_auth(ev=None):
    username = document["auth-username"].value.strip()
    password = document["auth-password"].value
    if not username or not password:
        show_auth_message("pseudo et mot de passe requis", True)
        return
    endpoint = "/api/signup" if auth_signup[0] else "/api/login"
    try:
        response = await window.fetch(endpoint, {
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"username": username, "password": password}),
        })
        response_text = await response.text()
        try:
            data = json.loads(response_text)
        except Exception:
            data = {}
        if not response.ok:
            show_auth_message(data.get("detail", "authentification impossible"), True)
            return
        if auth_signup[0]:
            show_auth_message("compte cree, connexion...", False)
            login_response = await window.fetch("/api/login", {
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"username": username, "password": password}),
            })
            login_text = await login_response.text()
            try:
                data = json.loads(login_text)
            except Exception:
                data = {}
            if not login_response.ok:
                show_auth_message("compte cree, connecte-toi", False)
                return
        set_authenticated(data["username"], data["token"])
    except Exception as error:
        print("Erreur auth:", error)
        show_auth_message("API indisponible", True)


def select_auth_tab(signup):
    auth_signup[0] = signup
    document["auth-login-tab"].classList.toggle("auth-tab-on", not signup)
    document["auth-signup-tab"].classList.toggle("auth-tab-on", signup)
    document["auth-submit-btn"].text = "creer le compte" if signup else "se connecter"
    show_auth_message("")


document["auth-login-tab"].bind("click", lambda ev: select_auth_tab(False))
document["auth-signup-tab"].bind("click", lambda ev: select_auth_tab(True))
document["auth-submit-btn"].bind("click", lambda ev: aio.run(submit_auth()))
document["auth-logout-btn"].bind("click", clear_authenticated)
document["auth-password"].bind("keydown", lambda ev: aio.run(submit_auth()) if ev.key == "Enter" else None)

if auth_token and auth_username:
    set_authenticated(auth_username, auth_token)


# ── Connexion au jeu ──────────────────────────────────────────────────────────
def validate_name():
    return bool(auth_token and auth_username)


def connect():
    global ws, t0
    if ws is not None:
        return

    # sauvegarder le pseudo
    name = document["name"].value.strip()
    window.localStorage.setItem("snake_pseudo", name)

    t0 = window.performance.now()
    game_reset_local_view()

    proto  = "wss" if window.location.protocol == "https:" else "ws"
    ws_url = f"{proto}://{window.location.host}/ws"

    ws = window.WebSocket.new(ws_url)
    ws.bind("open",    on_ws_open)
    ws.bind("message", front_parser.handle_message)
    ws.bind("close",   on_ws_close)
    ws.bind("error",   on_ws_error)


def set_mode_and_connect(new_mode):
    global mode
    if not validate_name():
        show_auth_message("connecte-toi pour jouer", True)
        return
    mode = new_mode
    game_state["mode"] = new_mode
    connect()


def game_start(ev):
    if ws is None and validate_name():
        connect()
    elif not validate_name():
        show_auth_message("connecte-toi pour jouer", True)


def send_ready(ev):
    if ws is not None:
        ws.send(json.dumps({"type": "ready"}))
    document["ready-btn"].attrs["disabled"] = True
    document["ready-btn"].style.opacity = "0.4"
    document["ready-btn"].text = "✓ Prêt !"

document["start"].bind("click", game_start)
document["solo"].bind("click", lambda ev: set_mode_and_connect("solo"))
document["ws"].bind("click",   lambda ev: set_mode_and_connect("multi"))
document["ready-btn"].bind("click", send_ready)


def on_ws_open(e):
    room_code = document["room-code"].value.strip().upper()
    ws.send(json.dumps({
        "type": "join",
        "name": document["name"].value.strip() or "Player",
        "mode": mode,
        "room_code": room_code,
    }))

def on_ws_close(e):
    global ws
    ws = None

def on_ws_error(e):
    print("WebSocket error:", e)


# ── Init ──────────────────────────────────────────────────────────────────────
# ── Onglets leaderboard ───────────────────────────────────────────────────────
def switch_lb(period):
    _lb_period[0] = period
    document["lb-btn-all"].classList.toggle("lb-tab-active", period == "all")
    document["lb-btn-month"].classList.toggle("lb-tab-active", period == "monthly")
    aio.run(load_leaderboard(period))

document["lb-btn-all"].bind("click",   lambda ev: switch_lb("all"))
document["lb-btn-month"].bind("click", lambda ev: switch_lb("monthly"))

window.setInterval(lambda: aio.run(load_leaderboard()), 10000)
window.requestAnimationFrame(animation_frame)
aio.run(load_leaderboard())
