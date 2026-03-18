import os
import asyncio
import mysql.connector


def _save_score_sync(name: str, score: int, duration_ms: int):
    db = mysql.connector.connect(
        host=os.getenv("DB_HOST", "db"),
        user=os.getenv("DB_USER", "snake"),
        password=os.getenv("DB_PASS", "snakepass"),
        database=os.getenv("DB_NAME", "snake"),
    )
    cur = db.cursor()
    cur.execute("SELECT id FROM players WHERE name=%s", (name,))
    row = cur.fetchone()
    if row:
        player_id = row[0]
    else:
        cur.execute("INSERT INTO players(name) VALUES (%s)", (name,))
        player_id = cur.lastrowid
    cur.execute(
        "INSERT INTO scores(player_id, score, duration_ms) VALUES (%s, %s, %s)",
        (player_id, score, duration_ms),
    )
    db.commit()
    cur.close()
    db.close()


async def save_score(name: str, score: int, duration_ms: int):
    try:
        await asyncio.to_thread(_save_score_sync, name, score, duration_ms)
    except Exception as e:
        print(f"DB error saving score for {name}: {e}")
