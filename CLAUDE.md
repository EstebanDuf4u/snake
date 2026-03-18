# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the project

Everything runs via Docker Compose:

```bash
docker compose up --build   # first run or after backend changes
docker compose up           # subsequent runs
```

The app is available at **http://localhost:8090**. The backend API runs internally on port 8000 and is proxied by Nginx.

To restart only the backend after Python changes (hot-reload is enabled via `--reload`):
```bash
docker compose restart api
```

To view logs:
```bash
docker compose logs -f api
```

## Architecture overview

Three Docker services:
- **db** — MariaDB 11, initialized with `backend/models.sql`
- **api** — FastAPI (uvicorn), the game server
- **front** — Nginx serving static files, proxying `/api/` and `/ws` to the API

### Frontend

The frontend is written in **Python using Brython** (Python runtime in the browser, loaded as `brython.js`). There is no build step — Python files are served as static assets and executed client-side.

- `frontend/snake.py` — main entry point: canvas rendering (60fps rAF loop), input handling (keyboard + touch + d-pad), WebSocket connection management, leaderboard API calls
- `frontend/parser.py` — `WSFrontParser` class: routes incoming WebSocket messages to game state updates

### Backend

- `backend/main.py` — FastAPI app: `GET /api/health`, `POST /api/score`, `GET /api/leaderboard`, `WebSocket /ws`
- `backend/parser.py` — `WSParser`: per-connection handler, routes `join`/`input` messages, manages solo game task lifecycle
- `backend/GameState.py` — `GameState`: solo game logic (tick, collision, apple generation) on a 20×20 grid
- `backend/rooms/rooms.py` — `MultiGameState` + `Room` + `BotAI`: multiplayer game state, room lifecycle, greedy+flood-fill bot
- `backend/rooms/room_manager.py` — `RoomManager` singleton: matchmaking (public queue or private room by code), bot fill after 5s delay
- `backend/score.py` — async wrapper around synchronous MariaDB writes for score persistence

### WebSocket message flow

Client → Server: `join` (with `mode: "solo"|"multi"` and optional `room_code`), `input` (direction)

Server → Client: `joined`, `waiting`, `bot_joining`, `game_start`, `state`, `countdown`, `player_left`, `error`

The `state` message shape differs between solo (single snake/apple) and multi (snakes/apples dicts keyed by player_id).

### Key design details

- **`parser.py` exists in both `backend/` and `frontend/`** — these are completely separate classes (`WSParser` vs `WSFrontParser`)
- Solo game speed is adaptive: interval starts at 0.22s and decreases by 0.007s per point (min 0.09s)
- Multiplayer tick is fixed at 0.15s; 12 apples are maintained on the board at all times
- When a snake dies in multi, its body cells become apples
- Private rooms use a user-provided code as the room ID; public matchmaking auto-generates a UUID-based ID
- Input rate-limited server-side to 50ms minimum between inputs
- Scores are always recorded (solo: from client after game over; multi: from server after game loop ends)
