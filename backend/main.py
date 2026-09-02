import os
import json
import asyncio
import hashlib
import hmac
import secrets
import mysql.connector
from fastapi import FastAPI, HTTPException, Header, WebSocket
from pydantic import BaseModel
from parser import WSParser
from score import save_score


app = FastAPI()


@app.on_event("startup")
async def ensure_auth_schema():
    def migrate():
        db = _db()
        cur = db.cursor()
        try:
            try:
                cur.execute("ALTER TABLE players ADD COLUMN password_hash VARCHAR(256)")
            except mysql.connector.Error as error:
                if error.errno != 1060:
                    raise
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                  token CHAR(64) PRIMARY KEY,
                  player_id INT NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  CONSTRAINT fk_sessions_player FOREIGN KEY (player_id) REFERENCES players(id)
                )
            """)
            db.commit()
        finally:
            cur.close()
            db.close()
    await asyncio.to_thread(migrate)


class ScoreIn(BaseModel):
    name: str
    score: int
    duration_ms: int


class CredentialsIn(BaseModel):
    username: str
    password: str


def _db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "db"),
        user=os.getenv("DB_USER", "snake"),
        password=os.getenv("DB_PASS", "snakepass"),
        database=os.getenv("DB_NAME", "snake"),
    )


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120000)
    return f"{salt.hex()}${digest.hex()}"


def _password_matches(password: str, stored: str) -> bool:
    if not stored:
        return False
    salt_hex, digest_hex = stored.split("$", 1)
    candidate = _password_hash(password, bytes.fromhex(salt_hex)).split("$", 1)[1]
    return hmac.compare_digest(candidate, digest_hex)


def _validate_credentials(credentials: CredentialsIn):
    username = credentials.username.strip()
    if not 3 <= len(username) <= 24 or not username.replace("_", "").isalnum():
        raise HTTPException(400, "Username: 3 a 24 caracteres alphanumeriques")
    if not 6 <= len(credentials.password) <= 128:
        raise HTTPException(400, "Le mot de passe doit contenir 6 caracteres minimum")
    return username


def _create_account(credentials: CredentialsIn):
    username = _validate_credentials(credentials)
    db = _db()
    cur = db.cursor()
    try:
        cur.execute("SELECT id FROM players WHERE name=%s", (username,))
        if cur.fetchone():
            raise HTTPException(409, "Ce pseudo est deja pris")
        cur.execute(
            "INSERT INTO players(name, password_hash) VALUES (%s, %s)",
            (username, _password_hash(credentials.password)),
        )
        db.commit()
    finally:
        cur.close()
        db.close()
    return username


def _create_session(credentials: CredentialsIn):
    username = credentials.username.strip()
    db = _db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, name, password_hash FROM players WHERE name=%s", (username,))
        player = cur.fetchone()
        if not player or not _password_matches(credentials.password, player["password_hash"]):
            raise HTTPException(401, "Pseudo ou mot de passe incorrect")
        token = secrets.token_hex(32)
        cur.execute("INSERT INTO sessions(token, player_id) VALUES (%s, %s)", (token, player["id"]))
        db.commit()
        return {"token": token, "username": player["name"]}
    finally:
        cur.close()
        db.close()


def _player_from_token(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Connexion requise")
    token = authorization[7:].strip()
    db = _db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT p.id, p.name FROM sessions s JOIN players p ON p.id=s.player_id WHERE s.token=%s",
            (token,),
        )
        player = cur.fetchone()
    finally:
        cur.close()
        db.close()
    if not player:
        raise HTTPException(401, "Session invalide")
    return player


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/signup")
async def signup(credentials: CredentialsIn):
    username = await asyncio.to_thread(_create_account, credentials)
    return {"ok": True, "username": username}


@app.post("/api/login")
async def login(credentials: CredentialsIn):
    return await asyncio.to_thread(_create_session, credentials)


@app.post("/api/score")
async def post_score(s: ScoreIn, authorization: str | None = Header(default=None)):
    if s.score < 0 or s.duration_ms < 0:
        raise HTTPException(400, "Invalid score/duration")
    player = await asyncio.to_thread(_player_from_token, authorization)
    await save_score(player["name"], s.score, s.duration_ms)
    return {"ok": True}


@app.get("/api/leaderboard")
async def leaderboard(limit: int = 10, period: str = "all"):
    limit = max(1, min(limit, 50))

    def _query():
        db = _db()
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
