CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE violation_events (
    event_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id           VARCHAR(64) NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    violation_types     TEXT[] NOT NULL,
    snapshot_url        TEXT,
    confidence_scores   JSONB NOT NULL DEFAULT '{}',
    bounding_boxes      JSONB NOT NULL DEFAULT '[]',
    processing_latency  INTEGER NOT NULL,
    inference_metadata  JSONB NOT NULL DEFAULT '{}',
    upload_status       VARCHAR(16) NOT NULL DEFAULT 'success',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_violation_events_timestamp ON violation_events (timestamp DESC);
CREATE INDEX idx_violation_events_camera_timestamp ON violation_events (camera_id, timestamp DESC);
