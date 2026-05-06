-- Add performance indexes to documents table
CREATE INDEX IF NOT EXISTS "documents_status_submitted_at_idx"
    ON "documents" ("status", "submitted_at");

CREATE INDEX IF NOT EXISTS "documents_device_id_idx"
    ON "documents" ("device_id");
