from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GitIgnoreTests(unittest.TestCase):
    def ignored(self, path):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=ROOT,
            check=False,
        )
        return result.returncode == 0

    def test_sensitive_and_generated_paths_are_ignored(self):
        for path in (
            "data/raw/example.csv",
            "data/processed/cache.parquet",
            "configs/real_eod.local.json",
            "local.duckdb",
            "state.sqlite3",
            ".env",
            ".env.local",
            "credentials.json",
            "id_ed25519",
            "certificate.pfx",
            "certificate.crt",
            "logs/run.log",
            "src/hamsa/__pycache__/module.pyc",
            ".venv/pyvenv.cfg",
        ):
            with self.subTest(path=path):
                self.assertTrue(self.ignored(path), f"expected ignored: {path}")

    def test_source_schemas_docs_examples_and_synthetic_tests_remain_trackable(self):
        for path in (
            ".env.example",
            "configs/policies.example.toml",
            "configs/real_eod.example.json",
            "sql/duckdb_schema.sql",
            "docs/architecture.md",
            "tests/test_point_in_time.py",
            "src/hamsa/domain/financials.py",
        ):
            with self.subTest(path=path):
                self.assertFalse(self.ignored(path), f"unexpectedly ignored: {path}")


if __name__ == "__main__":
    unittest.main()
