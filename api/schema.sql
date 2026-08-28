-- Database Schema for Borges Knowledge Graph API
-- PostgreSQL 12+

-- Table: pipeline_runs
-- Track each pipeline execution (process_id is the primary identifier)
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- This is the process_id
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,  -- When processing actually began
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Run Configuration (all files must be same type)
    file_type VARCHAR(10) NOT NULL CHECK (file_type IN ('pdf', 'xml')),
    total_files INTEGER NOT NULL DEFAULT 0,  -- Count of uploaded files

    -- Model Configuration (fixed defaults, not client-configurable)
    extraction_model VARCHAR(100) NOT NULL DEFAULT 'gpt-4.1',
    merging_model VARCHAR(100) NOT NULL DEFAULT 'gpt-4.1-mini',

    -- Current Pipeline Step (clear visibility of which step)
    current_step VARCHAR(50) NOT NULL DEFAULT 'pending'
        CHECK (current_step IN (
            'pending',              -- Waiting to start
            'text_extraction',      -- Extracting text from PDF/XML
            'entity_extraction',    -- LLM entity extraction from chunks
            'vector_indexing',      -- Uploading to Qdrant vector DB
            'csv_merging',          -- Merging all document CSVs
            'entity_deduplication', -- Iterative entity deduplication
            'normalization',        -- Creating normalized entity tables
            'uploading_results',    -- Uploading final files to S3
            'completed',            -- Successfully finished
            'failed'                -- Pipeline failed
        )),

    -- Step-specific progress (what's happening within current step)
    step_detail VARCHAR(500),  -- e.g., "Processing document 3/10: Borges_Stories.pdf"

    -- Overall Progress
    total_documents INTEGER DEFAULT 0,
    processed_documents INTEGER DEFAULT 0,
    total_entities INTEGER DEFAULT 0,
    unique_entities INTEGER DEFAULT NULL,

    -- Prompt Configuration (which prompt version was used)
    prompt_version_id UUID REFERENCES extraction_prompts(id),

    -- Error Handling
    error_message TEXT,

    -- S3 Output Keys (only final files are stored)
    unique_entities_s3_key VARCHAR(1000),     -- S3 path for unique_entities.csv
    references_s3_key VARCHAR(1000)           -- S3 path for references.csv
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_current_step ON pipeline_runs(current_step);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_created_at ON pipeline_runs(created_at DESC);

-- Table: input_files
-- Track input files per run (for status display only, not stored in S3)
CREATE TABLE IF NOT EXISTS input_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,

    -- File Information
    original_filename VARCHAR(500) NOT NULL,
    file_size_bytes BIGINT NOT NULL,

    -- Processing Status
    status VARCHAR(30) NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending',      -- Not yet processed
            'processing',   -- Currently being processed
            'completed',    -- Successfully processed
            'failed'        -- Processing failed for this file
        )),

    -- Per-file metrics
    entities_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_input_files_run_id ON input_files(run_id);

-- Table: pipeline_status_updates
-- Detailed status log (for detailed status endpoint)
CREATE TABLE IF NOT EXISTS pipeline_status_updates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    step VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    details JSONB  -- Additional context (document name, entity count, etc.)
);

CREATE INDEX IF NOT EXISTS idx_status_updates_run_id ON pipeline_status_updates(run_id);
CREATE INDEX IF NOT EXISTS idx_status_updates_created_at ON pipeline_status_updates(created_at DESC);

-- Table: extraction_prompts
-- Store custom prompts with version tracking
CREATE TABLE IF NOT EXISTS extraction_prompts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Version tracking
    version INTEGER NOT NULL UNIQUE,
    is_active BOOLEAN DEFAULT FALSE,  -- Only one can be active

    -- Prompt content
    prompt_name VARCHAR(200) NOT NULL,
    prompt_content TEXT NOT NULL,

    -- Audit
    created_by VARCHAR(200),  -- Optional: track who made changes
    change_notes TEXT,        -- Optional: describe changes

    -- Hash for quick comparison
    content_hash VARCHAR(64) NOT NULL  -- SHA256 of prompt_content
);

CREATE INDEX IF NOT EXISTS idx_extraction_prompts_version ON extraction_prompts(version DESC);

-- Ensure only one active prompt (partial unique index)
CREATE UNIQUE INDEX IF NOT EXISTS idx_single_active_prompt
    ON extraction_prompts(is_active)
    WHERE is_active = TRUE;

-- Database Functions

-- Function to get the current active prompt
CREATE OR REPLACE FUNCTION get_active_extraction_prompt()
RETURNS TABLE(id UUID, version INTEGER, prompt_content TEXT) AS $$
BEGIN
    RETURN QUERY
    SELECT ep.id, ep.version, ep.prompt_content
    FROM extraction_prompts ep
    WHERE ep.is_active = TRUE
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function to activate a prompt version (deactivates others)
CREATE OR REPLACE FUNCTION activate_prompt_version(prompt_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    UPDATE extraction_prompts SET is_active = FALSE WHERE is_active = TRUE;
    UPDATE extraction_prompts SET is_active = TRUE WHERE id = prompt_id;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Add foreign key constraint to pipeline_runs (after extraction_prompts is created)
-- Note: This is already defined in the CREATE TABLE statement above with REFERENCES

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'Database schema created successfully!';
    RAISE NOTICE 'Tables created: pipeline_runs, input_files, pipeline_status_updates, extraction_prompts';
END $$;
