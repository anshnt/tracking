import base64

from portal.models import Workspace


def _ws(db, owner, name="ws", state="active", ref="7"):
    w = Workspace(
        owner_id=owner.id, name=name, role_profile="dev", lifecycle_state=state, connection_ref=ref
    )
    db.add(w)
    db.commit()
    return w


def test_only_own_workspaces_and_launch_url(db, make_employee, client_for, monkeypatch):
    monkeypatch.setenv("GUACAMOLE_URL", "https://gw.example.invalid/guacamole/")
    me, other = make_employee(), make_employee()
    mine = _ws(db, me, name="mine")
    _ws(db, other, name="theirs")
    _ws(db, me, name="gone", state="decommissioned")
    _ws(db, me, name="paused", state="suspended")
    rows = client_for(me).get("/api/v1/workspaces").json()["workspaces"]
    ws = {w["name"]: w for w in rows}
    assert set(ws) == {"mine", "paused"}
    url = ws["mine"]["launch_url"]
    assert url.startswith("https://gw.example.invalid/guacamole/#/client/")
    assert base64.b64decode(url.rsplit("/", 1)[1] + "==") == b"7\x00c\x00postgresql"
    assert ws["paused"]["launch_url"] is None
    assert "connection_ref" not in ws["mine"] and "password" not in str(ws).lower()
    assert str(mine.id) == ws["mine"]["id"]


def test_no_launch_url_without_config(db, make_employee, client_for, monkeypatch):
    monkeypatch.delenv("GUACAMOLE_URL", raising=False)
    me = make_employee()
    _ws(db, me)
    assert client_for(me).get("/api/v1/workspaces").json()["workspaces"][0]["launch_url"] is None


def test_substituting_other_employee_id(db, make_employee, client_for):
    mgr = make_employee(roles=["manager"])
    report, stranger = make_employee(manager=mgr), make_employee()
    _ws(db, report)
    c = client_for(mgr)
    got = c.get(f"/api/v1/workspaces?employee_id={report.id}").json()["workspaces"]
    assert len(got) == 1 and got[0]["launch_url"] is None  # managers never get the report's link
    assert c.get(f"/api/v1/workspaces?employee_id={stranger.id}").status_code == 404
    other = client_for(report).get(f"/api/v1/workspaces?employee_id={stranger.id}")
    assert other.status_code == 404


def test_workspace_posture_from_linked_asset(db, make_employee, client_for):
    from datetime import UTC, datetime, timedelta

    from portal.models import Asset, PostureObservation

    me = make_employee()
    asset = Asset(name="vm", ownership="company")
    db.add(asset)
    db.commit()
    linked, bare = _ws(db, me, name="linked"), _ws(db, me, name="bare")
    linked.asset_id = asset.id
    now = datetime.now(UTC)
    db.add(
        PostureObservation(
            asset_id=asset.id,
            source="t",
            observed_at=now,
            expires_at=now + timedelta(minutes=15),
            state="noncompliant",
            checks={"disk_encrypted": {"passed": False, "detail": "off"}},
        )
    )
    db.commit()
    ws = {w["name"]: w for w in client_for(me).get("/api/v1/workspaces").json()["workspaces"]}
    assert ws["linked"]["posture"]["state"] == "noncompliant"
    assert ws["linked"]["posture"]["failing_checks"] == [
        {"check": "disk_encrypted", "detail": "off"}
    ]
    assert ws["linked"]["posture"]["observed_at"]
    assert ws["bare"]["posture"]["state"] == "unknown"
    assert bare.asset_id is None
    mgr = make_employee(roles=["manager"])
    me.manager_id = mgr.id
    db.commit()
    person = client_for(mgr).get("/api/v1/overview").json()["people"][0]
    assert {w["name"]: w["posture"]["state"] for w in person["workspaces"]} == {
        "linked": "noncompliant",
        "bare": "unknown",
    }
