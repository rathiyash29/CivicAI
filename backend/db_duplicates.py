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


def reconcile_cluster_stats(
    db: Session,
    commit: bool = True,
) -> list[dict]:
    """
    Recompute every cluster's stored statistics from its actual members.

    `IssueCluster.complaint_count` and `avg_severity_score` are a denormalised
    cache of the complaints pointing at the cluster. `_refresh_cluster_stats`
    keeps it correct while complaints are assigned, but nothing reconciles it
    when membership changes by another route -- a bulk re-cluster, a data reload
    that repoints `cluster_id`, or a row inserted outside the request path. A
    cluster whose members have all moved away then keeps claiming complaints it
    no longer has, and that stale number is read back by the priority engine.

    This walks every cluster in id order -- deterministic, and a no-op for
    clusters that are already correct -- and re-derives both fields from the
    members actually assigned. A cluster with no members ends at 0 complaints
    and 0.0 average severity rather than keeping its last known figures.

    Nothing is deleted: an orphaned cluster is a real historical group that
    simply has no members right now, and its identity is still referenced by
    the recommendations table.
    """
    before: dict[int, tuple] = {}
    clusters = db.query(models.IssueCluster).order_by(models.IssueCluster.id).all()
    for cluster in clusters:
        before[cluster.id] = (cluster.complaint_count, cluster.avg_severity_score)

    for cluster in clusters:
        _refresh_cluster_stats(db, cluster)

    results = []
    for cluster in clusters:
        old_count, old_severity = before[cluster.id]
        results.append({
            "cluster_id": cluster.id,
            "ward": cluster.ward,
            "category": cluster.category,
            "members_before": old_count,
            "members_after": cluster.complaint_count,
            "avg_severity_before": old_severity,
            "avg_severity_after": cluster.avg_severity_score,
            "changed": (old_count != cluster.complaint_count
                        or old_severity != cluster.avg_severity_score),
        })

    if commit:
        db.commit()
    else:
        db.flush()
    return results


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
        cluster, is_new = assign_cluster(db, complaint, threshold=threshold)
        if is_new:
            clusters.append(cluster)
            created.append(cluster)

    db.commit()
    return created


def assign_cluster(
    db: Session,
    complaint: models.Complaint,
    threshold: float = SIMILARITY_THRESHOLD,
    commit: bool = False,
) -> tuple[models.IssueCluster, bool]:
    """
    Put a single complaint into a cluster, creating one if nothing matches.

    This is the request-path counterpart to `cluster_all_unclustered`. It
    shares the same matching rule -- scope to (ward, category) first, then
    compare by text similarity -- but it touches one complaint instead of
    scanning the whole table, and it does not commit, so the caller controls
    the transaction.

    Returns (cluster, created_new_cluster).
    """
    if complaint.cluster_id:
        existing = (
            db.query(models.IssueCluster)
            .filter_by(id=complaint.cluster_id)
            .first()
        )
        if existing is not None:
            # Already clustered, so the assignment itself is a no-op -- but the
            # cluster's cached statistics may still be out of date, and this is
            # the one code path that is guaranteed to be looking at it.
            _refresh_cluster_stats(db, existing)
            return existing, False

    # Note: reassignment that happens *outside* this function (a bulk re-cluster
    # or a data reload repointing `cluster_id`) leaves the cluster the complaint
    # left still counting it. That path has no way to know the previous owner
    # from here, which is why `reconcile_cluster_stats` exists.

    ward = _ward(db, complaint) or "Unassigned"
    category = complaint.category or "Other"

    same_scope = (
        db.query(models.IssueCluster)
        .filter_by(ward=ward, category=category)
        .order_by(models.IssueCluster.id)
        .limit(CLUSTER_MATCH_CANDIDATES)
        .all()
    )

    assigned = None
    for cluster in same_scope:
        members = db.query(models.Complaint).filter_by(cluster_id=cluster.id).all()
        if any(similarity(complaint.text or "", m.text or "") >= threshold
               for m in members):
            assigned = cluster
            break

    created = False
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
        created = True

    complaint.cluster_id = assigned.id
    db.flush()
    _refresh_cluster_stats(db, assigned)

    if commit:
        db.commit()

    return assigned, created
