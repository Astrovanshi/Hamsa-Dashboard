-- Migration 0005: preserve the type of actor making an identity decision.
-- Existing reviews predate explicit actor typing; retain that uncertainty.

ALTER TABLE security_identifier_revision_review
    ADD COLUMN IF NOT EXISTS reviewer_actor_type VARCHAR;

UPDATE security_identifier_revision_review
SET reviewer_actor_type = CASE
    WHEN reviewed_by IS NULL THEN NULL
    ELSE 'legacy_unknown'
END
WHERE reviewer_actor_type IS NULL;
