import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models import Base

ORIGIN = "http://127.0.0.1:4180"


@pytest.fixture
def app(tmp_path, monkeypatch):
    from app import data, knowledge
    from app.config import ROOT
    monkeypatch.setattr(data, "DATA", ROOT.parent / "data/synthetic")
    monkeypatch.setattr(knowledge, "DATA", ROOT.parent / "data/synthetic")
    app = create_app(Settings(_env_file=None, llm_provider="mock", database_url=f"sqlite:///{tmp_path / 'test.db'}", csrf_secret="test-secret-with-at-least-32-characters", rate_limit=100, max_tool_calls=4))
    Base.metadata.create_all(app.state.engine)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": client.get("/api/v1/csrf").json()["token"]})
        yield client


def register(client, email="first@example.test"):
    response = client.post("/api/v1/registrations", json={"email": email, "password": "safe-demo-password", "display_name": "测试用户"})
    assert response.status_code == 201, response.text
    return response.json()


def request_body(question="生化清洗液缺货补货核查", **context):
    return {"schema_version": "1", "mode": "analyze", "question": question, "session_id": None, "parent_run_id": None,
            "context": {"snapshot_set_id": None, "item_ids": ["SIM-P001"], "department_ids": [], "analysis_id": None, **context}, "options": {"window_days": 14}}


def create_run(client, project_id, key="test-run-key", body=None):
    response = client.post(f"/api/v1/projects/{project_id}/runs", json=body or request_body(), headers={"Idempotency-Key": key})
    assert response.status_code == 202, response.text
    return response.json()


def complete_human_reviews(client, *run_ids):
    """Explicit human-review API fixtures for task lifecycle regression, not real acceptance."""
    for run_id in run_ids:
        url = '/api/v1/runs/' + run_id + '/human-review'
        view = client.get(url).json()
        response = client.post(url, json={
            'revision': view['revision'], 'source_token': view['source_token'], 'status': 'confirmed',
            'conclusion': '受控测试：已核对范围内结论，继续测试个人待办生命周期。',
            'basis': '受控测试：逐项核对本次快照和保存的资料，非实际业务签收。',
            'next_step': '', 'evidence_ids': [e['evidence_id'] for e in view['available_evidence']],
            'handled_feedback_ids': [f['id'] for f in view['pending_feedback']],
        }, headers={'Idempotency-Key': 'lifecycle-human-review-key'})
        assert response.status_code == 200, response.text
