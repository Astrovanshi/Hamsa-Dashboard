from pathlib import Path
import sqlite3
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SchemaContractTests(unittest.TestCase):
    def test_sqlite_schema_creates_append_only_review_ledger(self):
        schema = (ROOT / "sql" / "sqlite_schema.sql").read_text(encoding="utf-8")
        with sqlite3.connect(":memory:") as connection:
            connection.executescript(schema)
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertIn("filter_review", tables)
            self.assertIn("filter_review_evidence", tables)
            connection.execute(
                "INSERT INTO filter_review VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("r1", "entity-1", "gap", "Unproven", "reviewer", "2024-01-01T00:00:00+05:30", "needs evidence", None),
            )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute("UPDATE filter_review SET status='Pass' WHERE review_id='r1'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute("DELETE FROM filter_review WHERE review_id='r1'")

    def test_analytical_schema_has_lifecycle_pit_provenance_and_action_contracts(self):
        schema = (ROOT / "sql" / "duckdb_schema.sql").read_text(encoding="utf-8")
        required_tables = (
            "issuer_entity", "equity_security", "security_identifier_revision",
            "entity_relationship_revision", "security_relationship_revision",
            "exchange_listing_revision", "exchange_trading_session",
            "source_document_revision", "source_document_sighting",
            "financial_observation_revision", "eod_price_observation_revision",
            "delivery_observation_revision", "corporate_action_event_revision",
            "adjustment_factor_revision", "adjusted_price_series_revision",
            "venue_policy_revision", "observation_quarantine",
            "unit_conversion_rule_revision", "metric_staleness_policy_revision",
        )
        for table in required_tables:
            with self.subTest(table=table):
                self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
        for column in (
            "period_end DATE NOT NULL",
            "source_document_date DATE NOT NULL",
            "publication_date DATE NOT NULL",
            "ingestion_timestamp TIMESTAMPTZ NOT NULL",
            "parser_version VARCHAR NOT NULL",
            "extraction_timestamp TIMESTAMPTZ NOT NULL",
            "extraction_locator VARCHAR NOT NULL",
            "formula_version VARCHAR",
            "publicly_available_at TIMESTAMPTZ",
        ):
            with self.subTest(column=column):
                self.assertIn(column, schema)
        self.assertIn("'public_as_of', 'hamsa_known_as_of', 'retrospective'", schema)
        self.assertIn("price_factor DECIMAL", schema)
        self.assertIn("volume_factor DECIMAL", schema)

if __name__ == "__main__":
    unittest.main()
