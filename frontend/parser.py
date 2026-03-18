from browser import document
import json


class WSFrontParser:
    def __init__(self, game_state, render, score_el, status_el=None, on_game_over=None, on_game_start=None, on_lobby_update=None):
        self.game_state = game_state
        self.render = render
        self.score_el = score_el
        self.status_el = status_el
        self.on_game_over = on_game_over
        self.on_game_start = on_game_start
        self.on_lobby_update = on_lobby_update

    def handle_message(self, e):
        msg = json.loads(e.data)
        msg_type = msg.get("type")

        if msg_type == "joined":
            self.handle_joined(msg)
        elif msg_type == "waiting":
            self.handle_waiting(msg)
        elif msg_type == "lobby_update":
            self.handle_lobby_update(msg)
        elif msg_type == "bot_joining":
            self.handle_bot_joining(msg)
        elif msg_type == "game_start":
            self.handle_game_start(msg)
        elif msg_type == "state":
            self.handle_state(msg)
        elif msg_type == "player_left":
            self.handle_player_left(msg)
        elif msg_type == "countdown":
            self.handle_countdown(msg)
        elif msg_type == "error":
            if self.status_el:
                self.status_el.text = msg.get("message", "Erreur serveur")
        else:
            print("Unknown server message:", msg)

    def handle_joined(self, msg):
        if self.status_el:
            self.status_el.text = f'Connected as {msg["name"]}'

    def handle_waiting(self, msg):
        # Stocker le player_id personnel dès sa réception
        self.game_state["my_player_id"] = msg.get("player_id")
        if self.status_el:
            room_id   = msg.get("room_id", "")
            bot_delay = msg.get("bot_delay")
            if bot_delay is not None:
                self.status_el.text = f'Salle {room_id} — en attente...'
            else:
                self.status_el.text = f'Salle privée {room_id} — partagez ce code !'

    def handle_lobby_update(self, msg):
        self.game_state["lobby"] = True
        self.game_state["lobby_players"] = msg.get("players", [])
        self.game_state["lobby_room_id"] = msg.get("room_id", "")
        if self.on_lobby_update:
            self.on_lobby_update(msg)

    def handle_bot_joining(self, msg):
        if self.status_el:
            self.status_el.text = msg.get("message", "Un bot vous rejoint...")

    def handle_game_start(self, msg):
        self.game_state["my_player_id"] = msg["player_id"]
        self.game_state["names"] = msg["names"]
        self.game_state["lobby"] = False
        if self.status_el:
            opponents = [n for pid, n in msg["names"].items() if pid != msg["player_id"]]
            self.status_el.text = f'VS {", ".join(opponents)} — GO!'
        if self.on_game_start:
            self.on_game_start()

    def handle_state(self, msg):
        mode = msg.get("mode", "solo")
        self.game_state["mode"] = mode

        if mode == "multi":
            was_running = self.game_state.get("running", True)
            self.game_state["snakes"] = {pid: [tuple(cell) for cell in snake] for pid, snake in msg["snakes"].items()}
            self.game_state["apples"] = [tuple(a) for a in msg["apples"]]
            self.game_state["scores"] = msg["scores"]
            self.game_state["directions"] = msg["directions"]
            self.game_state["alive"] = msg["alive"]
            self.game_state["running"] = msg["running"]
            self.game_state["winner_id"] = msg.get("winner_id")
            self.game_state["powerups"] = msg.get("powerups", [])
            self.game_state["slow_ticks"] = msg.get("slow_ticks", {})
            self.score_el.text = str(self.game_state["scores"].get(self.game_state.get("my_player_id", "0"), 0))
            self.render()
            if was_running and not msg["running"] and self.on_game_over:
                self.on_game_over()
        else:
            was_running = self.game_state.get("running", True)
            self.game_state["snake"] = [tuple(part) for part in msg["snake"]]
            self.game_state["apple"] = tuple(msg["apple"])
            self.game_state["score"] = msg["score"]
            self.game_state["direction"] = msg["direction"]
            self.game_state["running"] = msg["running"]
            self.score_el.text = str(self.game_state["score"])
            self.render()
            if was_running and not msg["running"] and self.on_game_over:
                self.on_game_over()

    def handle_countdown(self, msg):
        self.game_state["countdown"] = msg.get("value", 0)

    def handle_player_left(self, msg):
        if self.status_el:
            self.status_el.text = "Opponent left the game"
        self.game_state["running"] = False
        if self.on_game_over:
            self.on_game_over()
