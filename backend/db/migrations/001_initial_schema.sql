-- PPE Compliance Monitoring System
-- Migration: 001_initial_schema
-- Creates the violation_events table with core fields, extended analytics fields, and indexes.

-- Enable pgcrypto for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS violation_events (
    -- Core fields
    event_id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id           VARCHAR(64) NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    violation_types     TEXT[]      NOT NULL,
    snapshot_url        TEXT,
    confidence_scores   JSONB       NOT NULL DEFAULT '{}',
    upload_status       VARCHAR(16) NOT NULL DEFAULT 'success',  -- success | pending_retry | failed

    -- Extended fields for performance evaluation and AI accuracy analysis (Requirements 4.3)
    -- bounding_boxes: coordinates of detected violation objects for frontend overlay and offline analysis
    bounding_boxes      JSONB       NOT NULL DEFAULT '[]',
    -- processing_latency: time spent calling Yandex Vision API, in milliseconds
    processing_latency  INTEGER     NOT NULL,
    -- raw_api_response: complete untruncated Yandex Vision API JSON response for data replay and offline experiments
    raw_api_response    JSONB       NOT NULL DEFAULT '{}',

    -- Metadata
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for query performance (Requirements 4.7)
CREATE INDEX IF NOT EXISTS idx_violations_camera_id
    ON violation_events (camera_id);

CREATE INDEX IF NOT EXISTS idx_violations_timestamp
    ON violation_events (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_violations_types
    ON violation_events USING GIN (violation_types);
