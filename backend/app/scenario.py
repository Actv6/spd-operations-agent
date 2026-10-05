"""Publish generated scenario versions without overwriting historical facts."""
from sqlalchemy import select, func
from .data import seed_snapshot, snapshot_for
from .catalog import lock_project
from .versions import activate
from .knowledge import ingest
from .models import Project, Organization, Document, Snapshot


def publish(db):
    counts = {"projects": 0, "snapshots_added": 0, "documents_added": 0, "documents_retired": 0}
    for project in db.scalars(select(Project).where(Project.synthetic.is_(True))):
        lock_project(db, project.id)
        previous = snapshot_for(db, project.id).id
        before = db.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.project_id == project.id))
        snapshot = seed_snapshot(db, project)
        after = db.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.project_id == project.id))
        if after > before:
            activate(db, project.id, snapshot.id, previous, "scenario", reason="场景数据版本发布")
        counts["snapshots_added"] += after - before
        counts["documents_added"] += ingest(db, project)
        for doc in db.scalars(select(Document).where(Document.project_id == project.id, Document.external_id.like("SIM-%"), Document.status == "approved_demo")):
            doc.status = "retired_demo"
            counts["documents_retired"] += 1
        if project.name == "我的演示医院 A":
            project.name = "澄川医院 · SPD 项目"
        organization = db.get(Organization, project.org_id)
        if organization.name.endswith("的演示组织"):
            organization.name = organization.name.removesuffix("的演示组织") + "的工作空间"
        counts["projects"] += 1
    db.flush()
    return counts
