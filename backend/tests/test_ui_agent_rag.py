import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.agent import initial_state, work_once
from app.models import Run, Project, Document
from app.providers import MockProvider
from app.knowledge import ingest, search
from conftest import register, create_run, request_body, ORIGIN
from test_enterprise import use_scenario


def test_scoped_catalog_uses_verified_ids_not_inventory_answers(client, app, monkeypatch):
    use_scenario(monkeypatch)
    project = register(client)["projects"][0]["id"]
    run = create_run(client, project, body=request_body("核查生化清洗液 MAT-0001"))
    with app.state.factory() as db:
        state = initial_state(db, db.get(Run, run["run_id"]))
        context = json.loads(state["messages"][1]["content"].split("\n", 1)[1])
        rows = context["scoped_inventory_catalog"]
        assert len(rows) == 1
        assert rows[0]["item_id"] == "SIM-P001"
        assert rows[0]["display_code"] == "MAT-0001"
        assert rows[0]["name"] == "生化清洗液" and rows[0]["department_name"]
        assert "available" not in rows[0] and "coverage_days" not in rows[0]

    class CatalogProvider(MockProvider):
        async def complete(self, messages, final=False):
            message, metadata = await super().complete(messages, final)
            if message.get("tool_calls"):
                catalog = json.loads(messages[1]["content"].split("\n", 1)[1])["scoped_inventory_catalog"]
                message["tool_calls"][0]["function"]["arguments"] = json.dumps({"item_ids": [catalog[0]["item_id"]], "department_ids": []})
            return message, metadata

    work_once(app.state.factory, app.state.settings, CatalogProvider())
    assert client.get(f"/api/v1/runs/{run['run_id']}").json()["status"] == "succeeded"


@pytest.mark.parametrize("invalid_id", ["生化清洗液", "MAT-0001", "SIM-P002"])
def test_catalog_fix_does_not_relax_scope(client, app, invalid_id):
    project = register(client)["projects"][0]["id"]
    run = create_run(client, project)

    class InvalidProvider(MockProvider):
        async def complete(self, messages, final=False):
            return {"role": "assistant", "content": None, "tool_calls": [{"id": "invalid", "type": "function", "function": {"name": "get_inventory", "arguments": json.dumps({"item_ids": [invalid_id], "department_ids": []})}}]}, {}

    work_once(app.state.factory, app.state.settings, InvalidProvider())
    result = client.get(f"/api/v1/runs/{run['run_id']}").json()
    assert result["status"] == "failed" and result["analysis_id"] is None
    assert result["error"]["code"] == "TOOL_SCOPE_REJECTED"


@pytest.mark.parametrize("query,expected", [
    ("缺货没货联系谁补货", "SHORTAGE"),
    ("在途订单未交数量到货日期", "ETA"),
    ("箱与瓶采购包装换算", "UNITS"),
    ("科室盘亏盘盈差异", "STOCKTAKE"),
    ("质量冻结解除冻结", "HOLD"),
    ("缺两天记录只有12天", "MISSING"),
    ("过期快照刷新超过24小时", "STALE"),
    ("收货验收外包装交接单", "RECEIVE"),
    ("MAT-0001生化清洗液规格供应商", "MAT-0001"),
])
def test_enterprise_retrieval_relevant_sources(client, app, monkeypatch, query, expected):
    use_scenario(monkeypatch)
    project = register(client)["projects"][0]["id"]
    with app.state.factory() as db:
        hits = search(db, project, query)
        assert f"OPS-KB-{expected}-v1" in {h["document_external_id"] for h in hits}
        for hit in hits:
            doc = db.get(Document, hit["document_id"])
            assert doc.content[hit["start_offset"]:hit["end_offset"]] == hit["excerpt"]
            assert hashlib.sha256(doc.content.encode()).hexdigest() == hit["source_hash"]


def test_enterprise_ingest_idempotence_hospital_acl_and_no_evidence(client, app, monkeypatch):
    use_scenario(monkeypatch)
    project_id = register(client)["projects"][0]["id"]
    with app.state.factory() as db:
        project = db.get(Project, project_id)
        assert ingest(db, project) == 0
        assert search(db, project_id, "量子宇宙星际飞船") == []
        other = Project(org_id=project.org_id, name="另一项目", source_hospital="SIM-HB")
        db.add(other)
        db.flush()
        ingest(db, other)
        ids = set(db.scalars(select(Document.external_id).where(Document.project_id == other.id)))
        assert not any("CASE-" in i for i in ids)
        assert "OPS-KB-SHORTAGE-v1" in ids


def test_knowledge_catalog_details_counts_and_project_acl(client, app, monkeypatch):
    use_scenario(monkeypatch)
    project = register(client)["projects"][0]["id"]
    path = f"/api/v1/projects/{project}/knowledge/documents"
    response = client.get(path)
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 46 and all(d["currently_valid"] for d in items)
    stats = client.get(f"/api/v1/projects/{project}/dashboard").json()["stats"]
    assert stats["active_documents"] == 46
    assert stats["knowledge_chunks"] == sum(d["chunk_count"] for d in items)
    docpath = f"/api/v1/knowledge/documents/{items[0]['document_id']}"
    detail = client.get(docpath).json()
    assert hashlib.sha256(detail["content"].encode()).hexdigest() == detail["source_hash"]
    with TestClient(app) as other:
        other.headers.update({"Origin": ORIGIN, "X-CSRF-Token": other.get("/api/v1/csrf").json()["token"]})
        register(other, "second@example.test")
        assert other.get(path).status_code == 404
        assert other.get(docpath).status_code == 404
