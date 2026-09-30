"""
Provider provenance: which AI provider actually answered, and why it fell back.

The bug this suite exists to prevent is a quiet one. `AI_PROVIDER` is the
*configured* preference, and the old code echoed it straight into the API
response. When Gemini failed and the mock keyword engine quietly took over, the
response still said "gemini" -- a demo claiming real AI that never ran, with no
way for the frontend to tell.

Every test here asserts on `provider_used`, which is what actually executed.
"""
import json
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend import ai


VALID_PAYLOAD = {
    "language": "English",
    "category": "Water Supply",
    "location": "Kothrud",
    "severity": "High",
    "urgency": "High",
    "affected_group": "Local residents",
    "issue_summary": "Water supply has been irregular for a week.",
    "recommended_action": "Deploy tankers and repair the pipeline.",
}


@pytest.fixture
def as_provider(monkeypatch):
    """Point `analyze_complaint` at a specific provider for the test."""
    def _set(name):
        monkeypatch.setattr(ai, "AI_PROVIDER", name)
    return _set


@pytest.fixture
def fake_genai_client(monkeypatch):
    """
    Stub the SDK at its outermost point, so the REAL `analyze_with_gemini` runs.

    Patching `analyze_with_gemini` itself would skip the very code these tests
    exist to cover: the 429 classification, the JSON parsing and the no-retry
    guarantee. Instead only `genai.Client` is replaced, and `generate_content`
    is made to do whatever `behaviour` asks for.
    """
    state = {"calls": 0, "behaviour": None}

    def _install(behaviour):
        """`behaviour` is a callable receiving the keyword args of the call."""
        state["behaviour"] = behaviour

        class FakeModels:
            def generate_content(self, **kwargs):
                state["calls"] += 1
                return state["behaviour"](**kwargs)

        class FakeClient:
            def __init__(self, **kwargs):
                self.models = FakeModels()

        import google.genai as genai_mod
        monkeypatch.setattr(genai_mod, "Client", FakeClient)
        monkeypatch.setattr(ai, "GEMINI_API_KEY", "test-key-not-a-real-credential")
        return state

    return _install


def ok_response(payload):
    class R:
        text = json.dumps(payload)
    return R()


def raw_response(text):
    class R:
        pass
    R.text = text
    return R()


def raises(message):
    def _behaviour(**kwargs):
        raise RuntimeError(message)
    return _behaviour


# --- happy paths ------------------------------------------------------------

def test_mock_provider_reports_mock(as_provider):
    as_provider("mock")
    result = ai.analyze_complaint("Potholes on the road", "English", "Kothrud")
    assert result["provider_used"] == "mock"


def test_successful_gemini_reports_gemini(as_provider, fake_genai_client):
    as_provider("gemini")
    fake_genai_client(lambda **kw: ok_response(VALID_PAYLOAD))

    result = ai.analyze_complaint(
        "There is no water supply in my colony", "English", "Kothrud")

    assert result["provider_used"] == "gemini"
    assert result["category"] == "Water Supply"
    assert result["severity"] == "High"
    # A success must NOT carry a fallback reason at all.
    assert "fallback_reason" not in result


def test_a_429_falls_back_to_mock_with_quota_reason(as_provider, fake_genai_client):
    as_provider("gemini")
    fake_genai_client(raises(
        "429 RESOURCE_EXHAUSTED. quota exceeded for "
        "generate_content_free_tier_requests"))

    result = ai.analyze_complaint("No water for four days", "English", "Kothrud")

    assert result["provider_used"] == "mock"
    assert result["fallback_reason"] == "quota_exhausted"


def test_a_429_is_not_retried(as_provider, fake_genai_client):
    """
    The free tier's 429 is a daily per-project allowance, not a burst limit.
    Retrying is a guaranteed second failed call that also burns quota, so
    exactly one attempt must be made.
    """
    as_provider("gemini")
    state = fake_genai_client(raises("429 quota exceeded"))

    ai.analyze_complaint("No water for four days", "English", "Kothrud")

    assert state["calls"] == 1


def test_malformed_json_falls_back_to_mock(as_provider, fake_genai_client):
    as_provider("gemini")
    fake_genai_client(
        lambda **kw: raw_response("Sure! Here is your analysis: {not json at all"))

    result = ai.analyze_complaint("No water for four days", "English", "Kothrud")

    assert result["provider_used"] == "mock"
    assert result["fallback_reason"] == "invalid_response"


def test_empty_response_falls_back_to_mock(as_provider, fake_genai_client):
    as_provider("gemini")
    fake_genai_client(lambda **kw: raw_response(""))

    result = ai.analyze_complaint("No water for four days", "English", "Kothrud")

    assert result["provider_used"] == "mock"
    assert result["fallback_reason"] == "invalid_response"


def test_schema_violation_falls_back_to_mock(as_provider, fake_genai_client):
    """A well-formed JSON object that is missing a required field."""
    as_provider("gemini")
    partial = {k: v for k, v in VALID_PAYLOAD.items() if k != "severity"}
    fake_genai_client(lambda **kw: ok_response(partial))

    result = ai.analyze_complaint("No water for four days", "English", "Kothrud")

    assert result["provider_used"] == "mock"
    assert result["fallback_reason"] == "invalid_response"


def test_unrecognised_vendor_error_still_yields_a_safe_code(as_provider,
                                                             fake_genai_client):
    """
    An unrecognised message must still classify to a known code, never leak.
    It maps to `api_error` because it came from the vendor call itself.
    """
    as_provider("gemini")
    fake_genai_client(raises(
        "connection to internal-endpoint-7.internal:443 refused"))

    result = ai.analyze_complaint("No water for four days", "English", "Kothrud")

    assert result["provider_used"] == "mock"
    assert result["fallback_reason"] == "api_error"
    # The internal detail must not survive into the analysis payload.
    assert "internal-endpoint" not in json.dumps(result)


def test_a_non_vendor_exception_is_reported_as_unexpected(monkeypatch, as_provider):
    """
    An error from outside the vendor call (a programming fault, say) is
    classified separately, so a genuine bug is not disguised as a vendor
    outage. It is still logged, but only ever at WARNING with no detail in
    the response.
    """
    as_provider("gemini")

    class WeirdError(Exception):
        """Not a GeminiError, not a ValueError: an unexpected fault."""

    def boom(text, language, location):
        raise WeirdError("internal-endpoint-7.internal exploded")

    monkeypatch.setattr(ai, "analyze_with_gemini", boom)
    result = ai.analyze_complaint("No water for four days", "English", "Kothrud")

    assert result["provider_used"] == "mock"
    assert result["fallback_reason"] == "unexpected_error"
    assert "internal-endpoint" not in json.dumps(result)


# --- error classification ---------------------------------------------------

@pytest.mark.parametrize("message,expected", [
    ("429 RESOURCE_EXHAUSTED quota exceeded", "quota_exhausted"),
    ("Quota exceeded for metric: generate_content_free_tier_requests", "quota_exhausted"),
    ("rate limit exceeded, please retry", "quota_exhausted"),
    ("403 PERMISSION_DENIED project denied access", "api_error"),
    ("401 UNAUTHORIZED api key not valid", "api_error"),
    ("400 INVALID_ARGUMENT bad request", "api_error"),
    ("something we have never seen before", "api_error"),
])
def test_vendor_errors_map_to_safe_reason_codes(message, expected):
    assert ai._classify_gemini_error(message) == expected


def test_no_credential_can_appear_in_a_fallback_reason():
    """
    `fallback_reason` is returned over HTTP, so the classifier must only ever
    produce a fixed vocabulary -- never any part of the vendor's message.
    """
    allowed = {
        ai.FALLBACK_QUOTA_EXHAUSTED,
        ai.FALLBACK_API_ERROR,
        ai.FALLBACK_INVALID_RESPONSE,
        ai.FALLBACK_NOT_CONFIGURED,
        ai.FALLBACK_UNEXPECTED,
    }
    hostile = [
        "429 quota exceeded for key AIzaSySECRETSECRETSECRET",
        "403 denied, project=my-project-123, email=dev@example.com",
        "invalid API key: sk-abcdefghijklmnop",
    ]
    for message in hostile:
        assert ai._classify_gemini_error(message) in allowed


# --- analyze_with_gemini directly ------------------------------------------

def test_analyze_with_gemini_raises_gemini_error_without_a_key(monkeypatch):
    monkeypatch.setattr(ai, "GEMINI_API_KEY", None)
    with pytest.raises(ai.GeminiError) as exc:
        ai.analyze_with_gemini("anything", "English", "Kothrud")
    assert exc.value.reason == "not_configured"


def test_analyze_with_gemini_does_not_retry_on_429(fake_genai_client):
    """
    The real call path must make exactly one HTTP attempt on a quota error.
    A retry here would be a second guaranteed failure against a daily cap.
    """
    state = fake_genai_client(raises("429 RESOURCE_EXHAUSTED quota exceeded"))

    with pytest.raises(ai.GeminiError) as exc:
        ai.analyze_with_gemini("anything", "English", "Kothrud")

    assert exc.value.reason == "quota_exhausted"
    assert state["calls"] == 1


def test_gemini_error_message_carries_no_vendor_detail(fake_genai_client):
    secret = "AIzaSySECRETSECRETSECRET"
    fake_genai_client(raises(
        f"403 PERMISSION_DENIED for key {secret} on project my-project-123"))

    with pytest.raises(ai.GeminiError) as exc:
        ai.analyze_with_gemini("anything", "English", "Kothrud")

    assert secret not in str(exc.value)
    assert "my-project-123" not in str(exc.value)


# --- schema compatibility ---------------------------------------------------

def test_analysis_schema_is_unchanged_by_the_provenance_fields(as_provider):
    """
    The provenance keys are additive. Every field the frontend and the
    intelligence engines read must still be present and unchanged.
    """
    as_provider("mock")
    result = ai.analyze_complaint("Potholes on the road", "English", "Kothrud")

    for field in ("language", "category", "location", "severity", "urgency",
                  "affected_group", "issue_summary", "recommended_action"):
        assert field in result, f"analysis contract lost {field}"

    assert result["category"] in ai.CATEGORIES
    assert result["severity"] in ai.SEVERITY_LEVELS
    assert result["urgency"] in ai.URGENCY_LEVELS
    # Mock still echoes the request's own location, never a guessed one.
    assert result["location"] == "Kothrud"


@pytest.mark.parametrize("language", ["English", "Hindi", "Marathi"])
def test_every_supported_language_still_round_trips(as_provider, language):
    as_provider("mock")
    result = ai.analyze_complaint(f"Test complaint in {language}", language, "Kothrud")
    assert result["language"] == language
    assert result["provider_used"] == "mock"
