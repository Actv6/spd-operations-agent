from sqlalchemy import select, func
from app.models import Project, Document, Chunk
from app.knowledge import ingest, search
from app.errors import AppError
from conftest import register
import pytest


def test_ingest_scope_versions_offsets_and_no_match(client, app):
    project_id = register(client)["projects"][0]["id"]
    with app.state.factory() as db:
        project = db.get(Project, project_id)
        assert ingest(db, project) == 0
        docs = db.scalars(select(Document).where(Document.project_id == project_id)).all()
        assert len(docs) == 5
        assert all(d.external_id != "SIM-SOP-B-v1" for d in docs)
        hits = search(db, project_id, "缺货补货核查")
        assert hits and hits[0]["document_external_id"] == "SIM-SOP-REPL-v1"
        assert all(h["document_external_id"] != "SIM-SOP-REPL-v0" for h in hits)
        for hit in hits:
            doc = db.get(Document, hit["document_id"])
            assert doc.content[hit["start_offset"]:hit["end_offset"]] == hit["excerpt"]
        assert search(db, project_id, "量子宇宙星际飞船") == []
        assert search(db, "other-project", "补货") == []
        doc = next(d for d in docs if d.external_id == "SIM-SOP-REPL-v1")
        doc.effective_from = "2099-01-01"
        db.flush()
        assert not any(h["document_external_id"] == doc.external_id for h in search(db, project_id, "补货"))
        doc.effective_from = "2020-01-01"
        doc.effective_until = "2020-02-01"
        db.flush()
        assert not any(h["document_external_id"] == doc.external_id for h in search(db, project_id, "补货"))


def test_conflicting_versions_block_retrieval(client, app):
    project_id = register(client)["projects"][0]["id"]
    with app.state.factory() as db:
        old = db.scalar(select(Document).where(Document.project_id == project_id, Document.external_id == "SIM-SOP-REPL-v0"))
        old.status = "approved_demo"
        old.effective_until = None
        db.flush()
        with pytest.raises(AppError, match="重叠"):
            search(db, project_id, "补货")
