import argparse
import json
import secrets
from pathlib import Path
from .config import ROOT, Settings
from .db import make_engine, session_factory
from .models import Project
from .knowledge import ingest


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-config")
    sub.add_parser("publish-scenario")
    onsite = sub.add_parser("publish-onsite")
    onsite.add_argument("--project-id", action="append")
    sub.add_parser("db-summary")
    spec = sub.add_parser("openapi")
    spec.add_argument("output")
    imp = sub.add_parser("ingest")
    imp.add_argument("project_id")
    imp.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.command == "init-config":
        path = ROOT / ".env"
        with path.open("x") as file:
            file.write((ROOT / ".env.example").read_text().replace("replace-with-a-random-local-secret-at-least-32-characters", secrets.token_hex(32)))
        path.chmod(0o600)
        print("Created backend/.env (secret not printed)")
    elif args.command == "openapi":
        from .main import create_app
        Path(args.output).write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n")
    else:
        settings = Settings()
        factory = session_factory(make_engine(settings.database_url))
        with factory() as db:
            if args.command == "publish-onsite":
                from .onsite import publish
                result = publish(db, args.project_id)
                db.commit()
                print(json.dumps(result, ensure_ascii=False))
                return
            if args.command == "publish-scenario":
                from .scenario import publish
                result = publish(db)
                db.commit()
                print(json.dumps(result, ensure_ascii=False))
                return
            if args.command == "db-summary":
                from sqlalchemy import select, func
                from .models import Base
                tables = ["users", "organizations", "projects", "snapshots", "documents", "chunks", "agent_runs", "analyses", "evidence"]
                for name in tables:
                    print(f"{name}: {db.scalar(select(func.count()).select_from(Base.metadata.tables[name]))}")
                return
            project = db.get(Project, args.project_id)
            if not project:
                raise SystemExit("Unknown project")
            count = ingest(db, project, args.manifest)
            db.commit()
            print(f"Imported {count} versions (synthetic, lexical)")


if __name__ == "__main__":
    main()
