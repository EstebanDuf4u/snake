import sys
import os
import paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST     = "178.104.51.243"
USER     = "esteban"
PASSWORD = "esteban"

SNAKE_DIR = "/home/esteban/snake"
AUTH_DIR  = "/home/esteban/auth"

SNAKE_FILES = [
    ("frontend/index.html",            f"{SNAKE_DIR}/frontend/index.html"),
    ("frontend/snake.py",              f"{SNAKE_DIR}/frontend/snake.py"),
    ("frontend/parser.py",             f"{SNAKE_DIR}/frontend/parser.py"),
    ("frontend/nginx.conf",            f"{SNAKE_DIR}/frontend/nginx.conf"),
    ("backend/main.py",                f"{SNAKE_DIR}/backend/main.py"),
    ("backend/parser.py",              f"{SNAKE_DIR}/backend/parser.py"),
    ("backend/GameState.py",           f"{SNAKE_DIR}/backend/GameState.py"),
    ("backend/score.py",               f"{SNAKE_DIR}/backend/score.py"),
    ("backend/requirements.txt",       f"{SNAKE_DIR}/backend/requirements.txt"),
    ("backend/rooms/__init__.py",      f"{SNAKE_DIR}/backend/rooms/__init__.py"),
    ("backend/rooms/rooms.py",         f"{SNAKE_DIR}/backend/rooms/rooms.py"),
    ("backend/rooms/room_manager.py",  f"{SNAKE_DIR}/backend/rooms/room_manager.py"),
    ("docker-compose.yml",             f"{SNAKE_DIR}/docker-compose.yml"),
    (".env",                           f"{SNAKE_DIR}/.env"),
]

AUTH_BASE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "auth")
AUTH_FILES = [
    ("main.py",            f"{AUTH_DIR}/main.py"),
    ("requirements.txt",   f"{AUTH_DIR}/requirements.txt"),
    ("Dockerfile",         f"{AUTH_DIR}/Dockerfile"),
    ("docker-compose.yml", f"{AUTH_DIR}/docker-compose.yml"),
    ("models.sql",         f"{AUTH_DIR}/models.sql"),
    (".env",               f"{AUTH_DIR}/.env"),
]


def run(ssh, cmd):
    print(f"\n$ {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
    for line in iter(stdout.readline, ""):
        print(line, end="")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        print(f"ERROR (exit {code}): {stderr.read().decode('utf-8', errors='replace')}")
    return code


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"Connecting to {HOST}...")
ssh.connect(HOST, username=USER, password=PASSWORD)
sftp = ssh.open_sftp()

# ── Auth service ──────────────────────────────────────────────────────────────
print("\n=== Auth service ===")
for d in [AUTH_DIR]:
    try: sftp.mkdir(d)
    except IOError: pass

print("Uploading auth files...")
for local_rel, remote in AUTH_FILES:
    local = os.path.join(AUTH_BASE, local_rel)
    if not os.path.exists(local):
        print(f"  SKIP: {local_rel}")
        continue
    sftp.put(local, remote)
    print(f"  OK: {local_rel}")

# ── Snake ─────────────────────────────────────────────────────────────────────
print("\n=== Snake ===")
for d in [SNAKE_DIR, f"{SNAKE_DIR}/frontend", f"{SNAKE_DIR}/backend", f"{SNAKE_DIR}/backend/rooms"]:
    try: sftp.mkdir(d)
    except IOError: pass

print("Uploading snake files...")
BASE = os.path.dirname(os.path.abspath(__file__))
for local_rel, remote in SNAKE_FILES:
    local = os.path.join(BASE, local_rel)
    if not os.path.exists(local):
        print(f"  SKIP: {local_rel}")
        continue
    sftp.put(local, remote)
    print(f"  OK: {local_rel}")

sftp.close()

# ── Docker ────────────────────────────────────────────────────────────────────
print("\n=== Docker ===")

# Créer le réseau dgames si besoin
run(ssh, "docker network create dgames 2>/dev/null || true")

# Déployer auth
for cmd in [
    f"cd {AUTH_DIR} && docker compose down",
    f"cd {AUTH_DIR} && docker compose build --no-cache",
    f"cd {AUTH_DIR} && docker compose up -d",
]:
    if run(ssh, cmd) != 0:
        break

# Déployer snake
for cmd in [
    f"cd {SNAKE_DIR} && docker compose down",
    f"cd {SNAKE_DIR} && docker compose build --no-cache",
    f"cd {SNAKE_DIR} && docker compose up -d",
]:
    if run(ssh, cmd) != 0:
        break

ssh.close()
print("\nDone!")
