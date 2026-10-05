import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from sqlalchemy import select, func
from app.agent import claim, execute, build_graph
from app.models import Run, Analysis, Evidence, Document
from app.providers import MockProvider, DeepSeekProvider
from app.errors import AppError
from conftest import register, create_run
import httpx
import pytest


class CrashAfterTools(MockProvider):
    async def complete(self, messages, final=False):
        if any(m["role"] == "tool" for m in messages):
            raise SystemExit("simulated abrupt worker death")
        return await super().complete(messages, final)


def test_resume_persisted_tool_checkpoint_without_duplicate_evidence(client, app):
    project = register(client)["projects"][0]["id"]
    run = create_run(client, project)
    job = claim(app.state.factory, app.state.settings)
    # Exercise the graph directly so the test can model process death (not a handled provider failure).
    graph = build_graph(app.state.factory, app.state.settings, *job, CrashAfterTools())
    from app.agent import SYSTEM
    state = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "生化清洗液补货"}], "calls": 0, "pending": [], "stage": "model", "inventory": [], "evidence_ids": [], "knowledge_ids": [], "metadata": []}
    with pytest.raises(SystemExit):
        asyncio.run(graph.ainvoke(state))
    with app.state.factory() as db:
        row = db.get(Run, run["run_id"])
        assert row.checkpoint["stage"] == "model" and row.checkpoint["calls"] == 2
        before = db.scalar(select(func.count()).select_from(Evidence).where(Evidence.run_id == row.id))
        row.lease_until = time.time() - 1
        db.commit()
    second = claim(app.state.factory, app.state.settings)
    asyncio.run(execute(app.state.factory, app.state.settings, *second))
    with app.state.factory() as db:
        assert db.get(Run, run["run_id"]).status == "succeeded"
        assert db.scalar(select(func.count()).select_from(Evidence).where(Evidence.run_id == run["run_id"])) == before


def test_worker_retry_exhaustion(client, app):
    project = register(client)["projects"][0]["id"]
    run = create_run(client, project)
    for _ in range(2):
        assert claim(app.state.factory, app.state.settings)
        with app.state.factory() as db:
            db.get(Run, run["run_id"]).lease_until = time.time() - 1
            db.commit()
    assert claim(app.state.factory, app.state.settings) is None
    result = client.get(f"/api/v1/runs/{run['run_id']}").json()
    assert result["status"] == "failed" and result["error"]["code"] == "WORKER_RETRY_EXHAUSTED"


def test_cancel_running_fences_late_result(client, app):
    project = register(client)["projects"][0]["id"]
    run = create_run(client, project)
    job = claim(app.state.factory, app.state.settings)
    assert client.post(f"/api/v1/runs/{run['run_id']}/cancel").json()["status"] == "cancelled"
    asyncio.run(execute(app.state.factory, app.state.settings, *job))
    with app.state.factory() as db:
        assert db.get(Run, run["run_id"]).status == "cancelled"
        assert db.scalar(select(func.count()).select_from(Analysis).where(Analysis.run_id == run["run_id"])) == 0


def test_retired_citation_remains_readable_but_marked(client, app):
    project = register(client)["projects"][0]["id"]
    run = create_run(client, project)
    from app.agent import work_once
    work_once(app.state.factory, app.state.settings)
    result = client.get(f"/api/v1/runs/{run['run_id']}").json()
    analysis = client.get(f"/api/v1/analyses/{result['analysis_id']}").json()
    citation = next(c for c in analysis["citations"] if c["source_kind"] == "document")
    with app.state.factory() as db:
        db.get(Document, citation["location"]["document_id"]).status = "retired_demo"
        db.commit()
    assert not client.get(f"/api/v1/evidence/{citation['evidence_id']}").json()["currently_valid"]


@pytest.mark.parametrize("response", [{"choices": []}, {"choices": [{"message": {"content": ""}}]}, {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}])
def test_provider_empty_and_truncated(response, app):
    app.state.settings.deepseek_api_key = "fake-test-key"
    provider = DeepSeekProvider(app.state.settings, httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    with pytest.raises(AppError) as caught:
        asyncio.run(provider.complete([]))
    assert caught.value.body["code"] in {"MODEL_OUTPUT_INVALID", "MODEL_OUTPUT_TRUNCATED"}


def test_alembic_fresh_database_and_postgres_offline_compilation(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'migrated.db'}", "CSRF_SECRET": "migration-test-secret-with-32-characters"}
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    env["DATABASE_URL"] = "postgresql+psycopg://spd:unused@127.0.0.1:5432/spd"
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head", "--sql"], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0 and "CREATE TABLE agent_runs" in result.stdout
    # SQL compilation is explicitly NOT a live PostgreSQL integration test.
