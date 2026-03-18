import asyncio
import json
import uuid
from rooms.rooms import Room

BOT_FILL_DELAY = 20  # secondes avant qu'un bot rejoigne si la room est incomplète


class RoomManager:
    def __init__(self):
        self.rooms = {}
        self._waiting_room = None

    def _new_room(self):
        room_id = str(uuid.uuid4())[:8]
        room = Room(room_id, max_players=4)
        self.rooms[room_id] = room
        return room

    async def join(self, ws, name, room_code=None):
        if room_code:
            room = self._join_by_code(ws, room_code)
            if room is None:
                await ws.send_text(json.dumps({
                    "type": "error",
                    "message": f"La salle « {room_code} » est pleine ou invalide.",
                }))
                return None, None
        else:
            if self._waiting_room is None or self._waiting_room.is_full:
                self._waiting_room = self._new_room()
            room = self._waiting_room

        player_id = room.add_player(ws, name)

        # Infos perso au nouveau joueur en premier (pour qu'il connaisse son player_id)
        await room.send_to(ws, {
            "type": "waiting",
            "room_id": room.room_id,
            "player_id": player_id,
            "bot_delay": BOT_FILL_DELAY if not room_code else None,
        })

        # Lobby state à tous
        await room.broadcast(room.lobby_dict())

        if not room_code:
            asyncio.create_task(self._fill_with_bots(room))

        return room, player_id

    def _join_by_code(self, ws, code):
        room = self.rooms.get(code)
        if room is None:
            room = Room(code, max_players=4)
            self.rooms[code] = room
        elif room.is_full:
            return None
        return room

    async def player_ready(self, ws):
        room, player_id = self.find_room(ws)
        if not room or not player_id:
            return
        room.set_ready(player_id)
        await room.broadcast(room.lobby_dict())
        if room.all_human_ready:
            if self._waiting_room and self._waiting_room.room_id == room.room_id:
                self._waiting_room = None
            await room.start_game()

    async def _fill_with_bots(self, room):
        await asyncio.sleep(BOT_FILL_DELAY)

        if room.room_id not in self.rooms or room.is_empty:
            return
        if room.game_state and room.game_state.running:
            return

        await room.broadcast({
            "type": "bot_joining",
            "message": "Aucun adversaire trouvé — un bot va vous rejoindre.",
        })

        while not room.is_full:
            room.add_bot()

        if self._waiting_room and self._waiting_room.room_id == room.room_id:
            self._waiting_room = None

        await room.broadcast(room.lobby_dict())

        if room.all_human_ready:
            await room.start_game()

    async def leave(self, ws):
        for room in list(self.rooms.values()):
            if room.find_player(ws):
                await room.remove_player(ws)
                if room.is_empty:
                    del self.rooms[room.room_id]
                    if self._waiting_room and self._waiting_room.room_id == room.room_id:
                        self._waiting_room = None
                break

    def find_room(self, ws):
        for room in self.rooms.values():
            player = room.find_player(ws)
            if player:
                return room, player["player_id"]
        return None, None


room_manager = RoomManager()
