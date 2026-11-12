from datetime import UTC, datetime, timedelta

from portal.models import (
    Asset,
    ExportRequest,
    PolicyAssignment,
    PolicyVersion,
    PostureObservation,
    SecurityEvent,
    TaskSnapshot,
    WorkUpdate,
)


def _policy(db, text="Notice v1", scope=("all", None), **assign):
    n = db.query(PolicyVersion).count() + 1
    v = PolicyVersion(
        name="collection-policy",
        version=n,
        content={"notice_text": text, "contact": "it@x"},
        content_hash=f"h{n}",
    )
    db.add(v)
    db.flush()
    db.add(
        PolicyAssignment(policy_version_id=v.id, scope_type=scope[0], scope_id=scope[1], **assign)
    )
    db.commit()
    return v


def test_me(make_employee, client_for):
    e = make_employee()
    assert client_for(e).get("/api/v1/me").json()["id"] == str(e.id)


def test_collection_policy_and_ack(db, make_employee, client_for):
    e = make_employee()
    c = client_for(e)
    r = c.get("/api/v1/me/collection-policy").json()
    assert r["policy"] is None
    by_signal = {x["signal"]: x["default"] for x in r["categories"]}
    assert by_signal["Window titles, full URLs, clipboard text"] == "off"
    assert by_signal["Screenshots and full session recordings"] == "off"
    assert by_signal["Keystrokes, passwords, personal browsing, camera, audio"] == "excluded"
    v = _policy(db)
    r = c.get("/api/v1/me/collection-policy").json()
    assert r["policy"]["version"] == 1 and r["policy"]["notice_text"] == "Notice v1"
    assert r["policy"]["contact"] == "it@x" and r["policy"]["acknowledged_at"] is None
    body = {"policy_version_id": str(v.id)}
    assert c.post("/api/v1/me/notice-acknowledgements", json=body).status_code == 201
    assert c.post("/api/v1/me/notice-acknowledgements", json=body).status_code == 201
    assert c.get("/api/v1/me/collection-policy").json()["policy"]["acknowledged_at"]
    assert len(c.get("/api/v1/me/records").json()["notice_acknowledgements"]) == 1  # idempotent


def test_cannot_ack_future_policy(db, make_employee, client_for):
    e = make_employee()
    _policy(db)
    future = _policy(db, "v2", activates_at=datetime.now(UTC) + timedelta(days=1))
    r = client_for(e).post(
        "/api/v1/me/notice-acknowledgements", json={"policy_version_id": str(future.id)}
    )
    assert r.status_code == 409


def test_employee_scoped_policy_wins(db, make_employee, client_for):
    a, b = make_employee(), make_employee()
    _policy(db, "all")
    _policy(db, "just a", scope=("employee", a.id))
    got = client_for(a).get("/api/v1/me/collection-policy").json()["policy"]["notice_text"]
    assert got == "just a"
    got = client_for(b).get("/api/v1/me/collection-policy").json()["policy"]["notice_text"]
    assert got == "all"


def test_records_are_own_only(db, make_employee, client_for):
    me, other = make_employee(), make_employee()
    now = datetime.now(UTC)
    mine = Asset(name="mine", ownership="company", assigned_employee_id=me.id)
    theirs = Asset(name="theirs", ownership="company", assigned_employee_id=other.id)
    byod = Asset(name="byod", ownership="personal", assigned_employee_id=me.id)
    db.add_all([mine, theirs, byod])
    db.flush()
    for a in (mine, theirs, byod):
        db.add(
            PostureObservation(
                asset_id=a.id,
                source="t",
                observed_at=now,
                expires_at=now + timedelta(minutes=15),
                state="compliant",
            )
        )
    for who, n in ((me, "mine"), (other, "theirs")):
        db.add(WorkUpdate(employee_id=who.id, update_date=now.date(), summary=n))
        db.add(
            ExportRequest(
                requester_id=who.id,
                object_ref=n,
                classification="internal",
                recipient="r",
                purpose="p",
            )
        )
        db.add(
            SecurityEvent(
                source="s",
                source_event_id=n,
                employee_id=who.id,
                event_type="login",
                occurred_at=now,
                event_metadata={"secret": n},
            )
        )
    db.commit()
    r = client_for(me).get("/api/v1/me/records").json()
    assert [u["summary"] for u in r["work_updates"]] == ["mine"]
    assert [x["object_ref"] for x in r["export_requests"]] == ["mine"]
    assert len(r["security_event_summaries"]) == 1
    assert "secret" not in str(r)  # event metadata is never returned
    assert [o["asset_id"] for o in r["posture_observations"]] == [str(mine.id)]


def test_my_tasks(db, make_employee, client_for):
    me, other = make_employee(), make_employee()
    db.add_all(
        [
            TaskSnapshot(source="g", source_ref="1", assignee_id=me.id, title="mine"),
            TaskSnapshot(source="g", source_ref="2", assignee_id=other.id, title="theirs"),
            TaskSnapshot(source="g", source_ref="3", assignee_id=me.id, title="d", state="done"),
        ]
    )
    db.commit()
    tasks = client_for(me).get("/api/v1/me/tasks").json()["tasks"]
    assert [t["title"] for t in tasks] == ["mine"]


def test_categories_come_from_the_policy_version_in_force(db, make_employee, client_for):
    cats = [{"signal": "Only this", "default": "on", "visible_to": "you"}]
    n = db.query(PolicyVersion).count() + 1
    v = PolicyVersion(
        name="collection-policy",
        version=n,
        content={"notice_text": "n", "categories": cats},
        content_hash="hc",
    )
    db.add(v)
    db.flush()
    db.add(PolicyAssignment(policy_version_id=v.id, scope_type="all"))
    db.commit()
    got = client_for(make_employee()).get("/api/v1/me/collection-policy").json()
    assert got["categories"] == cats


def test_double_ack_is_idempotent_with_one_audit_row(db, make_employee, client_for):
    from sqlalchemy import select

    from portal.models import AuditEvent, NoticeAcknowledgement

    e = make_employee()
    v = _policy(db)
    db.add(NoticeAcknowledgement(employee_id=e.id, policy_version_id=v.id))
    db.commit()
    body = {"policy_version_id": str(v.id)}
    c = client_for(e)
    assert c.post("/api/v1/me/notice-acknowledgements", json=body).status_code == 201
    assert c.post("/api/v1/me/notice-acknowledgements", json=body).status_code == 201
    assert len(db.scalars(select(NoticeAcknowledgement)).all()) == 1
    assert (
        db.scalars(select(AuditEvent).where(AuditEvent.action == "notice.acknowledge")).all() == []
    )
