"""
ORM models for Member 2's tables.

`users` and `complaints` are also touched by Member 1 (auth.py /
complaints.py) — column names here MUST match docs/API_CONTRACT.md.
Everything else (locations, issue_clusters, infrastructure, demographics,
investments, projects, recommendations, impact_metrics) is owned by
Member 2.
"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON, Text
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    """
    A CivicAI account, and the single source of truth for authentication.

    This table started life as a *mirror* of `backend/auth.py`'s process-local
    dict, holding only enough to attribute complaints to a stable identity
    (`auth_key`, derived from the email). It is now the real account table:
    `backend/auth.py` reads and writes these rows through SQLAlchemy, so an
    account survives a restart and a second process sees the same users.

    `auth_key` is still the stable identity used for complaint ownership. It is
    derived from the email -- the one field that survives a restart -- and is
    unique, so two people can never share a row. `id` is now a real SERIAL from
    the database rather than a counter that restarted at 1 every process, which
    was the original reason the two could be confused.

    `password_hash` is nullable because rows created before auth was
    database-backed have no password. Such a row cannot log in: it is a
    complaint-ownership record for an account that lived in the old
    process-local dict and is no longer reachable. It is never silently
    promoted to a usable account. See scripts/migrate_add_password_hash.py.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(120))
    email = Column(String(255), unique=True, index=True)
    # Stable external identity key for complaint ownership. Set on every row
    # auth creates, and backfilled onto legacy rows by
    # scripts/migrate_add_auth_key.py.
    auth_key = Column(String(255), unique=True, index=True, nullable=True)
    # bcrypt hash. Never a plaintext password, and never selected into a
    # response model.
    password_hash = Column(String(255), nullable=True)
    role = Column(String(20), default="citizen")  # citizen | officer
    created_at = Column(DateTime, default=datetime.utcnow)

    complaints = relationship("Complaint", back_populates="user")


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True)
    ward = Column(String(120), index=True)          # e.g. "Kothrud"
    area = Column(String(120))
    city = Column(String(80), default="Pune")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    complaints = relationship("Complaint", back_populates="location")
    demographics = relationship("Demographics", back_populates="location", uselist=False)
    infrastructure = relationship("Infrastructure", back_populates="location")


class Complaint(Base):
    """
    Mirrors the JSON contract Member 1 -> Member 2:
    complaint_id, text, language, category, location, severity, urgency,
    affected_group, issue_summary, recommended_action.
    """
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    cluster_id = Column(Integer, ForeignKey("issue_clusters.id"), nullable=True)

    text = Column(Text, nullable=False)
    language = Column(String(30))
    # Raw free-text location exactly as the citizen typed it. `location_id` is
    # only populated when the text resolves to a known ward, so without this
    # column an unrecognised location would be silently discarded.
    location_text = Column(String(200), nullable=True)
    category = Column(String(80), index=True)
    severity = Column(String(20))       # Low | Medium | High
    urgency = Column(String(20))        # Low | Medium | High
    affected_group = Column(String(120))
    issue_summary = Column(Text)
    recommended_action = Column(Text)

    priority_score = Column(Float, nullable=True)
    priority_level = Column(String(20), nullable=True)
    status = Column(String(30), default="Submitted")

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="complaints")
    location = relationship("Location", back_populates="complaints")
    cluster = relationship("IssueCluster", back_populates="complaints")


class IssueCluster(Base):
    __tablename__ = "issue_clusters"

    id = Column(Integer, primary_key=True)
    label = Column(String(200))              # "Issue Cluster #27"
    category = Column(String(80))
    ward = Column(String(120))
    complaint_count = Column(Integer, default=0)
    avg_severity_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    complaints = relationship("Complaint", back_populates="cluster")


class Infrastructure(Base):
    """Roads / water / electricity / sanitation / healthcare / education gap data."""
    __tablename__ = "infrastructure"

    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"))
    category = Column(String(80))            # e.g. "Road Infrastructure"
    coverage_score = Column(Float)           # 0-100, higher = better served
    gap_score = Column(Float)                # 0-100, higher = bigger gap
    source = Column(String(200))             # dataset provenance
    updated_at = Column(DateTime, default=datetime.utcnow)

    location = relationship("Location", back_populates="infrastructure")


class Demographics(Base):
    __tablename__ = "demographics"

    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), unique=True)
    population = Column(Integer)
    population_density = Column(Float, nullable=True)
    literacy_rate = Column(Float, nullable=True)
    source = Column(String(200))
    updated_at = Column(DateTime, default=datetime.utcnow)

    location = relationship("Location", back_populates="demographics")


class Investment(Base):
    __tablename__ = "investments"

    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"))
    category = Column(String(80))
    amount_allocated = Column(Float, default=0.0)
    project_status = Column(String(50))      # Planned | Ongoing | Completed
    year = Column(Integer, nullable=True)
    source = Column(String(200))


class Project(Base):
    """Created when an officer approves a recommendation (Member 3 writes here)."""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    recommendation_id = Column(Integer, ForeignKey("recommendations.id"), nullable=True)
    title = Column(String(200))
    # What the officer decided should be done, in their words. Distinct from
    # `title` (a short label) and from the engine's own `Recommendation.reason`,
    # which is never overwritten by an officer decision.
    description = Column(Text, nullable=True)
    status = Column(String(30), default="Under Review")  # Under Review|Approved|In Progress|Completed
    officer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # The decisions behind this project, oldest first. A project and its ledger
    # are written in the same transaction, so this is never partially filled.
    decisions = relationship(
        "OfficerDecision",
        back_populates="project",
        order_by="OfficerDecision.created_at",
    )

    # Impact measurement (only for completed projects)
    impact = relationship(
        "ProjectImpact",
        back_populates="project",
        uselist=False,
    )


class OfficerDecision(Base):
    """
    Append-only record of what an officer did about a recommendation.

    Needed because `projects` alone cannot carry the whole workflow:

      * a REJECTION creates no project, so it has nowhere to be recorded;
      * a MODIFY changes a plan without changing the engine's recommendation,
        and the officer's wording must be kept verbatim;
      * a status progression is a decision an auditor needs to see.

    `recommendations` rows are engine output and are refreshed in place by
    `recommendations.generate_all`, so an officer's decision cannot live there.
    Every field on this table is therefore the officer's, written once and never
    rewritten by the engine.

    No credential of any kind is stored: the officer is identified by
    `officer_id`, a foreign key to the `users` mirror row, never by a token,
    password or auth-module id.
    """
    __tablename__ = "officer_decisions"

    id = Column(Integer, primary_key=True)
    # Nullable so a decision that outlives its recommendation is still kept.
    # Deleting a recommendation is prevented rather than relied upon.
    recommendation_id = Column(Integer, ForeignKey("recommendations.id"), nullable=True)
    # Set when the decision produced or changed a project; NULL for a rejection.
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    officer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Approved | Modified | Rejected | Status Changed
    decision = Column(String(30))
    # The officer's own words. Required for a rejection, optional otherwise.
    reason = Column(Text, nullable=True)
    # The plan as it stood at decision time, so a later edit is still auditable.
    action_snapshot = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="decisions")
    recommendation = relationship("Recommendation")
    officer = relationship("User")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, ForeignKey("issue_clusters.id"))
    action = Column(String(300))
    reason = Column(Text)
    evidence = Column(JSON)          # {"related_complaints": 47, "infra_gap": "High", ...}
    priority_score = Column(Float)
    estimated_affected_population = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ImpactMetric(Base):
    __tablename__ = "impact_metrics"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    metric_name = Column(String(120))
    value = Column(Float)
    recorded_at = Column(DateTime, default=datetime.utcnow)


class ProjectImpact(Base):
    """
    Impact measurement for a completed project.

    A project progresses: Approved -> In Progress -> Completed -> Impact recorded.
    Only a Completed project may have an impact record. An officer records observed
    measurements (not causal claims) after the work is finished.

    Calculated fields (before/after complaint counts, severity averages) are
    derived from actual complaint data where the time boundary permits. Where it
    does not, the officer provides a manual measurement with notes.
    """
    __tablename__ = "project_impacts"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), unique=True, nullable=False)

    # Complaint-based measurements (calculated where possible)
    before_complaint_count = Column(Integer, nullable=True)
    after_complaint_count = Column(Integer, nullable=True)
    complaints_resolved = Column(Integer, nullable=True)

    # Severity/demand measurements (calculated or manual)
    before_avg_severity_score = Column(Float, nullable=True)
    after_avg_severity_score = Column(Float, nullable=True)
    before_avg_priority_score = Column(Float, nullable=True)
    after_avg_priority_score = Column(Float, nullable=True)

    # Measurement metadata
    measurement_period_start = Column(DateTime, nullable=True)
    measurement_period_end = Column(DateTime, nullable=True)

    # Officer input
    officer_notes = Column(Text, nullable=True)
    recorded_by_officer_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="impact")
    recorded_by = relationship("User")
