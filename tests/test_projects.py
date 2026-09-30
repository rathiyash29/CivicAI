"""
Tests for the officer decision workflow: recommendation -> project, and the
decision ledger.

The workflow is the part of CivicAI that records what a government officer
actually decided, so the tests focus on the things that would be expensive to
get wrong: a decision that does not survive a refresh, a rejection that quietly
becomes a project, an approval that happens twice, and a status jump that skips
the work in between.
"""
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import projects as service
from backend import projects_router as PR
from backend import recommendations as rec_service
from backend import impact as impact_service
from database import models


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def app():
    application = FastAPI()
    application.include_router(PR.router)
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def officer_headers(make_auth_user):
    def _headers(email="officer@example.com"):
        _user, token = make_auth_user(email, role="officer", name="Officer One")
        return {"Authorization": f"Bearer {token}"}
    return _headers


@pytest.fixture
def citizen_headers(make_auth_user):
    def _headers(email="citizen@example.com"):
        _user, token = make_auth_user(email, role="citizen", name="Citizen One")
        return {"Authorization": f"Bearer {token}"}
    return _headers


def _cluster_with_complaints(db, ward="Kothrud", category="Road Infrastructure", n=3):
    """A populated cluster plus its recommendation, exactly as the engine leaves them."""
    loc = db.query(models.Location).filter_by(ward=ward).first()
    if loc is None:
        loc = models.Location(ward=ward, city="Pune")
        db.add(loc)
        db.flush()

    cluster = models.IssueCluster(label=f"{category} - {ward}", category=category, ward=ward)
    db.add(cluster)
    db.flush()

    for index in range(n):
        db.add(models.Complaint(
            text=f"complaint {index}", category=category, severity="High",
            urgency="High", location_id=loc.id, cluster_id=cluster.id,
            priority_score=70.0,
        ))
    db.flush()
    db.commit()

    rec = rec_service.generate_recommendation(db, cluster)
    return cluster, db.query(models.Recommendation).filter_by(id=rec["cluster_id"]).one()


def _empty_cluster_recommendation(db, ward="Baner", category="Education"):
    """A recommendation whose cluster has no complaints left."""
    cluster = models.IssueCluster(label=f"stale {category}", category=category, ward=ward)
    db.add(cluster)
    db.flush()
    rec = rec_service.upsert_recommendation(
        db, cluster, action="Old plan", reason="old", evidence={},
        priority_score=10.0, estimated_affected_population=None,
    )
    db.commit()
    return cluster, rec


# --------------------------------------------------------------------------
# authorization
# --------------------------------------------------------------------------

def test_anonymous_cannot_decide(client):
    assert client.post("/projects/recommendations/1/approve", json={}).status_code == 401
    assert client.post("/projects/recommendations/1/reject",
                        json={"reason": "no"}).status_code == 401
    assert client.get("/projects").status_code == 401


def test_cannot_be_officer_but_officer_can(client, clean_db, citizen_headers, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id

    assert client.post(f"/projects/recommendations/{rec_id}/approve",
                       json={}, headers=citizen_headers()).status_code == 403
    assert client.post(f"/projects/recommendations/{rec_id}/reject",
                       json={"reason": "no"}, headers=citizen_headers()).status_code == 403
    assert client.get("/projects", headers=citizen_headers()).status_code == 403
    assert client.post(f"/projects/recommendations/{rec_id}/approve",
                       json={}, headers=officer_headers()).status_code == 200


# --------------------------------------------------------------------------
# approve
# --------------------------------------------------------------------------

def test_approve_creates_a_linked_project(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id

    r = client.post(f"/projects/recommendations/{rec_id}/approve", json={},
                    headers=officer_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["project"]["recommendation_id"] == rec_id
    assert body["project"]["status"] == "Approved"
    assert body["project"]["title"] == "Road rehabilitation"
    assert body["decision"]["decision"] == "Approved"


def test_approve_records_the_officer_without_storing_a_credential(
    client, clean_db, officer_headers
):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id

    body = client.post(f"/projects/recommendations/{rec_id}/approve", json={},
                       headers=officer_headers()).json()

    officer = body["decision"]["officer"]
    assert officer and officer["id"] > 0
    assert officer["email"] == "officer@example.com"

    project = clean_db.query(models.Project).one()
    assert project.officer_id == officer["id"]

    # Nothing on the users row is a usable credential. `password_hash` does
    # exist now -- auth is database-backed -- so this asserts what it actually
    # must be: a bcrypt digest, never a plaintext password, and never a token.
    # The API response must not carry it either.
    user = clean_db.query(models.User).filter_by(id=project.officer_id).one()
    assert user.password_hash is not None
    assert user.password_hash.startswith("$2")
    assert "password123" not in user.password_hash
    assert not hasattr(user, "password")
    assert not hasattr(user, "token")
    assert "password_hash" not in officer
    assert not any("password" in key for key in officer)


def test_approve_accepts_an_officer_title_override(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id

    body = client.post(
        f"/projects/recommendations/{rec_id}/approve",
        json={"title": "Pothole repair phase 1", "description": "Ward-wide resurfacing",
              "reason": "Budget approved for Q3"},
        headers=officer_headers(),
    ).json()

    assert body["project"]["title"] == "Pothole repair phase 1"
    assert body["project"]["description"] == "Ward-wide resurfacing"
    assert body["decision"]["reason"] == "Budget approved for Q3"


def test_second_approval_is_a_conflict_not_a_second_project(
    client, clean_db, officer_headers
):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()

    assert client.post(f"/projects/recommendations/{rec_id}/approve", json={},
                       headers=headers).status_code == 200
    second = client.post(f"/projects/recommendations/{rec_id}/approve", json={},
                         headers=headers)

    assert second.status_code == 409
    assert "already has project" in second.json()["detail"]
    assert clean_db.query(models.Project).count() == 1, \
        "a repeated approval must not create a second project"


# --------------------------------------------------------------------------
# modify
# --------------------------------------------------------------------------

def test_modify_creates_a_project_under_review(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id

    body = client.post(
        f"/projects/recommendations/{rec_id}/modify",
        json={"title": "Targeted pothole patching", "description": "Phase 1 only",
              "reason": "Full rehabilitation exceeds the budget"},
        headers=officer_headers(),
    ).json()

    assert body["project"]["title"] == "Targeted pothole patching"
    assert body["project"]["status"] == "Under Review"
    assert body["decision"]["decision"] == "Modified"


def test_modify_never_overwrites_the_recommendation(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec = clean_db.query(models.Recommendation).one()
    rec_id, original_action, original_reason = rec.id, rec.action, rec.reason

    client.post(f"/projects/recommendations/{rec_id}/modify",
                json={"title": "A completely different plan", "reason": "budget"},
                headers=officer_headers())

    rec = clean_db.query(models.Recommendation).filter_by(id=rec_id).one()
    assert rec.action == original_action == "Road rehabilitation"
    assert rec.reason == original_reason


def test_second_modify_updates_the_same_project(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()

    client.post(f"/projects/recommendations/{rec_id}/modify",
                json={"title": "Plan v1"}, headers=headers)
    client.post(f"/projects/recommendations/{rec_id}/modify",
                json={"title": "Plan v2"}, headers=headers)

    projects = clean_db.query(models.Project).all()
    assert len(projects) == 1
    assert projects[0].title == "Plan v2"
    assert clean_db.query(models.OfficerDecision).filter_by(
        decision="Modified").count() == 2, "both modifications are in the ledger"


def test_modify_requires_a_title(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id

    assert client.post(f"/projects/recommendations/{rec_id}/modify", json={"title": ""},
                       headers=officer_headers()).status_code == 422
    assert client.post(f"/projects/recommendations/{rec_id}/modify", json={},
                       headers=officer_headers()).status_code == 422


# --------------------------------------------------------------------------
# the id the decision endpoints are keyed on
# --------------------------------------------------------------------------

def test_approve_with_an_empty_body_succeeds(client, clean_db, officer_headers):
    """
    "Approve as proposed" is the normal path and sends no fields. Every field of
    `ApproveRequest` is optional, so an empty object is valid and must not be
    what produces a 422.
    """
    _cluster_with_complaints(clean_db)
    row = clean_db.query(models.Recommendation).one()
    r = client.post(f"/projects/recommendations/{row.id}/approve", json={},
                    headers=officer_headers())
    assert r.status_code == 200, r.text
    assert r.json()["project"] is not None


def test_decision_routes_reject_a_non_integer_id(client, clean_db, officer_headers):
    """
    The 422 the dashboard showed. `{recommendation_id}` is declared `int`, so a
    non-numeric path segment is a malformed request and is refused before the
    service runs.

    This validation is correct and must stay: it is the backend half of the fix.
    The client half is refusing to build such a request, not this route
    accepting one.
    """
    _cluster_with_complaints(clean_db)
    headers = officer_headers()
    for action, body in (("approve", {}),
                         ("modify", {"title": "A revised plan"}),
                         ("reject", {"reason": "Not this cycle"})):
        r = client.post(f"/projects/recommendations/undefined/{action}", json=body,
                        headers=headers)
        assert r.status_code == 422, f"{action} should refuse a non-integer id"
        assert any("recommendation_id" in str(err.get("loc", ""))
                   for err in r.json()["detail"])
    assert clean_db.query(models.OfficerDecision).count() == 0
    assert clean_db.query(models.Project).count() == 0


# --------------------------------------------------------------------------
# reject
# --------------------------------------------------------------------------

def test_reject_records_a_reason_and_creates_no_project(
    client, clean_db, officer_headers
):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id

    r = client.post(f"/projects/recommendations/{rec_id}/reject",
                    json={"reason": "Covered by the ongoing AMC contract"},
                    headers=officer_headers())

    assert r.status_code == 200
    assert r.json()["decision"] == "Rejected"
    assert r.json()["reason"] == "Covered by the ongoing AMC contract"
    assert r.json()["project_id"] is None
    assert clean_db.query(models.Project).count() == 0, \
        "a rejected recommendation must never produce a project"


def test_reject_requires_a_reason(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()

    # A missing field is a malformed request (422); whitespace passes schema
    # validation but is caught by the service, which refuses to record a
    # rejection with no stated reason (400).
    assert client.post(f"/projects/recommendations/{rec_id}/reject", json={},
                       headers=headers).status_code == 422
    blank = client.post(f"/projects/recommendations/{rec_id}/reject", json={"reason": "   "},
                        headers=headers)
    assert blank.status_code == 400
    assert "reason is required" in blank.json()["detail"]
    assert clean_db.query(models.OfficerDecision).count() == 0


def test_reject_conflicts_with_an_existing_project(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()
    client.post(f"/projects/recommendations/{rec_id}/approve", json={}, headers=headers)

    r = client.post(f"/projects/recommendations/{rec_id}/reject",
                    json={"reason": "changed my mind"}, headers=headers)
    assert r.status_code == 409
    assert clean_db.query(models.Project).count() == 1


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def test_unknown_recommendation_is_404(client, clean_db, officer_headers):
    headers = officer_headers()
    assert client.post("/projects/recommendations/9999/approve", json={},
                       headers=headers).status_code == 404
    assert client.post("/projects/recommendations/9999/reject", json={"reason": "x"},
                       headers=headers).status_code == 404
    assert client.get("/decisions/recommendation/9999", headers=headers).status_code == 404


def test_recommendation_with_no_complaints_cannot_be_decided(
    client, clean_db, officer_headers
):
    """An empty cluster has no evidence behind it, even if a row survives."""
    _cluster_with_complaints(clean_db)
    _empty_cluster_recommendation(clean_db)
    stale = clean_db.query(models.Recommendation).filter_by(action="Old plan").one()
    headers = officer_headers()

    r = client.post(f"/projects/recommendations/{stale.id}/approve", json={},
                    headers=headers)
    assert r.status_code == 409
    assert "no related complaints" in r.json()["detail"]
    assert clean_db.query(models.Project).count() == 0


# --------------------------------------------------------------------------
# status progression
# --------------------------------------------------------------------------

def test_status_advances_one_step_at_a_time(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()
    project_id = client.post(f"/projects/recommendations/{rec_id}/approve", json={},
                             headers=headers).json()["project"]["id"]

    assert client.get(f"/projects/{project_id}",
                      headers=headers).json()["status"] == "Approved"

    moved = client.patch(f"/projects/{project_id}/status", json={"status": "In Progress"},
                         headers=headers)
    assert moved.status_code == 200
    assert moved.json()["project"]["status"] == "In Progress"

    done = client.patch(f"/projects/{project_id}/status", json={"status": "Completed"},
                        headers=headers)
    assert done.status_code == 200
    assert done.json()["project"]["status"] == "Completed"


def test_status_cannot_skip_or_go_backwards(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()
    project_id = client.post(f"/projects/recommendations/{rec_id}/approve", json={},
                             headers=headers).json()["project"]["id"]

    skip = client.patch(f"/projects/{project_id}/status", json={"status": "Completed"},
                        headers=headers)
    assert skip.status_code == 409
    assert "next step is 'In Progress'" in skip.json()["detail"]

    client.patch(f"/projects/{project_id}/status", json={"status": "In Progress"},
                 headers=headers)
    back = client.patch(f"/projects/{project_id}/status", json={"status": "Approved"},
                        headers=headers)
    assert back.status_code == 409

    assert client.get(f"/projects/{project_id}", headers=headers).json()["status"] == "In Progress"


def test_status_rejects_an_unknown_value(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()
    project_id = client.post(f"/projects/recommendations/{rec_id}/approve", json={},
                             headers=headers).json()["project"]["id"]

    r = client.patch(f"/projects/{project_id}/status", json={"status": "Cancelled"},
                     headers=headers)
    assert r.status_code == 400
    assert clean_db.query(models.Project).filter_by(id=project_id).one().status == "Approved"


def test_completed_project_cannot_be_modified(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()
    client.post(f"/projects/recommendations/{rec_id}/approve", json={}, headers=headers)
    client.post(f"/projects/recommendations/{rec_id}/modify", json={"title": "revise"},
                headers=headers)
    project_id = clean_db.query(models.Project).one().id
    client.patch(f"/projects/{project_id}/status", json={"status": "In Progress"},
                 headers=headers)
    client.patch(f"/projects/{project_id}/status", json={"status": "Completed"},
                 headers=headers)

    r = client.post(f"/projects/recommendations/{rec_id}/modify", json={"title": "too late"},
                    headers=headers)
    assert r.status_code == 409


def test_status_change_needs_officer_auth(client, clean_db, citizen_headers,
                                          make_auth_user):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    # Approve as an officer first. The account is provisioned through the auth
    # service rather than POST /auth/register, which creates citizens only.
    _officer, officer_token = make_auth_user("status.officer@example.com", role="officer")
    client.post(f"/projects/recommendations/{rec_id}/approve", json={},
                headers={"Authorization": f"Bearer {officer_token}"})
    project_id = clean_db.query(models.Project).one().id

    assert client.patch(f"/projects/{project_id}/status", json={"status": "In Progress"},
                        headers=citizen_headers()).status_code == 403


# --------------------------------------------------------------------------
# read side
# --------------------------------------------------------------------------

def test_decision_history_is_readable(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()
    client.post(f"/projects/recommendations/{rec_id}/approve", json={}, headers=headers)
    client.post(f"/projects/recommendations/{rec_id}/modify", json={"title": "revised"},
                headers=headers)

    history = client.get(f"/decisions/recommendation/{rec_id}", headers=headers)
    assert history.status_code == 200
    decisions = history.json()
    assert [d["decision"] for d in decisions] == ["Approved", "Modified"]


def test_projects_list_carries_recommendation_context(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db, n=4)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()
    client.post(f"/projects/recommendations/{rec_id}/approve", json={}, headers=headers)

    projects = client.get("/projects", headers=headers).json()
    assert len(projects) == 1
    project = projects[0]
    assert project["action"] == "Road rehabilitation"
    assert project["location"] == "Kothrud"
    assert project["related_complaints"] == 4
    assert project["priority_level"] == "High"
    assert project["officer"]["email"] == "officer@example.com"


def test_project_detail_includes_its_decisions(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()
    project_id = client.post(f"/projects/recommendations/{rec_id}/approve", json={},
                             headers=headers).json()["project"]["id"]
    client.patch(f"/projects/{project_id}/status", json={"status": "In Progress"},
                 headers=headers)

    detail = client.get(f"/projects/{project_id}", headers=headers).json()
    assert [d["decision"] for d in detail["decisions"]] == ["Approved", "Status Changed"]


def test_read_endpoints_do_not_leak_credentials(client, clean_db, officer_headers):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    headers = officer_headers()
    client.post(f"/projects/recommendations/{rec_id}/approve", json={}, headers=headers)

    raw = client.get("/projects", headers=headers).text.lower()
    for secret in ("password", "password_hash", "access_token", "secret", "bearer "):
        assert secret not in raw, f"{secret!r} must not appear in the projects payload"


def test_unknown_project_is_404(client, clean_db, officer_headers):
    assert client.get("/projects/9999", headers=officer_headers()).status_code == 404
    assert client.patch("/projects/9999/status", json={"status": "In Progress"},
                        headers=officer_headers()).status_code == 404


# --------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------

def test_decision_survives_a_new_session(clean_db, make_auth_user, officer_headers):
    """A second session must see the decision: this is the refresh-survival rule."""
    from database.db import SessionLocal

    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    make_auth_user("officer@example.com", role="officer", name="Officer One")

    officer = PR.UserResponse(id=1, full_name="Officer One",
                              email="officer@example.com", role="officer",
                              created_at=datetime.utcnow())
    project, decision = service.approve(clean_db, rec_id, officer)

    fresh = SessionLocal()
    try:
        stored_project = fresh.query(models.Project).filter_by(id=project.id).one()
        assert stored_project.status == "Approved"
        assert stored_project.recommendation_id == rec_id
        stored_decision = fresh.query(models.OfficerDecision).filter_by(id=decision.id).one()
        assert stored_decision.decision == "Approved"
        assert stored_decision.action_snapshot == "Road rehabilitation"
    finally:
        fresh.close()


def test_rejection_survives_a_new_session(clean_db):
    from database.db import SessionLocal

    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    officer = PR.UserResponse(id=1, full_name="Officer One",
                              email="officer@example.com", role="officer",
                              created_at=datetime.utcnow())
    service.reject(clean_db, rec_id, officer, "Not a civic priority this quarter")

    fresh = SessionLocal()
    try:
        entry = fresh.query(models.OfficerDecision).filter_by(recommendation_id=rec_id).one()
        assert entry.decision == "Rejected"
        assert entry.reason == "Not a civic priority this quarter"
        assert fresh.query(models.Project).count() == 0
    finally:
        fresh.close()


# --------------------------------------------------------------------------
# regeneration safety
# --------------------------------------------------------------------------

def test_regeneration_preserves_an_approved_decision(clean_db, make_auth_user):
    """The engine refreshing a recommendation must not undo an officer decision."""
    _cluster_with_complaints(clean_db)
    rec = clean_db.query(models.Recommendation).one()
    rec_id = rec.id
    make_auth_user("officer@example.com", role="officer")
    officer = PR.UserResponse(id=1, full_name="Officer One",
                              email="officer@example.com", role="officer",
                              created_at=datetime.utcnow())
    project, _decision = service.approve(clean_db, rec_id, officer)

    # The dashboard's read path regenerates every recommendation in place.
    rec_service.generate_all(clean_db)

    assert clean_db.query(models.Recommendation).filter_by(id=rec_id).one(), \
        "the recommendation row must survive so the project FK stays valid"
    assert clean_db.query(models.Project).filter_by(id=project.id).one().status == "Approved"
    assert clean_db.query(models.OfficerDecision).filter_by(
        recommendation_id=rec_id, decision="Approved").count() == 1


def test_regeneration_preserves_a_rejection(clean_db):
    _cluster_with_complaints(clean_db)
    rec_id = clean_db.query(models.Recommendation).one().id
    officer = PR.UserResponse(id=1, full_name="Officer One",
                              email="officer@example.com", role="officer",
                              created_at=datetime.utcnow())
    service.reject(clean_db, rec_id, officer, "Already funded elsewhere")

    rec_service.generate_all(clean_db)

    entries = clean_db.query(models.OfficerDecision).filter_by(
        recommendation_id=rec_id, decision="Rejected").all()
    assert len(entries) == 1
    assert entries[0].reason == "Already funded elsewhere"


def test_regeneration_does_not_delete_a_decided_recommendation(clean_db):
    """
    A cluster can empty out after a decision. The stale-cleanup path must keep a
    recommendation that a project or decision points at, or the FK breaks.
    """
    _cluster_with_complaints(clean_db)
    cluster, rec = _empty_cluster_recommendation(clean_db)
    officer = PR.UserResponse(id=1, full_name="Officer One",
                              email="officer@example.com", role="officer",
                              created_at=datetime.utcnow())
    # Attach a decision to the stale recommendation.
    clean_db.add(models.OfficerDecision(recommendation_id=rec.id, officer_id=None,
                                        decision="Approved", reason=None))
    clean_db.commit()

    rec_service.generate_all(clean_db)

    assert clean_db.query(models.Recommendation).filter_by(id=rec.id).one() is not None, \
        "a recommendation with decision history must not be deleted"


def test_regeneration_still_removes_an_undecided_stale_recommendation(clean_db):
    """The cleanup path keeps working where nothing points at the row."""
    _cluster_with_complaints(clean_db)
    _cluster, rec = _empty_cluster_recommendation(clean_db)

    rec_service.generate_all(clean_db)

    assert clean_db.query(models.Recommendation).filter_by(id=rec.id).first() is None


# --------------------------------------------------------------------------
# GET /impact -- the measured/unmeasured distinction
# --------------------------------------------------------------------------

def _completed_project(db, ward="Kothrud", category="Road Infrastructure"):
    """A project walked all the way to Completed, which is the only state an
    impact record is legal in."""
    _cluster_with_complaints(db, ward=ward, category=category)
    # The newest recommendation is the one just generated, not whichever row
    # happens to be first once a second project exists in the same database.
    rec = db.query(models.Recommendation).order_by(models.Recommendation.id.desc()).first()
    officer = PR.UserResponse(id=1, full_name="Officer One",
                              email="officer@example.com", role="officer",
                              created_at=datetime.utcnow())
    project, _ = service.approve(db, rec.id, officer)
    for next_step in ("In Progress", "Completed"):
        project, _ = service.set_status(db, project.id, officer, new_status=next_step)
    db.commit()
    return project


def test_impact_listing_is_empty_when_nothing_is_measured(client, clean_db, officer_headers):
    _completed_project(clean_db)
    body = client.get("/impact", headers=officer_headers()).json()
    assert body["impacts"] == []
    assert body["measured_project_ids"] == []


def test_impact_listing_reports_only_projects_that_were_measured(
        client, clean_db, officer_headers):
    """
    The Impact page previously hardcoded "awaiting measurement" for every
    completed project. The listing is what lets it tell the two apart, so a
    measured project must appear and an unmeasured one must not.
    """
    measured = _completed_project(clean_db)
    unmeasured = _completed_project(clean_db, ward="Baner", category="Water Supply")
    assert measured.id != unmeasured.id

    impact_service.record_impact(
        clean_db, measured.id, PR.UserResponse(
            id=1, full_name="Officer One", email="officer@example.com",
            role="officer", created_at=datetime.utcnow()),
        before_complaint_count=5, after_complaint_count=2, complaints_resolved=3,
    )

    body = client.get("/impact", headers=officer_headers()).json()
    assert body["measured_project_ids"] == [measured.id]
    assert unmeasured.id not in body["measured_project_ids"]
    assert len(body["impacts"]) == 1
    assert body["impacts"][0]["project_id"] == measured.id


def test_impact_listing_carries_the_observed_change(client, clean_db, officer_headers):
    """The card shows observed changes, which are computed on read."""
    project = _completed_project(clean_db)
    impact_service.record_impact(
        clean_db, project.id, PR.UserResponse(
            id=1, full_name="Officer One", email="officer@example.com",
            role="officer", created_at=datetime.utcnow()),
        before_complaint_count=5, after_complaint_count=2, complaints_resolved=3,
    )
    impact = client.get("/impact", headers=officer_headers()).json()["impacts"][0]
    assert impact["observed_change"]["complaint_change"] == -3


def test_impact_listing_is_officer_only(client, clean_db, citizen_headers):
    assert client.get("/impact", headers=citizen_headers()).status_code == 403
    assert client.get("/impact").status_code == 401
