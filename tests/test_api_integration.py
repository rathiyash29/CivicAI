"""
End-to-end tests for the FastAPI app.

Two things are protected here and both are easy to break accidentally:

  1. the frontend response contract for POST /complaints and /complaints/my
  2. the pre-existing endpoints (/hotspots, /auth/*) that Member 1 owns
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Force SQLite before any application module is imported.
import tempfile
_TMP = os.path.join(tempfile.gettempdir(), "civicai_api_tests.db")
if os.path.exists(_TMP):
    os.remove(_TMP)
os.environ["DATABASE_URL"] = "sqlite:///" + _TMP.replace(os.sep, "/")
os.environ["ENABLE_BIGQUERY_SYNC"] = "false"

from backend import complaint_service as svc  # noqa: E402
from backend import main  # noqa: E402
from database import models  # noqa: E402

# The original eleven fields the citizen frontend binds to. The `analysis_*`
# and `cluster_id` fields below are additive: the officer dashboard needs them
# and the citizen UI ignores them, so both contracts are served by one shape.
FRONTEND_COMPLAINT_FIELDS = {
    "complaint_id", "user_id", "text", "language", "location", "category",
    "severity", "priority_score", "priority_level", "status", "created_at",
    "cluster_id", "analysis_urgency", "analysis_affected_group",
    "analysis_issue_summary", "analysis_recommended_action",
}


@pytest.fixture
def client():
    svc.reset_health_cache()
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def citizen(client):
    """A registered + logged-in citizen."""
    email = "citizen@example.com"
    client.post("/auth/register", json={
        "full_name": "Asha Verma", "email": email, "password": "password123"})
    token = client.post("/auth/login",
                        json={"email": email, "password": "password123"}).json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "email": email}


@pytest.fixture
def seeded_ward(client):
    loc = models.Location(ward="Kothrud", city="Pune")
    client.app  # keep reference
    return loc


def _seed_reference_data():
    from database.db import SessionLocal
    s = SessionLocal()
    try:
        for ward in ("Kothrud", "Baner"):
            if not s.query(models.Location).filter_by(ward=ward).first():
                s.add(models.Location(ward=ward, city="Pune"))
        for ward, pop in (("Kothrud", 118_000), ("Baner", 187_000)):
            loc = s.query(models.Location).filter_by(ward=ward).first()
            if loc and not s.query(models.Demographics).filter_by(location_id=loc.id).first():
                s.add(models.Demographics(location_id=loc.id, population=pop,
                                          source="test"))
        s.commit()
    finally:
        s.close()


# --- 1. persistence through the API ----------------------------------------

def test_complaint_is_stored_in_the_database(client, citizen):
    _seed_reference_data()
    r = client.post("/complaints", headers=citizen["headers"], json={
        "text": "There is a huge pothole near the school gate",
        "language": "English", "location": "Kothrud"})
    assert r.status_code == 200
    assert r.json()["persistence"] == "postgres"

    from database.db import SessionLocal
    s = SessionLocal()
    try:
        assert s.query(models.Complaint).count() >= 1
    finally:
        s.close()


def test_complaint_id_format_through_the_api(client, citizen):
    _seed_reference_data()
    r = client.post("/complaints", headers=citizen["headers"], json={
        "text": "Potholes all over the main road here",
        "language": "English", "location": "Kothrud"})
    cid = r.json()["complaint"]["complaint_id"]
    assert cid.startswith("CA-") and len(cid) == 9 and cid[3:].isdigit()


# --- 10. response contract -------------------------------------------------

def _provision_officer(email, password="password123"):
    """
    Create an officer and return its bearer header.

    Deliberately not `/auth/register`: that route is unauthenticated and
    creates citizens only, so an officer has to be provisioned out of band.
    Deliberately not the `make_auth_user` fixture either -- that depends on
    `clean_db`, which truncates. The tests in this module share a database
    across fixtures and assert on rows seeded earlier in the same test, so a
    truncation here would delete the complaint under examination.
    """
    from backend.auth import (UserCreate, create_access_token, create_user,
                              normalise_email)
    from database.db import SessionLocal

    s = SessionLocal()
    try:
        user = create_user(s, UserCreate(
            full_name="Officer One", email=normalise_email(email),
            password=password, role="officer"))
        s.commit()
    finally:
        s.close()
    token = create_access_token(data={"sub": normalise_email(email)})
    return {"Authorization": f"Bearer {token}"}


def test_officer_complaints_expose_the_stored_ai_analysis(client, citizen):
    """
    The officer's "what did the system understand this to be" view. These are
    the columns the AI layer wrote at submission; they were stored and never
    returned, which is why the detail modal used to show em dashes.
    """
    _seed_reference_data()
    r = client.post("/complaints", headers=citizen["headers"], json={
        "text": "The streetlight outside our building has not worked for a month",
        "language": "English", "location": "Kothrud"})
    stored = r.json()["analysis"]
    assert stored["issue_summary"] and stored["affected_group"]
    assert stored["recommended_action"] and stored["urgency"]

    listed = client.get("/complaints",
                        headers=_provision_officer("officer-ai@example.com")).json()
    row = next(c for c in listed["complaints"]
               if c["complaint_id"] == r.json()["complaint"]["complaint_id"])
    assert row["analysis_issue_summary"] == stored["issue_summary"]
    assert row["analysis_affected_group"] == stored["affected_group"]
    assert row["analysis_urgency"] == stored["urgency"]
    assert row["analysis_recommended_action"] == stored["recommended_action"]


def test_complaint_analysis_fields_are_null_rather_than_invented(client, citizen):
    """
    A row with no analysis must report null, not a plausible-looking value. The
    UI renders null as unavailable, so fabricating here would put invented
    evidence in front of an officer.
    """
    from database.db import SessionLocal
    _seed_reference_data()
    s = SessionLocal()
    try:
        row = models.Complaint(text="potholes near the gate", category="Road Infrastructure",
                               severity="Medium")
        s.add(row)
        s.commit()
        row_id = row.id
    finally:
        s.close()

    from backend import complaint_service
    s = SessionLocal()
    try:
        contract = complaint_service.complaint_to_contract(s.get(models.Complaint, row_id))
    finally:
        s.close()

    assert contract["analysis_issue_summary"] is None
    assert contract["analysis_urgency"] is None
    assert contract["analysis_affected_group"] is None
    assert contract["analysis_recommended_action"] is None
    assert contract["cluster_id"] is None


def test_complaint_contract_carries_the_cluster_id(client, citizen):
    """
    The cluster is the join from one complaint to the hotspot and
    recommendation built from it, so it has to be on the row the dashboard has.
    """
    _seed_reference_data()
    r = client.post("/complaints", headers=citizen["headers"], json={
        "text": "Potholes again on the same stretch of road",
        "language": "English", "location": "Kothrud"})
    assert r.json()["complaint"]["cluster_id"] is not None


def test_complaint_contract_keeps_every_original_field(client, citizen):
    """The citizen UI binds to the original eleven; none may be renamed or dropped."""
    _seed_reference_data()
    r = client.post("/complaints", headers=citizen["headers"], json={
        "text": "Garbage not collected for a week in this lane",
        "language": "English", "location": "Kothrud"})
    body = r.json()["complaint"]
    for field in ("complaint_id", "user_id", "text", "language", "location",
                  "category", "severity", "priority_score", "priority_level",
                  "status", "created_at"):
        assert field in body, f"{field} was dropped from the complaint contract"


def test_post_complaints_contract_fields(client, citizen):
    _seed_reference_data()
    r = client.post("/complaints", headers=citizen["headers"], json={
        "text": "Broken streetlight near the main crossing",
        "language": "English", "location": "Kothrud"})
    body = r.json()
    assert set(body) >= {"success", "complaint", "analysis", "priority",
                         "ai_provider", "duplicate"}
    assert set(body["complaint"]) == FRONTEND_COMPLAINT_FIELDS


def test_post_complaints_response_types(client, citizen):
    _seed_reference_data()
    r = client.post("/complaints", headers=citizen["headers"], json={
        "text": "Water supply has been irregular for a week",
        "language": "English", "location": "Kothrud"})
    c = r.json()["complaint"]
    assert isinstance(c["complaint_id"], str)
    assert isinstance(c["user_id"], int)
    assert isinstance(c["priority_score"], (int, float, type(None)))


def test_priority_block_keeps_factor_keys(client, citizen):
    _seed_reference_data()
    r = client.post("/complaints", headers=citizen["headers"], json={
        "text": "Potholes near the college entrance again",
        "language": "English", "location": "Kothrud"})
    factors = r.json()["priority"]["factors"]
    assert set(factors) == {
        "citizen_demand", "infrastructure_gap", "population_impact",
        "urgency", "investment_gap"}


def test_duplicate_block_keeps_shape(client, citizen):
    _seed_reference_data()
    r = client.post("/complaints", headers=citizen["headers"], json={
        "text": "Garbage not collected for a week", "language": "English",
        "location": "Kothrud"})
    assert set(r.json()["duplicate"]) == {
        "success", "is_duplicate", "similar_complaints", "duplicate_count"}


def test_unauthenticated_submission_keeps_legacy_shape(client):
    """Unauthenticated complaints are still not stored, and say so."""
    r = client.post("/complaints", json={
        "text": "Some anonymous pothole report here", "language": "English",
        "location": "Kothrud"})
    assert r.status_code == 200
    body = r.json()
    assert body["complaint"] == {
        "text": "Some anonymous pothole report here",
        "language": "English", "location": "Kothrud", "status": "received"}
    assert body["persistence"] is None


def test_my_complaints_contract(client, citizen):
    _seed_reference_data()
    client.post("/complaints", headers=citizen["headers"], json={
        "text": "First complaint about potholes", "language": "English",
        "location": "Kothrud"})
    r = client.get("/complaints/my", headers=citizen["headers"])
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"success", "complaints", "total"}
    for c in body["complaints"]:
        assert set(c) == FRONTEND_COMPLAINT_FIELDS


def test_complaint_appears_in_my_complaints(client, citizen):
    _seed_reference_data()
    posted = client.post("/complaints", headers=citizen["headers"], json={
        "text": "A complaint that must round trip", "language": "English",
        "location": "Kothrud"}).json()["complaint"]
    mine = client.get("/complaints/my", headers=citizen["headers"]).json()
    ids = [c["complaint_id"] for c in mine["complaints"]]
    assert posted["complaint_id"] in ids


def test_my_complaints_newest_first(client, citizen):
    _seed_reference_data()
    for i in range(3):
        client.post("/complaints", headers=citizen["headers"], json={
            "text": f"Pothole number {i} on the main road", "language": "English",
            "location": "Kothrud"})
    mine = client.get("/complaints/my", headers=citizen["headers"]).json()
    assert mine["total"] == len(mine["complaints"]) >= 3
    created = [c["created_at"] for c in mine["complaints"]]
    assert created == sorted(created, reverse=True)


# --- ownership -------------------------------------------------------------

def test_citizen_cannot_see_another_citizens_complaints(client, citizen):
    _seed_reference_data()
    client.post("/complaints", headers=citizen["headers"], json={
        "text": "Private complaint from the first citizen", "language": "English",
        "location": "Kothrud"})

    client.post("/auth/register", json={
        "full_name": "Other Person", "email": "other@example.com",
        "password": "password123"})
    other = client.post("/auth/login", json={
        "email": "other@example.com", "password": "password123"}).json()["access_token"]

    theirs = client.get("/complaints/my",
                        headers={"Authorization": f"Bearer {other}"}).json()
    assert all("Private complaint" not in c["text"] for c in theirs["complaints"])


def test_my_complaints_requires_auth(client):
    assert client.get("/complaints/my").status_code == 401


# --- 11. existing endpoints still work -------------------------------------

def test_hotspots_still_works(client):
    r = client.get("/hotspots")
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert isinstance(r.json()["hotspots"], list)


def test_root_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/health").json() == {"status": "healthy"}


def test_analyze_endpoints_still_work(client):
    r = client.post("/complaints/analyze", json={
        "text": "huge potholes on the road", "language": "English",
        "location": "Kothrud"})
    assert r.status_code == 200
    assert "category" in r.json()["analysis"]

    r2 = client.post("/complaints/analyze-and-prioritize", json={
        "text": "no water supply for two days", "language": "English",
        "location": "Kothrud"})
    assert r2.status_code == 200
    assert r2.json()["priority"]["priority_level"] in ("Low", "Medium", "High")


def test_priority_endpoint_still_uses_the_mock_engine(client):
    """The old endpoint keeps its behaviour; it is not routed to the DB engine."""
    r = client.post("/complaints/priority", json={
        "citizen_demand": 80, "infrastructure_gap": 70, "population_impact": 60,
        "urgency": 90, "investment_gap": 40})
    assert r.json()["priority"]["priority_score"] == 71.0


def test_check_duplicate_endpoint_still_works(client):
    r = client.post("/complaints/check-duplicate", json={
        "text": "There are huge potholes on the road near the college",
        "location": "Pune"})
    assert r.status_code == 200
    assert r.json()["is_duplicate"] is True


# --- 12. auth endpoints ----------------------------------------------------

def test_auth_register_login_me(client):
    r = client.post("/auth/register", json={
        "full_name": "New Person", "email": "new@example.com",
        "password": "password123"})
    assert r.status_code == 201
    assert set(r.json()) == {"id", "full_name", "email", "role", "created_at"}

    tok = client.post("/auth/login", json={
        "email": "new@example.com", "password": "password123"}).json()
    assert "access_token" in tok and tok["token_type"] == "bearer"

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {tok['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "new@example.com"


def test_auth_rejects_duplicate_email(client):
    payload = {"full_name": "Dup", "email": "dup@example.com", "password": "password123"}
    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/register", json=payload).status_code == 400


def test_auth_rejects_bad_password(client):
    client.post("/auth/register", json={
        "full_name": "P", "email": "p@example.com", "password": "password123"})
    assert client.post("/auth/login", json={
        "email": "p@example.com", "password": "wrong"}).status_code == 401


def test_auth_me_requires_token(client):
    assert client.get("/auth/me").status_code == 401


# --- intelligence router ---------------------------------------------------

def test_intelligence_router_is_mounted(client):
    paths = client.app.openapi()["paths"]
    assert "/intelligence/hotspots" in paths
    assert "/intelligence/recommendations" in paths
    assert "/intelligence/stats" in paths


def test_intelligence_routes_are_not_shadowed_by_hotspots(client):
    """main.py's /hotspots must remain the mock one."""
    paths = client.app.openapi()["paths"]
    assert "/hotspots" in paths and "/intelligence/hotspots" in paths
    assert client.get("/hotspots").json()["hotspots"][0].get("hotspot_score") is not None


def test_mount_is_idempotent(client):
    from backend import main as m
    before = len(client.app.openapi()["paths"])
    m.mount_intelligence(client.app)
    m.mount_intelligence(client.app)
    assert len(client.app.openapi()["paths"]) == before


def test_intelligence_stats_endpoint_responds(client, auth_headers):
    r = client.get("/intelligence/stats",
                   headers=auth_headers("intel-officer@example.com", role="officer"))
    assert r.status_code == 200
    assert "complaints" in r.json()


# --- AI provider provenance over HTTP ---------------------------------------
#
# `ai_provider` used to be the *configured* AI_PROVIDER echoed into the
# response, so a silent fallback to the mock provider still reported "gemini".
# These tests pin the honest behaviour: the response reports what ran, and a
# fallback is always accompanied by a safe reason code.

ANALYSIS_ENDPOINTS = [
    "/complaints/analyze",
    "/complaints/analyze-and-prioritize",
]


def _analysis_payload():
    return {"text": "Potholes all over the main road near the school",
            "language": "English", "location": "Kothrud"}


@pytest.fixture
def gemini_stub(monkeypatch):
    """Swap `backend.ai.analyze_complaint` for one that reports a chosen outcome."""
    def _stub(provider_used, fallback_reason=None):
        from backend import ai

        def fake(text, language, location):
            out = ai.analyze_with_mock(text, language, location)
            out["provider_used"] = provider_used
            if fallback_reason:
                out["fallback_reason"] = fallback_reason
            return out
        monkeypatch.setattr(ai, "analyze_complaint", fake)
        # main.py imported the symbol directly, so patch there too.
        monkeypatch.setattr(main, "analyze_complaint", fake)
    return _stub


def test_analyze_reports_provider_used_gemini(client, gemini_stub):
    gemini_stub("gemini")
    body = client.post("/complaints/analyze", json=_analysis_payload()).json()
    assert body["ai_provider"] == "gemini"
    # No fallback happened, so the field is present but null. A client
    # branches on truthiness, so null and absent are equivalent here.
    assert body["fallback_reason"] is None
    # Inside `analysis` the key is genuinely absent, not null.
    assert "fallback_reason" not in body["analysis"]


def test_analyze_reports_provider_used_mock_with_reason(client, gemini_stub):
    gemini_stub("mock", "quota_exhausted")
    body = client.post("/complaints/analyze", json=_analysis_payload()).json()
    assert body["ai_provider"] == "mock"
    assert body["fallback_reason"] == "quota_exhausted"


def test_post_complaints_reports_provider_used(client, citizen, gemini_stub):
    _seed_reference_data()
    gemini_stub("mock", "quota_exhausted")
    body = client.post("/complaints", headers=citizen["headers"],
                       json=_analysis_payload()).json()
    assert body["ai_provider"] == "mock"
    assert body["fallback_reason"] == "quota_exhausted"


def test_unauthenticated_submission_also_reports_provider_used(client, gemini_stub):
    gemini_stub("mock", "api_error")
    body = client.post("/complaints", json=_analysis_payload()).json()
    assert body["ai_provider"] == "mock"
    assert body["fallback_reason"] == "api_error"


@pytest.mark.parametrize("path", ANALYSIS_ENDPOINTS)
def test_both_analysis_endpoints_report_provenance(client, gemini_stub, path):
    gemini_stub("mock", "invalid_response")
    body = client.post(path, json=_analysis_payload()).json()
    assert body["ai_provider"] == "mock"
    assert body["fallback_reason"] == "invalid_response"


def test_analysis_fields_remain_backward_compatible(client, gemini_stub):
    """
    Provenance is additive. Every field the citizen frontend and the priority
    engine already read must still be present, whatever provider ran.
    """
    gemini_stub("gemini")
    body = client.post("/complaints/analyze", json=_analysis_payload()).json()

    analysis = body["analysis"]
    for field in ("language", "category", "location", "severity", "urgency",
                  "affected_group", "issue_summary", "recommended_action",
                  "provider_used"):
        assert field in analysis, f"analysis lost {field}"

    # The analyse-and-prioritize block must be untouched by this change.
    combo = client.post("/complaints/analyze-and-prioritize",
                        json=_analysis_payload()).json()
    assert set(combo["priority"]["factors"]) == {
        "citizen_demand", "infrastructure_gap", "population_impact",
        "urgency", "investment_gap"}


def test_no_api_key_appears_in_any_analysis_response(client, gemini_stub):
    """
    A credential must never reach a response body, in either the success or
    the fallback case.
    """
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO_ROOT, "backend", ".env"))
    secret = os.environ.get("GEMINI_API_KEY")
    if not secret:
        pytest.skip("no GEMINI_API_KEY configured")

    gemini_stub("mock", "quota_exhausted")
    raw = client.post("/complaints/analyze", json=_analysis_payload()).text
    assert secret not in raw
