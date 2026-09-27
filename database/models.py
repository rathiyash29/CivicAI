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
    Mirror of a `backend/auth.py` user.

    `auth.py` still keeps users in a process-local dict, and its integer ids
    restart from 1 whenever the process restarts. That integer is therefore NOT
    a stable identity: a later account can be handed an id an earlier account
    already used, and keying complaint ownership on it lets that later account
    inherit the earlier account's complaints.

    `auth_key` is the stable identity. It is derived from a value that survives
    a restart (the account's email) and is unique, so two different people can
    never share a mirror row no matter what the auth counter does. `id` stays a
    plain SERIAL owned by the database.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(120))
    email = Column(String(255), unique=True, index=True)
    # Stable external identity key for the auth mirror. Nullable so a row that
    # predates this column still loads; see scripts/migrate_add_auth_key.py.
    auth_key = Column(String(255), unique=True, index=True, nullable=True)
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
    status = Column(String(30), default="Under Review")  # Under Review|Approved|In Progress|Completed
    officer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


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
