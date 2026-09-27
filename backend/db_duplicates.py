"""
DB-backed duplicate detection and clustering (Member 2).

The mock `backend/duplicates.py` compares against three hardcoded sample
strings and is left untouched, because `main.py` imports it for
`/complaints/check-duplicate`. This module does the same job against real
rows in the `complaints` table and is what the intelligence router uses.

Similarity is a hybrid of two cheap, offline signals, because either one
alone misses obvious duplicates:

  * token Jaccard on lightly stemmed words -- catches reworded complaints
    ("pothole" vs "potholes", "supply" vs "supplies")
  * character 3-gram Dice coefficient -- catches compound/spacing variants
    the tokeniser would miss entirely ("street lights" vs "streetlights",
    which share zero whitespace tokens and would otherwise score 0.0)

No external service, no embeddings, no network: the demo stays free and
offline-capable.
"""
import re
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from database import models

# Tuned against the paraphrase pairs in tests/test_db_duplicates.py. The
# measured separation is wide: the weakest genuine paraphrase in that set
# scores 36.7 while the strongest unrelated pair -- including same-domain
# ones like "street lights" vs "the transformer keeps sparking" -- scores
# 4.9. Anything in that gap separates the two classes.
SIMILARITY_THRESHOLD = 30.0

# Two complaints in different wards are not duplicates of each other, however
# similar the wording.
NGRAM_SIZE = 3

SEVERITY_SCORES = {"Low": 1.0, "Medium": 2.0, "High": 3.0}
DEFAULT_SEVERITY_SCORE = 2.0

# Guard against a pathological O(n*m) sweep on a large table.
CLUSTER_MATCH_CANDIDATES = 200

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "here", "he", "her", "him", "his", "how", "i", "in", "into", "is", "it",
    "its", "me", "my", "no", "not", "now", "of", "on", "one", "or", "our",
    "out", "over", "own", "she", "should", "since", "so", "some", "such",
    "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "those", "through", "to", "too", "under", "up", "very", "was",
    "we", "were", "what", "when", "where", "which", "while", "who", "why",
    "will", "with", "would", "you", "your", "our", "us", "get", "got",
}


def _stem(word: str) -> str:
    """Crude suffix stripping. Not linguistics -- just enough to unify plurals."""
    if len(word) > 4 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 3 and word.endswith("es"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, drop stop words and stems what is left."""
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = {_stem(w) for w in cleaned.split()}
    return {t for t in tokens if t not in STOP_WORDS and len(t) > 2}


def char_ngrams(text: str, n: int = NGRAM_SIZE) -> set[str]:
    """Character n-grams of the stemmed token stream, space-joined."""
    tokens = sorted(tokenize(text))
    if not tokens:
        return set()
    joined = " ".join(tokens)
    if len(joined) <= n:
        return {joined}
    return {joined[i:i + n] for i in range(len(joined) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _dice(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    total = len(a) + len(b)
    return 2 * len(a & b) / total if total else 0.0


def similarity(text_a: str, text_b: str) -> float:
    """0-100 similarity between two complaint texts."""
    token_score = _jaccard(tokenize(text_a), tokenize(text_b))
    gram_score = _dice(char_ngrams(text_a), char_ngrams(text_b))
    return round(100.0 * max(token_score, gram_score), 1)


def _ward(db: Session, complaint: models.Complaint) -> Optional[str]:
    if not complaint.location_id:
        return None
    location = db.query(models.Location).filter_by(id=complaint.location_id).first()
    return location.ward if location else None


def find_duplicates(
    db: Session,
    complaint: models.Complaint,
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[dict]:
    """
    Other stored complaints that describe the same problem.

    Complaints recorded in a different ward are excluded outright -- a
    pothole report in Kothrud is not a duplicate of one in Baner.
    """
    ward = _ward(db, complaint)
    candidates = (
        db.query(models.Complaint)
        .filter(models.Complaint.id != complaint.id)
        .order_by(models.Complaint.id)
    )

    matches: list[dict] = []
    for other in candidates.all():
        other_ward = _ward(db, other)
        if ward and other_ward and ward != other_ward:
            continue

        score = similarity(complaint.text or "", other.text or "")
        if score < threshold:
            continue

        matches.append({
            "complaint_id": other.id,
            "text": other.text,
            "location": other_ward,
            "category": other.category,
            "severity": other.severity,
            "similarity": score,
        })

    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return matches


def _severity_score(complaints: Iterable[models.Complaint]) -> float:
    complaints = list(complaints)
    if not complaints:
        return 0.0
    total = sum(SEVERITY_SCORES.get((c.severity or "").capitalize(), DEFAULT_SEVERITY_SCORE)
                for c in complaints)
    return round(total / len(complaints), 2)


def _refresh_cluster_stats(db: Session, cluster: models.IssueCluster) -> None:
    members = db.query(models.Complaint).filter_by(cluster_id=cluster.id).all()
    cluster.complaint_count = len(members)
    cluster.avg_severity_score = _severity_score(members)


def cluster_all_unclustered(
    db: Session,
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[models.IssueCluster]:
    """
    Group every un-clustered complaint into an `IssueCluster`.

    Clustering is scoped to a (ward, category) pair first -- a pothole report
    and a water complaint in the same ward are different problems -- and only
    then compared by text similarity. An unmatched complaint opens a new
    cluster. Previously created clusters are left alone, so the function is
    safe to re-run as new complaints arrive.
    """
    unclustered = (
        db.query(models.Complaint)
        .filter(models.Complaint.cluster_id.is_(None))
        .order_by(models.Complaint.id)
        .all()
    )
    if not unclustered:
        return []

    created: list[models.IssueCluster] = []
    clusters: list[models.IssueCluster] = db.query(models.IssueCluster).all()

    for complaint in unclustered:
        ward = _ward(db, complaint) or "Unassigned"
        category = complaint.category or "Other"

        # Only clusters in the same ward+category can possibly match.
        same_scope = [c for c in clusters if c.ward == ward and c.category == category]
        assigned = None

        for cluster in same_scope[:CLUSTER_MATCH_CANDIDATES]:
            members = db.query(models.Complaint).filter_by(cluster_id=cluster.id).all()
            if any(similarity(complaint.text or "", m.text or "") >= threshold for m in members):
                assigned = cluster
                break

        if assigned is None:
            assigned = models.IssueCluster(
                label=f"{category} - {ward} #{len(same_scope) + 1}",
                category=category,
                ward=ward,
                complaint_count=0,
                avg_severity_score=0.0,
            )
            db.add(assigned)
            db.flush()  # need an id for the FK below
            clusters.append(assigned)
            created.append(assigned)

        complaint.cluster_id = assigned.id
        db.flush()
        _refresh_cluster_stats(db, assigned)

    db.commit()
    return created
