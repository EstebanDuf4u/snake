import asyncio
import json
import time
from GameState import GameState
from rooms.room_manager import room_manager

INPUT_RATE_LIMIT = 0.05  # secondes minimum entre deux inputs


class WSParser:
    def __init__(self):
        self.game_state = GameState()
        self.player_name = None
        self.mode = None
        self.room = None
        self.player_id = None
        self._solo_task = None
        self._last_input = 0.0

    async def parse(self, websocket, msg):
        msg_type = msg.get("type")
        if msg_type == "join":
            await self.handle_join(websocket, msg)
        elif msg_type == "input":
            await self.handle_input(websocket, msg)
        elif msg_type == "ready":
            await self.handle_ready(websocket, msg)
        else:
            print("Unknown message:", msg)

    async def handle_ready(self, websocket, msg):
        if self.mode == "multi":
            await room_manager.player_ready(websocket)

    async def handle_join(self, websocket, msg):
        self.player_name = msg.get("name", "Player")
        self.mode = msg.get("mode", "solo")

        if self.mode == "multi":
            room_code = msg.get("room_code", "").strip().upper() or None
            self.room, self.player_id = await room_manager.join(websocket, self.player_name, room_code)
        else:
            await self._start_solo(websocket)

    async def _start_solo(self, websocket):
        # annuler proprement la tâche précédente
        if self._solo_task and not self._solo_task.done():
            self._solo_task.cancel()
            try:
                await self._solo_task
            except asyncio.CancelledError:
                pass

        self.game_state.reset()

        await websocket.send_text(json.dumps({
            "type": "joined",
            "name": self.player_name,
            "mode": "solo",
            "status": "ok",
        }))

        state = self.game_state.to_dict()
        state["mode"] = "solo"
        await websocket.send_text(json.dumps(state))

        # toute la logique (countdown + boucle) dans une seule tâche annulable
        self._solo_task = asyncio.create_task(self._solo_run(websocket))

    async def _solo_run(self, websocket):
        try:
            for i in range(5, 0, -1):
                await websocket.send_text(json.dumps({"type": "countdown", "value": i}))
                await asyncio.sleep(1)
            await websocket.send_text(json.dumps({"type": "countdown", "value": 0}))
            self.game_state.running = True
            await self._solo_loop(websocket)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print("Solo run error:", e)

    async def _solo_loop(self, websocket):
        while self.game_state.running:
            score = self.game_state.score
            # vitesse progressive : 0.22s → 0.09s selon le score
            interval = max(0.09, 0.22 - score * 0.007)
            await asyncio.sleep(interval)
            self.game_state.tick()
            state = self.game_state.to_dict()
            state["mode"] = "solo"
            state["interval"] = round(interval, 3)
            await websocket.send_text(json.dumps(state))

    async def handle_input(self, websocket, msg):
        now = time.monotonic()
        if now - self._last_input < INPUT_RATE_LIMIT:
            return
        self._last_input = now

        direction = msg.get("direction")
        if direction not in {"up", "down", "left", "right"}:
            return

        if self.mode == "multi" and self.room and self.room.game_state:
            self.room.game_state.set_direction(self.player_id, direction)
        elif self.mode == "solo":
            self.game_state.direction_from_input(direction)

    async def on_disconnect(self, websocket):
        if self._solo_task and not self._solo_task.done():
            self._solo_task.cancel()
            try:
                await self._solo_task
            except asyncio.CancelledError:
                pass
        if self.mode == "multi":
            await room_manager.leave(websocket)
