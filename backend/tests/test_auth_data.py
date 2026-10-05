import time
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.models import User, LoginSession, Snapshot, Membership
from app.auth import digest
from app.data import inventory
from conftest import register, ORIGIN


def test_registration_session_logout_and_hash(client, app):
    assert client.get("/api/v1/me").status_code == 401
    me = register(client)
    assert me["capabilities"] == ["read_synthetic", "run_analysis"]
    token = client.cookies["spd_session"]
    assert client.get("/api/v1/me").json() == me
    with app.state.factory() as db:
        assert db.get(User, me["user"]["id"]).password_hash.startswith("$argon2id$")
        assert db.get(LoginSession, digest(token)) is not None
        assert db.get(Membership, (me["user"]["id"], me["projects"][0]["id"])).role == "demo_owner"
    assert client.post("/api/v1/registrations", json={"email": "FIRST@example.test", "password": "safe-demo-password", "display_name": "repeat"}).status_code == 409
    assert client.delete("/api/v1/sessions/current").status_code == 204
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers={"Cookie": f"spd_session={token}"}).status_code == 401
    wrong = client.post("/api/v1/sessions", json={"email": "first@example.test", "password": "wrong-password"})
    assert wrong.status_code == 401
    response = client.post("/api/v1/sessions", json={"email": "first@example.test", "password": "safe-demo-password"})
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()
    assert client.cookies["spd_session"] != token
    with app.state.factory() as db:
        db.get(LoginSession, digest(client.cookies["spd_session"])).expires_at = time.time() - 1
        db.commit()
    assert client.get("/api/v1/me").status_code == 401


def test_csrf_and_validation_do_not_echo_password(client):
    body = {"email": "a@b.test", "password": "SECRET", "display_name": "test"}
    assert client.post("/api/v1/registrations", json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/v1/registrations", json=body, headers={"Origin": "https://evil.test"}).status_code == 403
    response = client.post("/api/v1/registrations", json=body)
    assert response.status_code == 422 and "SECRET" not in response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_rate_limit(client, app):
    app.state.settings.rate_limit = 2
    body = {"email": "missing@example.test", "password": "wrong-password"}
    assert client.post("/api/v1/sessions", json=body).status_code == 401
    assert client.post("/api/v1/sessions", json=body).status_code == 401
    response = client.post("/api/v1/sessions", json=body)
    assert response.status_code == 429 and response.headers["retry-after"] == "60"


def test_database_inventory_and_scope(client, app):
    me = register(client)
    project = me["projects"][0]["id"]
    dashboard = client.get(f"/api/v1/projects/{project}/dashboard").json()
    row = next(r for r in dashboard["inventory"] if r["item_id"] == "SIM-P001")
    assert row["available"] == "120" and row["daily_average"] == "20.0000" and row["coverage_days"] == "6.0000"
    missing = next(r for r in dashboard["inventory"] if r["item_id"] == "SIM-P006")
    assert missing["observed_days"] == 12 and missing["daily_average"] is None
    assert dashboard["stats"]["inventory_items"] > 0
    with TestClient(app) as other:
        other.headers.update({"Origin": ORIGIN, "X-CSRF-Token": other.get("/api/v1/csrf").json()["token"]})
        other_me = register(other, "other@example.test")
        assert other_me["projects"][0]["id"] != project
        for path in ["dashboard", "inventory", "knowledge/search?q=补货", "runs"]:
            assert other.get(f"/api/v1/projects/{project}/{path}").status_code == 404


def test_deterministic_inventory_excludes_unavailable(client, app):
    project = register(client)["projects"][0]["id"]
    with app.state.factory() as db:
        snapshot = db.scalar(select(Snapshot).where(Snapshot.project_id == project))
        import copy
        facts = copy.deepcopy(snapshot.facts)
        batches = [b for b in facts["inventory_batches"] if b["product_id"] == "SIM-P001"]
        batches[0]["frozen_base"] = 10
        batches[0]["reserved_base"] = 5
        batches[1]["expiry_date"] = "2026-09-26"
        batches[2]["status"] = "frozen"
        snapshot.facts = facts
        row = inventory(snapshot, ["SIM-P001"])[0]
        assert row["available"] == "25" and row["coverage_days"] == "1.2500"
        batches[0]["reserved_base"] = 100
        snapshot.facts = facts
        assert inventory(snapshot, ["SIM-P001"])[0]["available"] is None
