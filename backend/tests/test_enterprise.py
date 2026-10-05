import json
from sqlalchemy import select, func
from app.config import ROOT, Settings
from app.models import Project, Document, Snapshot, Analysis, Evidence
from app.data import inventory, snapshot_for
from app.knowledge import search
from app.scenario import publish
from app.agent import work_once
from conftest import register, create_run


def use_scenario(monkeypatch):
    from app import data, knowledge
    for module in (data, knowledge):
        monkeypatch.setattr(module, "DATA", ROOT.parent / "data/scenario")


def test_new_registration_uses_enterprise_scenario(client, app, monkeypatch):
    use_scenario(monkeypatch)
    project = register(client)["projects"][0]
    assert project["name"] == "澄川医院 · SPD 项目"
    dashboard = client.get(f"/api/v1/projects/{project['id']}/dashboard").json()
    row = dashboard["inventory"][0]
    assert row["display_code"] == "MAT-0001"
    assert row["name"] == "生化清洗液"
    assert row["specification"] and row["available"] == "120"
    with app.state.factory() as db:
        hits = search(db, project["id"], "缺货补货")
        assert hits and all(h["document_external_id"].startswith("OPS-") for h in hits)
        assert all("模拟" not in h["excerpt"] for h in hits)


def test_publish_is_versioned_idempotent_and_preserves_evidence(client, app, monkeypatch):
    project_id = register(client)["projects"][0]["id"]
    create_run(client, project_id)
    work_once(app.state.factory, app.state.settings)
    with app.state.factory() as db:
        project = db.get(Project, project_id)
        project.name = "我的演示医院 A"
        old = snapshot_for(db, project_id)
        original_facts = json.dumps(old.facts, sort_keys=True)
        original_docs = {d.id: (d.content, d.source_hash) for d in db.scalars(select(Document))}
        original_evidence = {e.id: e.body for e in db.scalars(select(Evidence))}
        original_analysis = {a.id: a.body for a in db.scalars(select(Analysis))}
        use_scenario(monkeypatch)
        result = publish(db)
        db.commit()
        assert result["snapshots_added"] == 1
        assert result["documents_added"] == 46
        assert project.name == "澄川医院 · SPD 项目"
        assert snapshot_for(db, project_id).id != old.id
        assert json.dumps(db.get(Snapshot, old.id).facts, sort_keys=True) == original_facts
        for doc_id, raw in original_docs.items():
            doc = db.get(Document, doc_id)
            assert (doc.content, doc.source_hash) == raw
        assert {e.id: e.body for e in db.scalars(select(Evidence))} == original_evidence
        assert {a.id: a.body for a in db.scalars(select(Analysis))} == original_analysis
        assert all(h["document_external_id"].startswith("OPS-") for h in search(db, project_id, "缺货"))
        second = publish(db)
        assert second["snapshots_added"] == second["documents_added"] == second["documents_retired"] == 0
        assert db.scalar(select(func.count()).select_from(Snapshot)) == 2


def test_default_provider_requires_real_key():
    settings = Settings(_env_file=None, csrf_secret="enterprise-test-secret-32-characters")
    assert settings.llm_provider == "deepseek"
    assert not settings.deepseek_api_key


def test_generated_data_retains_provenance_and_business_names():
    path = ROOT.parent / "data/scenario"
    products = json.loads((path / "products.json").read_text())
    assert len(products) == 24
    assert len({p["display_code"] for p in products}) == 24
    for p in products:
        assert p["synthetic"] is True
        assert not any(word in p["name"] + p["specification"] for word in ["模拟", "演示", "mock", "synthetic"])
        assert f"{p['units_per_purchase_pack']} {p['base_unit']}" in p["specification"]
    assert json.loads((path / "provenance.json").read_text())["real_company_data"] is False
