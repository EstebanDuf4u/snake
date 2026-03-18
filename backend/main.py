import os
import json
from fastapi import FastAPI, HTTPException, WebSocket, Header, Cookie
from pydantic import BaseModel
from jose import JWTError, jwt
from parser import WSParser
from score import save_score

JWT_SECRET = os.getenv("JWT_SECRET", "dgames_secret_changeme")
ALGORITHM  = "HS256"

def _username_from_token(authorization: str | None, cookie: str | None = None) -> str | None:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    elif cookie:
        token = cookie
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


app = FastAPI()


class ScoreIn(BaseModel):
    name: str
    score: int
    duration_ms: int


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/score")
async def post_score(s: ScoreIn, authorization: str = Header(None), dgames_token: str = Cookie(None)):
    account = _username_from_token(authorization, dgames_token)
    if not account:
        return {"ok": False, "reason": "not authenticated"}
    if s.score < 0 or s.duration_ms < 0:
        raise HTTPException(400, "Invalid score/duration")
    await save_score(account, s.score, s.duration_ms)
    return {"ok": True}


@app.get("/api/leaderboard")
async def leaderboard(limit: int = 10, period: str = "all"):
    import asyncio
    import mysql.connector
    limit = max(1, min(limit, 50))

    def _query():
        db = mysql.connector.connect(
            host=os.getenv("DB_HOST", "db"),
            user=os.getenv("DB_USER", "snake"),
            password=os.getenv("DB_PASS", "snakepass"),
            database=os.getenv("DB_NAME", "snake"),
        )
        cur = db.cursor(dictionary=True)
        if period == "monthly":
            sql = """
                SELECT p.name, s.score, s.duration_ms
                FROM scores s
                JOIN players p ON p.id = s.player_id
                INNER JOIN (
                    SELECT player_id, MAX(score) AS best
                    FROM scores
                    WHERE YEAR(created_at) = YEAR(CURDATE())
                      AND MONTH(created_at) = MONTH(CURDATE())
                    GROUP BY player_id
                ) top ON s.player_id = top.player_id AND s.score = top.best
                WHERE YEAR(s.created_at) = YEAR(CURDATE())
                  AND MONTH(s.created_at) = MONTH(CURDATE())
                ORDER BY s.score DESC, s.duration_ms ASC
                LIMIT %s
            """
        else:
            sql = """
                SELECT p.name, s.score, s.duration_ms
                FROM scores s
                JOIN players p ON p.id = s.player_id
                INNER JOIN (
                    SELECT player_id, MAX(score) AS best
                    FROM scores
                    GROUP BY player_id
                ) top ON s.player_id = top.player_id AND s.score = top.best
                ORDER BY s.score DESC, s.duration_ms ASC
                LIMIT %s
            """
        cur.execute(sql, (limit,))
        rows = cur.fetchall()
        cur.close()
        db.close()
        return rows

    return await asyncio.to_thread(_query)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    parser = WSParser()
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            await parser.parse(websocket, msg)
    except Exception as e:
        print("WebSocket disconnected:", e)
    finally:
        await parser.on_disconnect(websocket)
