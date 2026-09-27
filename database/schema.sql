-- CivicAI schema (Member 2 owned, shared tables: users, complaints)
-- Run with: psql -U <db-user> -d civicai -f schema.sql
-- Or just call init_db() in db.py to let SQLAlchemy create everything.

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120),
    email VARCHAR(255) UNIQUE,
    -- Stable identity of the mirrored auth account. The auth module's integer
    -- id restarts from 1 on every process restart, so it is never used here.
    auth_key VARCHAR(255) UNIQUE,
    role VARCHAR(20) DEFAULT 'citizen',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS locations (
    id SERIAL PRIMARY KEY,
    ward VARCHAR(120),
    area VARCHAR(120),
    city VARCHAR(80) DEFAULT 'Pune',
    latitude FLOAT,
    longitude FLOAT
);

CREATE TABLE IF NOT EXISTS issue_clusters (
    id SERIAL PRIMARY KEY,
    label VARCHAR(200),
    category VARCHAR(80),
    ward VARCHAR(120),
    complaint_count INTEGER DEFAULT 0,
    avg_severity_score FLOAT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS complaints (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    location_id INTEGER REFERENCES locations(id),
    cluster_id INTEGER REFERENCES issue_clusters(id),
    text TEXT NOT NULL,
    language VARCHAR(30),
    location_text VARCHAR(200),
    category VARCHAR(80),
    severity VARCHAR(20),
    urgency VARCHAR(20),
    affected_group VARCHAR(120),
    issue_summary TEXT,
    recommended_action TEXT,
    priority_score FLOAT,
    priority_level VARCHAR(20),
    status VARCHAR(30) DEFAULT 'Submitted',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_complaints_category ON complaints(category);

CREATE TABLE IF NOT EXISTS infrastructure (
    id SERIAL PRIMARY KEY,
    location_id INTEGER REFERENCES locations(id),
    category VARCHAR(80),
    coverage_score FLOAT,
    gap_score FLOAT,
    source VARCHAR(200),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS demographics (
    id SERIAL PRIMARY KEY,
    location_id INTEGER UNIQUE REFERENCES locations(id),
    population INTEGER,
    population_density FLOAT,
    literacy_rate FLOAT,
    source VARCHAR(200),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS investments (
    id SERIAL PRIMARY KEY,
    location_id INTEGER REFERENCES locations(id),
    category VARCHAR(80),
    amount_allocated FLOAT DEFAULT 0,
    project_status VARCHAR(50),
    year INTEGER,
    source VARCHAR(200)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id SERIAL PRIMARY KEY,
    cluster_id INTEGER REFERENCES issue_clusters(id),
    action VARCHAR(300),
    reason TEXT,
    evidence JSONB,
    priority_score FLOAT,
    estimated_affected_population INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    recommendation_id INTEGER REFERENCES recommendations(id),
    title VARCHAR(200),
    status VARCHAR(30) DEFAULT 'Under Review',
    officer_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS impact_metrics (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    metric_name VARCHAR(120),
    value FLOAT,
    recorded_at TIMESTAMP DEFAULT NOW()
);
