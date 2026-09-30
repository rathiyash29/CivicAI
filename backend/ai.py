import os
import json
import logging
from typing import Literal
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

AI_PROVIDER = os.getenv("AI_PROVIDER", "mock")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

# Which provider actually produced an analysis. `AI_PROVIDER` is only the
# *requested* provider: when Gemini fails and the mock takes over, the honest
# answer is "mock", and these two values are not the same thing.
PROVIDER_GEMINI = "gemini"
PROVIDER_MOCK = "mock"

# Machine-readable reasons a fallback happened. These are deliberately coarse
# and deliberately safe to return over HTTP: a client needs to know whether it
# got real AI, not why the vendor rejected the call. No exception text, no
# vendor error body, and never a credential ever reaches a response.
FALLBACK_QUOTA_EXHAUSTED = "quota_exhausted"
FALLBACK_API_ERROR = "api_error"
FALLBACK_INVALID_RESPONSE = "invalid_response"
FALLBACK_NOT_CONFIGURED = "not_configured"
FALLBACK_UNEXPECTED = "unexpected_error"

# Vendor error text is matched case-insensitively to pick a reason. Kept here
# as substrings rather than a regex so a vendor reworded message degrades to
# FALLBACK_API_ERROR instead of crashing the classifier.
_QUOTA_MARKERS = ("429", "quota", "resource_exhausted", "rate limit", "rate_limit")
_UNAUTHORIZED_MARKERS = ("401", "403", "unauthorized", "permission", "api key",
                         "forbidden")
_BAD_REQUEST_MARKERS = ("400", "invalid argument", "invalid_request")


class GeminiError(RuntimeError):
    """
    A Gemini failure, carrying a safe reason code.

    The original vendor message is deliberately NOT retained on the exception
    object beyond what the constructor was given, because these exceptions
    propagate toward an HTTP response. Callers get `reason`; nobody gets the
    raw vendor text.
    """

    def __init__(self, reason: str, user_message: str):
        super().__init__(user_message)
        self.reason = reason

CATEGORIES = [
    "Road Infrastructure",
    "Water Supply",
    "Electricity",
    "Sanitation",
    "Public Transport",
    "Healthcare",
    "Education",
    "Other",
]

SEVERITY_LEVELS = ["Low", "Medium", "High"]
URGENCY_LEVELS = ["Low", "Medium", "High"]


KEYWORD_CATEGORIES = {
    "Road Infrastructure": [
        "pothole", "potholes", "road", "highway", "bridge", "footpath",
        "sidewalk", "asphalt", "tar", "crack", "damaged road", "uneven", "manhole",
        "drainage cover", "speed breaker", "zebra crossing", "traffic signal"
    ],
    "Water Supply": [
        "water", "supply", "tap", "pipe", "leak", "leakage", "no water", "dry tap",
        "contaminated", "dirty water", "water quality", "pressure", "municipal water",
        "borewell", "tanker", "water shortage", "water cut"
    ],
    "Electricity": [
        "electricity", "power", "light", "streetlight", "street light", "lamp",
        "bulb", "wire", "cable", "transformer", "pole", "outage", "blackout",
        "load shedding", "voltage", "fluctuation", "meter", "bill"
    ],
    "Sanitation": [
        "garbage", "trash", "waste", "dump", "dustbin", "bin", "sewage", "drain",
        "drainage", "sewer", "toilet", "sanitation", "cleanliness", "filth",
        "mosquito", "stagnant", "overflow", "garbage collection"
    ],
    "Public Transport": [
        "bus", "bus stop", "bus stand", "train", "railway", "metro", "auto",
        "rickshaw", "transport", "commute", "fare", "schedule", "delay",
        "overcrowded", "frequency", "route", "station", "platform"
    ],
    "Healthcare": [
        "hospital", "clinic", "doctor", "nurse", "medicine", "pharmacy",
        "ambulance", "emergency", "health", "medical", "treatment", "patient",
        "ward", "icu", "vaccine", "vaccination", "health center", "primary health"
    ],
    "Education": [
        "school", "college", "university", "teacher", "student", "classroom",
        "education", "admission", "exam", "result", "fee", "scholarship",
        "midday meal", "uniform", "textbook", "library", "laboratory", "playground"
    ],
}

SEVERITY_KEYWORDS = {
    "High": [
        "emergency", "urgent", "critical", "dangerous", "hazard", "accident",
        "death", "injury", "collapsed", "flood", "fire", "toxic", "poison",
        "no water", "no electricity", "completely", "totally", "days", "weeks"
    ],
    "Medium": [
        "broken", "damaged", "not working", "malfunction", "leak", "delay",
        "irregular", "poor", "bad", "difficult", "problem", "issue", "faulty"
    ],
    "Low": [
        "minor", "small", "slight", "occasionally", "sometimes", "request",
        "suggestion", "improve", "better", "upgrade", "maintenance"
    ],
}

URGENCY_KEYWORDS = {
    "High": [
        "emergency", "urgent", "immediate", "asap", "critical", "dangerous",
        "hazard", "accident", "risk", "unsafe", "children", "school", "hospital",
        "elderly", "senior", "pregnant", "no water", "no electricity", "days"
    ],
    "Medium": [
        "soon", "quickly", "important", "needs attention", "should fix",
        "regular", "daily", "frequent", "recurring", "ongoing"
    ],
    "Low": [
        "when possible", "eventually", "sometime", "minor", "cosmetic",
        "aesthetic", "preference", "nice to have"
    ],
}


def analyze_complaint(text: str, language: str, location: str) -> dict:
    """
    Analyze a citizen complaint using the configured AI provider.

    The returned dict is the existing analysis contract, unchanged, plus two
    additive keys:

      provider_used     "gemini" or "mock" -- what ACTUALLY produced this
                        analysis. Never the configured value, which is only
                        what was asked for.
      fallback_reason   OMITTED from the analysis dict when there was no
                        fallback, and set to one of quota_exhausted |
                        api_error | invalid_response | not_configured |
                        unexpected_error when there was. (The HTTP envelope in
                        `main.py` always carries the key, null when unused, so
                        the response schema stays stable.)

    Reporting the provider that ran is the whole point. A demo that silently
    substitutes keyword matching while claiming real AI is worse than one that
    openly says it fell back.
    """
    if AI_PROVIDER == PROVIDER_GEMINI:
        try:
            result = analyze_with_gemini(text, language, location)
        except GeminiError as exc:
            logger.warning(
                "Gemini unavailable (%s); falling back to mock analysis", exc.reason
            )
            result = _with_provider(analyze_with_mock(text, language, location),
                                    PROVIDER_MOCK, exc.reason)
        except ValueError as exc:
            # Kept for safety: any future non-GeminiError ValueError raised
            # inside the Gemini path still degrades instead of 500-ing.
            logger.warning("Gemini config error; falling back to mock: %s", exc)
            result = _with_provider(analyze_with_mock(text, language, location),
                                    PROVIDER_MOCK, FALLBACK_NOT_CONFIGURED)
        except Exception:
            # The vendor message is logged at debug level only. It is not put
            # in the response, because an unexpected exception is exactly the
            # case most likely to carry a credential or an internal URL.
            logger.warning("Unexpected Gemini error; falling back to mock",
                           exc_info=True)
            result = _with_provider(analyze_with_mock(text, language, location),
                                    PROVIDER_MOCK, FALLBACK_UNEXPECTED)
        else:
            result = _with_provider(result, PROVIDER_GEMINI)
        return result

    return _with_provider(analyze_with_mock(text, language, location), PROVIDER_MOCK)


def _with_provider(analysis: dict, provider_used: str,
                   fallback_reason: str = None) -> dict:
    """
    Stamp the provenance of an analysis onto it.

    `fallback_reason` is omitted entirely when there was no fallback, rather
    than sent as null, so a client can branch on key presence and a successful
    Gemini call cannot be mistaken for a degraded one.
    """
    analysis["provider_used"] = provider_used
    if fallback_reason:
        analysis["fallback_reason"] = fallback_reason
    return analysis


def _classify_gemini_error(message: str) -> str:
    """
    Map a vendor error message onto a safe, coarse reason code.

    Quota is checked first and separately from the other codes, because the
    free tier's 429 is a *daily* allowance rather than a burst limit: retrying
    cannot help, so the caller must not try.
    """
    lowered = (message or "").lower()
    if any(marker in lowered for marker in _QUOTA_MARKERS):
        return FALLBACK_QUOTA_EXHAUSTED
    if any(marker in lowered for marker in _UNAUTHORIZED_MARKERS):
        return FALLBACK_API_ERROR
    if any(marker in lowered for marker in _BAD_REQUEST_MARKERS):
        return FALLBACK_API_ERROR
    return FALLBACK_API_ERROR


def analyze_with_mock(text: str, language: str, location: str) -> dict:
    """
    Mock AI analysis using keyword-based logic.
    Returns structured analysis for a citizen complaint.
    """
    text_lower = text.lower()
    location_lower = location.lower()

    category = categorize(text_lower)
    severity = assess_severity(text_lower)
    urgency = assess_urgency(text_lower)
    affected_group = identify_affected_group(text_lower)
    issue_summary = generate_summary(text_lower, category)
    recommended_action = generate_action(category, severity)

    return {
        "language": language,
        "category": category,
        "location": location,
        "severity": severity,
        "urgency": urgency,
        "affected_group": affected_group,
        "issue_summary": issue_summary,
        "recommended_action": recommended_action,
    }


def analyze_with_gemini(text: str, language: str, location: str) -> dict:
    """
    Analyze a citizen complaint using Google Gemini AI.

    Returns the plain analysis contract. Provenance is added by the caller
    (`analyze_complaint`), so this function stays directly testable against a
    stubbed client and a bare call to it never reports a provider.

    Raises:
        GeminiError: always. Carries a safe `reason` code from the
            FALLBACK_* constants, and a user-facing message that contains no
            vendor text and no credential.

    No retry is attempted, and none should be added here without changing this
    contract. The free tier's 429 is a daily per-project allowance, not a burst
    limit, so an automatic retry is a guaranteed second failed call and would
    burn the remaining quota rather than recover from it.
    """
    if not GEMINI_API_KEY:
        raise GeminiError(
            FALLBACK_NOT_CONFIGURED,
            "Gemini is not configured (no API key available).",
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise GeminiError(
            FALLBACK_API_ERROR,
            f"google-genai SDK is not installed: {e}",
        )

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = _build_gemini_prompt(text, language, location)

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
                max_output_tokens=1024,
            ),
        )
    except Exception as e:
        # The vendor message drives the classification, but it never leaves
        # this function: only the coarse reason code does.
        reason = _classify_gemini_error(str(e))
        logger.debug("Gemini call failed (%s): %s", reason, e)
        raise GeminiError(
            reason,
            f"Gemini request failed ({reason}).",
        ) from None

    if not response or not response.text:
        raise GeminiError(
            FALLBACK_INVALID_RESPONSE,
            "Gemini returned an empty response.",
        )

    try:
        result = json.loads(response.text)
    except (json.JSONDecodeError, TypeError):
        raise GeminiError(
            FALLBACK_INVALID_RESPONSE,
            "Gemini returned a response that was not valid JSON.",
        ) from None

    if not isinstance(result, dict):
        raise GeminiError(
            FALLBACK_INVALID_RESPONSE,
            "Gemini returned valid JSON that was not an object.",
        )

    try:
        return _validate_and_normalize_gemini_result(result, language, location)
    except GeminiError:
        raise
    except Exception:
        raise GeminiError(
            FALLBACK_INVALID_RESPONSE,
            "Gemini response did not match the CivicAI analysis schema.",
        ) from None


def _build_gemini_prompt(text: str, language: str, location: str) -> str:
    """Build the prompt for Gemini to analyze a civic complaint."""
    categories_str = ", ".join(CATEGORIES)
    return f"""You are a civic issue analysis system for CivicAI. Analyze the following citizen complaint and return a JSON object with the specified fields.

Complaint:
- Text: {text}
- Language: {language}
- Location: {location}

Return ONLY a JSON object with these exact fields:
{{
  "language": "{language}",
  "category": "one of: {categories_str}",
  "location": "{location}",
  "severity": "Low | Medium | High",
  "urgency": "Low | Medium | High",
  "affected_group": "description of affected population group",
  "issue_summary": "one-sentence summary of the issue",
  "recommended_action": "specific recommended remediation action"
}}

Rules:
- category MUST be exactly one of the listed categories
- severity MUST be exactly "Low", "Medium", or "High"
- urgency MUST be exactly "Low", "Medium", or "High"
- All fields are required
- No extra fields, no markdown, no explanation"""


def _validate_and_normalize_gemini_result(result: dict, language: str, location: str) -> dict:
    """
    Validate and normalize a Gemini response to the CivicAI analysis schema.

    Raises `GeminiError(FALLBACK_INVALID_RESPONSE)` on a missing field, so a
    schema miss degrades to the mock provider instead of surfacing as a 500.
    """
    required_fields = [
        "language", "category", "location", "severity", "urgency",
        "affected_group", "issue_summary", "recommended_action"
    ]

    for field in required_fields:
        if field not in result:
            raise GeminiError(
                FALLBACK_INVALID_RESPONSE,
                f"Gemini response missing required field: {field}",
            )

    # Normalize category to match known categories
    category = result["category"]
    if category not in CATEGORIES:
        # Try case-insensitive match
        matched = next((c for c in CATEGORIES if c.lower() == category.lower()), None)
        if matched:
            result["category"] = matched
        else:
            result["category"] = "Other"

    # Normalize severity
    severity = result["severity"]
    if severity not in SEVERITY_LEVELS:
        # Try case-insensitive match
        matched = next((s for s in SEVERITY_LEVELS if s.lower() == severity.lower()), None)
        if matched:
            result["severity"] = matched
        else:
            result["severity"] = "Medium"

    # Normalize urgency
    urgency = result["urgency"]
    if urgency not in URGENCY_LEVELS:
        matched = next((u for u in URGENCY_LEVELS if u.lower() == urgency.lower()), None)
        if matched:
            result["urgency"] = matched
        else:
            result["urgency"] = "Medium"

    # Ensure language and location are preserved from request
    result["language"] = language
    result["location"] = location

    return result


def categorize(text: str) -> str:
    scores = {}
    for category, keywords in KEYWORD_CATEGORIES.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[category] = score

    if scores:
        return max(scores, key=scores.get)
    return "Other"


def assess_severity(text: str) -> str:
    for level in ["High", "Medium", "Low"]:
        keywords = SEVERITY_KEYWORDS[level]
        if any(kw in text for kw in keywords):
            return level
    return "Medium"


def assess_urgency(text: str) -> str:
    for level in ["High", "Medium", "Low"]:
        keywords = URGENCY_KEYWORDS[level]
        if any(kw in text for kw in keywords):
            return level
    return "Medium"


def identify_affected_group(text: str) -> str:
    if any(kw in text for kw in ["school", "children", "student", "playground"]):
        return "Students and children"
    if any(kw in text for kw in ["elderly", "senior", "old age", "pensioner"]):
        return "Elderly residents"
    if any(kw in text for kw in ["hospital", "patient", "pregnant", "medical"]):
        return "Patients and vulnerable groups"
    if any(kw in text for kw in ["commuter", "travel", "bus", "train", "daily"]):
        return "Daily commuters"
    if any(kw in text for kw in ["resident", "local", "community", "neighbour", "area"]):
        return "Local residents"
    return "General public"


def generate_summary(text: str, category: str) -> str:
    templates = {
        "Road Infrastructure": "Road damage causing difficulty for commuters and safety concerns.",
        "Water Supply": "Water supply disruption affecting daily needs of residents.",
        "Electricity": "Electrical issue impacting lighting and power supply in the area.",
        "Sanitation": "Sanitation problem creating health and hygiene concerns.",
        "Public Transport": "Public transport issue affecting daily commute of residents.",
        "Healthcare": "Healthcare access or quality concern raised by community.",
        "Education": "Education infrastructure or service issue affecting students.",
        "Other": "Community issue reported requiring attention from authorities.",
    }
    return templates.get(category, templates["Other"])


def generate_action(category: str, severity: str) -> str:
    actions = {
        "Road Infrastructure": {
            "High": "Immediately inspect and repair the damaged road section to prevent accidents.",
            "Medium": "Schedule road inspection and plan repairs within the week.",
            "Low": "Add to routine road maintenance schedule.",
        },
        "Water Supply": {
            "High": "Emergency water tanker deployment and immediate pipeline repair.",
            "Medium": "Investigate supply disruption and restore within 24-48 hours.",
            "Low": "Schedule pipeline maintenance and quality check.",
        },
        "Electricity": {
            "High": "Emergency repair of power infrastructure to restore supply.",
            "Medium": "Schedule repair of street lights and electrical fixtures.",
            "Low": "Add to routine electrical maintenance plan.",
        },
        "Sanitation": {
            "High": "Immediate cleanup and waste removal; address drainage overflow.",
            "Medium": "Schedule garbage collection and drain cleaning.",
            "Low": "Improve waste management schedule and bin placement.",
        },
        "Public Transport": {
            "High": "Urgent review of transport schedule and capacity; deploy additional vehicles.",
            "Medium": "Adjust bus frequency and fix bus stop infrastructure.",
            "Low": "Review route optimization and passenger feedback.",
        },
        "Healthcare": {
            "High": "Immediate investigation of healthcare facility; ensure emergency services.",
            "Medium": "Schedule facility inspection and address staffing/equipment gaps.",
            "Low": "Plan facility upgrade and service improvement.",
        },
        "Education": {
            "High": "Urgent safety inspection of school infrastructure; ensure student safety.",
            "Medium": "Address facility issues and coordinate with education department.",
            "Low": "Plan infrastructure improvements for next academic session.",
        },
        "Other": {
            "High": "Prioritize investigation and immediate action.",
            "Medium": "Schedule inspection and remedial action.",
            "Low": "Log for future planning and community review.",
        },
    }
    return actions.get(category, actions["Other"]).get(severity, actions["Other"]["Medium"])