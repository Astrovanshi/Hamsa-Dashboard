from dataclasses import replace
from datetime import date, datetime
import unittest

from hamsa.domain.identity import (
    AmbiguousIdentityMapping,
    SecurityIdentifierMapping,
    resolve_isin,
)
from hamsa.domain.lifecycle import EntityRelationship, RelationshipType, ReviewStatus


class SecurityHistoryTests(unittest.TestCase):
    def test_routine_isin_change_keeps_issuer_and_preserves_security_history(self):
        mappings = (
            SecurityIdentifierMapping(
                "security-old", "issuer-stable", "INE000A01010", date(2000, 1, 1), date(2023, 12, 31), "doc-old", ReviewStatus.APPROVED
            ),
            SecurityIdentifierMapping(
                "security-new", "issuer-stable", "INE000A01028", date(2024, 1, 1), None, "doc-new", ReviewStatus.APPROVED
            ),
        )
        old = resolve_isin(mappings, isin="INE000A01010", on_date=date(2023, 12, 1))
        new = resolve_isin(mappings, isin="INE000A01028", on_date=date(2024, 1, 2))
        self.assertEqual(old.issuer_entity_id, "issuer-stable")
        self.assertEqual(new.issuer_entity_id, "issuer-stable")
        self.assertNotEqual(old.security_id, new.security_id)
        self.assertIsNone(resolve_isin(mappings, isin="INE000A01010", on_date=date(2024, 1, 2)))

    def test_unreviewed_or_conflicting_historical_mapping_is_not_guessed(self):
        pending = SecurityIdentifierMapping(
            "security-1", "issuer-1", "INE000A01010", date(2020, 1, 1), None, "doc", ReviewStatus.PENDING
        )
        self.assertIsNone(resolve_isin((pending,), isin="INE000A01010", on_date=date(2024, 1, 1)))
        ambiguous = (
            SecurityIdentifierMapping("sec-a", "issuer-a", "INE000A01010", date(2020, 1, 1), None, "doc-a", ReviewStatus.APPROVED),
            SecurityIdentifierMapping("sec-b", "issuer-b", "INE000A01010", date(2020, 1, 1), None, "doc-b", ReviewStatus.APPROVED),
        )
        with self.assertRaises(AmbiguousIdentityMapping):
            resolve_isin(ambiguous, isin="INE000A01010", on_date=date(2024, 1, 1))

    def test_reorganisation_relationship_is_explicit_reviewed_and_keeps_entities_distinct(self):
        relation = EntityRelationship(
            relationship_id="rel-1",
            from_entity_id="predecessor",
            to_entity_id="successor",
            relationship_type=RelationshipType.SUCCESSOR_OF,
            effective_date=date(2024, 1, 1),
            announced_at=datetime(2023, 12, 1),
            source_document_id="scheme-filing",
            review_status=ReviewStatus.PENDING,
        )
        self.assertNotEqual(relation.from_entity_id, relation.to_entity_id)
        self.assertEqual(relation.review_status, ReviewStatus.PENDING)
        # Frozen slots intentionally disallow mutation in place; an approved
        # relationship is represented by a distinct appended revision.
        reviewed = replace(relation, relationship_id="rel-2", review_status=ReviewStatus.APPROVED)
        self.assertNotEqual(relation.relationship_id, reviewed.relationship_id)
        self.assertEqual((reviewed.from_entity_id, reviewed.to_entity_id), ("predecessor", "successor"))


if __name__ == "__main__":
    unittest.main()
