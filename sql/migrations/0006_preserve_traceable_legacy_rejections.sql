-- Migration 0006: restore traceable legacy rejections without changing v4.
-- v4 conservatively made decisions without a locator pending.  A rejection
-- never grants admission, so an existing reviewer and timestamp are enough
-- to retain its historical denial while an approval still requires a locator.

UPDATE security_identifier_revision_review AS review
SET review_status = 'rejected',
    reviewed_by = identifier.reviewed_by,
    reviewer_actor_type = 'legacy_unknown',
    reviewed_at = identifier.reviewed_at,
    rationale = 'Restored traceable legacy rejection by migration v6.'
FROM security_identifier_revision AS identifier
WHERE review.identifier_revision_id = identifier.identifier_revision_id
  AND review.review_status = 'pending'
  AND identifier.mapping_review_status = 'rejected'
  AND identifier.reviewed_by IS NOT NULL
  AND identifier.reviewed_at IS NOT NULL;
