import asyncio
import json
import random
import time

from score import save_score


GRID = 30
N_APPLES = 20
N_POWERUPS = 2
POWERUP_TYPES = ["gold", "slow"]

STARTS = [
    {"pos": [[3, 7], [4, 7], [5, 7]],       "dir": "right"},
    {"pos": [[26, 22], [25, 22], [24, 22]], "dir": "left"},
    {"pos": [[15, 3], [15, 4], [15, 5]],   "dir": "down"},
    {"pos": [[15, 26], [15, 25], [15, 24]], "dir": "up"},
]

DELTAS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}


# ── Bot AI (greedy + flood-fill) ──────────────────────────────────────────────

class BotAI:
    def __init__(self, player_id):
        self.player_id = player_id

    def _all_cells(self, gs):
        return set(tuple(c) for snake in gs.snakes.values() for c in snake if snake)

    def _is_safe(self, pos, all_cells):
        x, y = pos
        return 0 <= x < GRID and 0 <= y < GRID and tuple(pos) not in all_cells

    def _flood_fill(self, start, all_cells):
        """Nombre de cases atteignables depuis start (BFS)."""
        visited = set()
        queue = [tuple(start)]
        while queue:
            cur = queue.pop()
            if cur in visited:
                continue
            x, y = cur
            if not (0 <= x < GRID and 0 <= y < GRID):
                continue
            if cur in all_cells:
                continue
            visited.add(cur)
            for dx, dy in DELTAS.values():
                queue.append((x + dx, y + dy))
        return len(visited)

    def compute_direction(self, gs):
        pid = self.player_id
        if not gs.alive.get(pid) or not gs.snakes.get(pid):
            return None

        head = gs.snakes[pid][-1]
        current_dir = gs.directions[pid]
        candidates = [d for d in DELTAS if d != OPPOSITE[current_dir]]

        all_cells = self._all_cells(gs)

        def next_pos(d):
            dx, dy = DELTAS[d]
            return [head[0] + dx, head[1] + dy]

        safe = [d for d in candidates if self._is_safe(next_pos(d), all_cells)]
        if not safe:
            return current_dir

        # 8% de hasard pour être moins prévisible
        if random.random() < 0.08:
            return random.choice(safe)

        if not gs.apples:
            return max(safe, key=lambda d: self._flood_fill(next_pos(d), all_cells))

        nearest = min(gs.apples, key=lambda a: abs(a[0] - head[0]) + abs(a[1] - head[1]))

        def score(d):
            np_ = next_pos(d)
            dist = abs(np_[0] - nearest[0]) + abs(np_[1] - nearest[1])
            space = self._flood_fill(np_, all_cells)
            # priorité : distance à la pomme, puis espace libre
            return (dist, -space)

        return min(safe, key=score)


# ── Multi game state ──────────────────────────────────────────────────────────

class MultiGameState:
    def __init__(self, player_ids):
        self.player_ids = player_ids
        self.snakes = {}
        self.directions = {}
        self.scores = {}
        self.alive = {}
        self.apples = []
        self.powerups = []
        self.slow_ticks = {}
        self.running = False
        self.winner_id = None
        self._init()

    def _init(self):
        for i, pid in enumerate(self.player_ids):
            start = STARTS[i % len(STARTS)]
            self.snakes[pid] = [list(p) for p in start["pos"]]
            self.directions[pid] = start["dir"]
            self.scores[pid] = 0
            self.alive[pid] = True
        self.apples = []
        self.powerups = []
        self.slow_ticks = {pid: 0 for pid in self.player_ids}
        self._fill_apples()
        self._fill_powerups()

    def reset(self):
        self._init()
        self.running = False
        self.winner_id = None
        self.ready = set()

    def set_direction(self, player_id, direction):
        if not self.alive.get(player_id):
            return
        if direction != OPPOSITE.get(self.directions[player_id]):
            self.directions[player_id] = direction

    def tick(self):
        if not self.running:
            return

        for pid in self.player_ids:
            if not self.alive[pid]:
                continue

            # slow effect: freeze this player for one tick
            if self.slow_ticks.get(pid, 0) > 0:
                self.slow_ticks[pid] -= 1
                continue

            snake = self.snakes[pid]
            dx, dy = DELTAS[self.directions[pid]]
            new_head = [snake[-1][0] + dx, snake[-1][1] + dy]

            if not (0 <= new_head[0] < GRID and 0 <= new_head[1] < GRID):
                self._kill(pid)
                continue
            if new_head in snake:
                self._kill(pid)
                continue
            if any(new_head in self.snakes[o] for o in self.player_ids if o != pid):
                self._kill(pid)
                continue

            snake.append(new_head)
            eaten_apple = next((a for a in self.apples if a == new_head), None)
            eaten_pu    = next((p for p in self.powerups if p["pos"] == new_head), None)

            if eaten_apple:
                self.apples.remove(eaten_apple)
                self.scores[pid] += 1
                self._fill_apples()
            elif eaten_pu:
                self.powerups.remove(eaten_pu)
                if eaten_pu["type"] == "gold":
                    self.scores[pid] += 3
                    # grow 2 extra segments
                    for _ in range(2):
                        snake.insert(0, list(snake[0]))
                elif eaten_pu["type"] == "slow":
                    for other in self.player_ids:
                        if other != pid and self.alive.get(other):
                            self.slow_ticks[other] = self.slow_ticks.get(other, 0) + 10
                self._fill_powerups()
            else:
                snake.pop(0)

        if not any(self.alive.values()):
            self.running = False
            self.winner_id = max(self.scores, key=lambda pid: self.scores[pid]) if self.scores else None

    def _kill(self, pid):
        self.alive[pid] = False
        for cell in self.snakes[pid]:
            if cell not in self.apples:
                self.apples.append(list(cell))
        self.snakes[pid] = []

    def _fill_powerups(self):
        occupied = self._occupied()
        for pu in self.powerups:
            if pu["pos"] not in occupied:
                occupied.append(pu["pos"])
        while len(self.powerups) < N_POWERUPS:
            candidate = [random.randint(0, GRID - 1), random.randint(0, GRID - 1)]
            if candidate not in occupied:
                self.powerups.append({"pos": candidate, "type": random.choice(POWERUP_TYPES)})
                occupied.append(candidate)

    def _occupied(self):
        cells = [cell for snake in self.snakes.values() for cell in snake]
        cells.extend(self.apples)
        return cells

    def _fill_apples(self):
        occupied = self._occupied()
        while len(self.apples) < N_APPLES:
            candidate = [random.randint(0, GRID - 1), random.randint(0, GRID - 1)]
            if candidate not in occupied:
                self.apples.append(candidate)
                occupied.append(candidate)

    def to_dict(self):
        return {
            "type": "state",
            "mode": "multi",
            "snakes": self.snakes,
            "apples": self.apples,
            "scores": self.scores,
            "directions": self.directions,
            "alive": self.alive,
            "running": self.running,
            "winner_id": self.winner_id,
            "powerups": self.powerups,
            "slow_ticks": self.slow_ticks,
        }


# ── Room ──────────────────────────────────────────────────────────────────────

class Room:
    def __init__(self, room_id, max_players=2):
        self.room_id = room_id
        self.max_players = max_players
        self.players = []
        self.game_state = None
        self._bots = []
        self._game_task = None
        self._start_time = None
        self.ready = set()

    @property
    def is_full(self):
        return len(self.players) >= self.max_players

    @property
    def is_empty(self):
        return len(self.players) == 0

    def human_count(self):
        return sum(1 for p in self.players if not p["is_bot"])

    def add_player(self, ws, name):
        player_id = str(len(self.players))
        self.players.append({"ws": ws, "name": name, "player_id": player_id, "is_bot": False})
        return player_id

    def add_bot(self, name=None):
        player_id = str(len(self.players))
        if name is None:
            name = f"Bot {player_id}"
        self.players.append({"ws": None, "name": name, "player_id": player_id, "is_bot": True})
        self._bots.append(BotAI(player_id))
        self.ready.add(player_id)  # bots toujours prêts
        return player_id

    def set_ready(self, player_id):
        self.ready.add(player_id)

    @property
    def all_human_ready(self):
        human_ids = {p["player_id"] for p in self.players if not p["is_bot"]}
        return bool(human_ids) and human_ids.issubset(self.ready)

    def lobby_dict(self):
        return {
            "type": "lobby_update",
            "room_id": self.room_id,
            "players": [
                {
                    "id": p["player_id"],
                    "name": p["name"],
                    "ready": p["player_id"] in self.ready,
                    "is_bot": p["is_bot"],
                }
                for p in self.players
            ],
        }

    def find_player(self, ws):
        return next((p for p in self.players if p["ws"] == ws), None)

    async def remove_player(self, ws):
        player = self.find_player(ws)
        if player:
            self.ready.discard(player["player_id"])
        self.players = [p for p in self.players if p["ws"] != ws]
        if self.game_state and self.game_state.running:
            self.game_state.running = False
            if self._game_task:
                self._game_task.cancel()
            await self.broadcast({
                "type": "player_left",
                "player_id": player["player_id"] if player else None,
            })
        elif self.players:
            await self.broadcast(self.lobby_dict())

    async def broadcast(self, msg):
        data = json.dumps(msg)
        for p in list(self.players):
            if p["ws"] is None:
                continue
            try:
                await p["ws"].send_text(data)
            except Exception:
                pass

    async def send_to(self, ws, msg):
        await ws.send_text(json.dumps(msg))

    async def start_game(self):
        player_ids = [p["player_id"] for p in self.players]
        self.game_state = MultiGameState(player_ids)

        existing_bot_ids = {b.player_id for b in self._bots}
        for p in self.players:
            if p["is_bot"] and p["player_id"] not in existing_bot_ids:
                self._bots.append(BotAI(p["player_id"]))

        names = {p["player_id"]: p["name"] for p in self.players}
        for p in self.players:
            if p["ws"] is None:
                continue
            await self.send_to(p["ws"], {
                "type": "game_start",
                "player_id": p["player_id"],
                "names": names,
                "room_id": self.room_id,
            })

        await self.broadcast(self.game_state.to_dict())

        for i in range(5, 0, -1):
            await self.broadcast({"type": "countdown", "value": i})
            await asyncio.sleep(1)

        # abort si plus aucun humain
        if self.human_count() == 0:
            return

        await self.broadcast({"type": "countdown", "value": 0})
        self.game_state.running = True
        self._start_time = time.time()
        self._game_task = asyncio.create_task(self._game_loop())

    async def _game_loop(self):
        while self.game_state.running:
            await asyncio.sleep(0.15)
            for bot in self._bots:
                direction = bot.compute_direction(self.game_state)
                if direction:
                    self.game_state.set_direction(bot.player_id, direction)
            self.game_state.tick()
            await self.broadcast(self.game_state.to_dict())

        await self._on_game_over()

    async def _on_game_over(self):
        duration_ms = int((time.time() - self._start_time) * 1000)
        for p in self.players:
            if p["is_bot"]:
                continue
            pid = p["player_id"]
            score = self.game_state.scores.get(pid, 0)
            await save_score(p["name"], score, duration_ms)
