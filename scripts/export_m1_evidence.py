"""Generate a credential-free local verification manifest from the M1 test account."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings
from app.db import make_engine, session_factory
from app.models import User, Membership, Run, Analysis, RunEvent
from sqlalchemy import select


def main():
    settings = Settings()
    engine = make_engine(settings.database_url)
    factory = session_factory(engine)
    output = {"recorded_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(), "database": engine.dialect.name,
              "dependencies": {name: importlib.metadata.version(name) for name in ["fastapi", "sqlalchemy", "alembic", "pydantic", "langgraph", "langgraph-checkpoint", "httpx", "argon2-cffi", "uvicorn", "psycopg"]},
              "real_deepseek_verified": False, "vector_search_verified": False, "postgres_live_verified": False, "cloud_deployed": False,
              "test_account_runs": [], "source_sha256": {}}
    with factory() as db:
        user = db.scalar(select(User).where(User.email == "m1-browser@example.test"))
        if user:
            runs = db.scalars(select(Run).where(Run.actor_id == user.id).order_by(Run.created_at)).all()
            for run in runs:
                analysis = db.scalar(select(Analysis).where(Analysis.run_id == run.id))
                events = db.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.cursor)).all()
                output["test_account_runs"].append({"run_id": run.id, "provider_mode": run.provider, "status": run.status, "attempts": run.attempts, "question": run.request["question"],
                                                   "error_code": run.error["code"] if run.error else None, "analysis_id": analysis.id if analysis else None,
                                                   "retrieval_mode": analysis.body["retrieval_mode"] if analysis else None,
                                                   "citation_count": len(analysis.body["citations"]) if analysis else 0,
                                                   "events": [{"cursor": e.cursor, "type": e.type, "step": e.step} for e in events]})
    paths = []
    for directory in ["backend/app", "backend/tests", "backend/migrations", "frontend/src/m1", "frontend/scripts"]:
        paths.extend(p for p in (ROOT / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    paths += [ROOT / p for p in ["backend/uv.lock", "backend/pyproject.toml", "frontend/pnpm-lock.yaml", "frontend/package.json", "frontend/src/main.jsx", "frontend/vite.config.mjs", "scripts/start_m1.py", "scripts/export_m1_evidence.py"]]
    for path in sorted(paths):
        output["source_sha256"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (ROOT / "docs/verification/m1-runtime-evidence.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    engine.dispose()
    print("Wrote docs/verification/m1-runtime-evidence.json (no credentials or session tokens)")


if __name__ == "__main__":
    main()
