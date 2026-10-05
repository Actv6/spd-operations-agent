import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.agent import work_once, claim, execute, checkpoint
from app.models import Run, Analysis, Evidence, Membership, Document
from app.providers import MockProvider
from app.errors import AppError
from conftest import register, create_run, request_body, ORIGIN


def test_standalone_run_events_result_and_idempotency(client, app):
    project = register(client)["projects"][0]["id"]
    run = create_run(client, project)
    assert create_run(client, project)["run_id"] == run["run_id"]
    conflict = client.post(f"/api/v1/projects/{project}/runs", headers={"Idempotency-Key": "test-run-key"}, json=request_body("另一个问题"))
    assert conflict.status_code == 409
    assert work_once(app.state.factory, app.state.settings)
    run = client.get(f"/api/v1/runs/{run['run_id']}").json()
    assert run["status"] == "succeeded", run
    analysis = client.get(f"/api/v1/analyses/{run['analysis_id']}").json()
    assert analysis["generation_mode"] == "mock" and analysis["retrieval_mode"] == "lexical"
    assert analysis["inventory"][0]["available"] == "120"
    assert len(analysis["citations"]) >= 2
    assert all(c["usage"] is None and c["cost"] is None for c in analysis["provider_metadata"]["calls"])
    first = client.get(f"/api/v1/runs/{run['run_id']}/events?limit=2").json()
    second = client.get(f"/api/v1/runs/{run['run_id']}/events?after={first['next_cursor']}").json()
    cursors = [int(e["cursor"]) for e in first["items"] + second["items"]]
    assert cursors == list(range(1, len(cursors) + 1))
    assert first["has_more"] and second["items"][-1]["type"] == "run_finished"
    assert not work_once(app.state.factory, app.state.settings)
    with TestClient(app) as other:
        other.headers.update({"Origin": ORIGIN, "X-CSRF-Token": other.get("/api/v1/csrf").json()["token"]})
        register(other, "another@example.test")
        for path in [f"runs/{run['run_id']}", f"runs/{run['run_id']}/events", f"analyses/{run['analysis_id']}", f"evidence/{analysis['citations'][0]['evidence_id']}"]:
            assert other.get("/api/v1/" + path).status_code == 404
    # A fresh app/engine instance reads persisted session/run/result after restart.
    from app.main import create_app
    restarted = create_app(app.state.settings)
    with TestClient(restarted) as fresh:
        fresh.cookies.update(client.cookies)
        assert fresh.get(f"/api/v1/analyses/{run['analysis_id']}").json() == analysis
    restarted.state.engine.dispose()


def test_real_provider_missing_key_is_failure(client, app):
    app.state.settings.llm_provider = "deepseek"
    app.state.settings.deepseek_api_key = ""
    project = register(client)["projects"][0]["id"]
    run = create_run(client, project)
    work_once(app.state.factory, app.state.settings)
    result = client.get(f"/api/v1/runs/{run['run_id']}").json()
    assert result["generation_mode"] == "model" and result["status"] == "failed"
    assert result["error"]["code"] == "PROVIDER_NOT_CONFIGURED" and result["analysis_id"] is None


def test_queue_concurrency_lease_fencing_and_retry(client, app):
    project = register(client)["projects"][0]["id"]
    run = create_run(client, project)
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: claim(app.state.factory, app.state.settings), range(2)))
    assert sum(c is not None for c in claims) == 1
    old = next(c for c in claims if c)
    with app.state.factory() as db:
        db.get(Run, run["run_id"]).lease_until = time.time() - 1
        db.commit()
    new = claim(app.state.factory, app.state.settings)
    assert new[0] == old[0] and new[1] != old[1]
    with pytest.raises(AppError, match="租约"):
        checkpoint(app.state.factory, *old, {}, "bad")
    asyncio.run(execute(app.state.factory, app.state.settings, *new))
    assert client.get(f"/api/v1/runs/{run['run_id']}").json()["status"] == "succeeded"
    with app.state.factory() as db:
        assert db.scalar(select(func.count()).select_from(Analysis).where(Analysis.run_id == run["run_id"])) == 1


def test_cancel_and_revocation(client, app):
    me = register(client)
    project = me["projects"][0]["id"]
    run = create_run(client, project)
    assert client.post(f"/api/v1/runs/{run['run_id']}/cancel").json()["status"] == "cancelled"
    assert not work_once(app.state.factory, app.state.settings)
    run = create_run(client, project, "revoked-key")
    with app.state.factory() as db:
        db.delete(db.get(Membership, (me["user"]["id"], project)))
        db.commit()
    work_once(app.state.factory, app.state.settings)
    with app.state.factory() as db:
        assert db.get(Run, run["run_id"]).status == "failed"
    assert client.get(f"/api/v1/runs/{run['run_id']}").status_code == 404


class BrokenProvider:
    def __init__(self, scenario):
        self.scenario = scenario

    async def complete(self, messages, final=False):
        if self.scenario == "timeout":
            await asyncio.sleep(2)
        if self.scenario in {"bad-json", "false-citation"}:
            return {"role": "assistant", "content": "oops" if self.scenario == "bad-json" else json.dumps({"answer": "假的", "evidence_ids": ["invented"], "insufficient_evidence": False})}, {}
        args = {"item_ids": ["SIM-P002"], "department_ids": []} if self.scenario == "scope" else {"raw_sql": "select *"}
        call = {"id": "x", "type": "function", "function": {"name": "delete_inventory" if self.scenario == "unknown" else "get_inventory", "arguments": json.dumps(args)}}
        return {"role": "assistant", "content": None, "tool_calls": [call] * (5 if self.scenario == "budget" else 1)}, {}


@pytest.mark.parametrize("scenario,code", [("unknown", "TOOL_NOT_ALLOWED"), ("scope", "TOOL_SCOPE_REJECTED"), ("bad-args", "TOOL_ARGUMENTS_INVALID"), ("budget", "TOOL_BUDGET_EXCEEDED"), ("bad-json", "MODEL_OUTPUT_INVALID"), ("false-citation", "INVALID_CITATION"), ("timeout", "RUN_TIMEOUT")])
def test_failure_modes(client, app, scenario, code):
    project = register(client)["projects"][0]["id"]
    run = create_run(client, project)
    if scenario == "timeout":
        app.state.settings.run_timeout_seconds = 1
    work_once(app.state.factory, app.state.settings, BrokenProvider(scenario))
    result = client.get(f"/api/v1/runs/{run['run_id']}").json()
    assert result["status"] == "failed" and result["error"]["code"] == code, result


def test_no_evidence_and_strict_request_contract(client, app):
    project = register(client)["projects"][0]["id"]
    for extra in [{"model": "evil"}, {"mode": "draft_action"}, {"org_id": "other"}]:
        response = client.post(f"/api/v1/projects/{project}/runs", json={**request_body(), **extra}, headers={"Idempotency-Key": "bad-body-key"})
        assert response.status_code == 422
    run = create_run(client, project, body=request_body("量子宇宙星际飞船"))
    work_once(app.state.factory, app.state.settings)
    run = client.get(f"/api/v1/runs/{run['run_id']}").json()
    result = client.get(f"/api/v1/analyses/{run['analysis_id']}").json()
    assert result["insufficient_evidence"] and "未检索到" in result["answer"]
