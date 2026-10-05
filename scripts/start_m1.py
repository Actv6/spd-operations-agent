"""Start the local API, one worker, and Vite; terminate only children started here."""
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    python = ROOT / "backend" / ".venv" / "bin" / "python"
    node = os.environ.get("M1_NODE") or shutil.which("node")
    bundled_node = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
    if not node and bundled_node.exists():
        node = str(bundled_node)
    if not python.exists() or not node:
        raise SystemExit("Install backend dependencies with uv sync and make Node available; see backend/README.md")
    for port in [8010, 4180]:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is already in use; leave existing services intact and stop them explicitly if needed.")
    if not (ROOT / "backend/.env").exists():
        subprocess.run([str(python), "-m", "app.cli", "init-config"], cwd=ROOT / "backend", check=True)
    subprocess.run([str(python), "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend", check=True)
    children = []
    try:
        children.append(subprocess.Popen([str(python), "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "8010"], cwd=ROOT / "backend", start_new_session=True))
        children.append(subprocess.Popen([str(python), "-m", "app.worker"], cwd=ROOT / "backend", start_new_session=True))
        children.append(subprocess.Popen([node, "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "4180", "--strictPort"], cwd=ROOT / "frontend", start_new_session=True))
        print("Local SPD M3: http://127.0.0.1:4180 — Ctrl+C stops these three processes.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
