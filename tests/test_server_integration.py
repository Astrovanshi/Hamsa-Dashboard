"""Integration tests for HAMSA Analytical REST Server."""

import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hamsa.server.app import HamsaServer, make_handler
from http.server import HTTPServer


class HamsaServerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        test_duck = Path(cls.tmp_dir.name) / "test_srv.duckdb"
        test_sql = Path(cls.tmp_dir.name) / "test_srv.sqlite3"
        shutil.copy2(ROOT / "hamsa_terminal.duckdb", test_duck)
        shutil.copy2(ROOT / "hamsa_terminal_reviews.sqlite3", test_sql)

        cls.backend = HamsaServer(test_duck, test_sql)
        cls.server = HTTPServer(("127.0.0.1", 0), make_handler(cls.backend))
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.backend.close()
        try:
            cls.tmp_dir.cleanup()
        except Exception:
            pass

    def _get(self, path: str):
        req = urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}")
        return json.loads(req.read().decode("utf-8"))

    def _post(self, path: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        res = urllib.request.urlopen(req)
        return json.loads(res.read().decode("utf-8"))

    def test_health_endpoint(self):
        data = self._get("/health")
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["schemaVersion"], 10)
        self.assertEqual(data["admittedIssuers"], 2395)

    def test_market_radar_endpoint(self):
        radar = self._get("/api/radar")
        self.assertEqual(radar["exchange"], "NSE")
        self.assertGreater(radar["totalTurnoverCr"], 0)
        self.assertGreaterEqual(len(radar["dislocations"]), 1)

    def test_companies_and_single_company_endpoints(self):
        comps = self._get("/api/companies?limit=5")
        self.assertEqual(len(comps), 5)
        poly = self._get("/api/companies/POLYCAB")
        self.assertEqual(poly["identity"]["symbol"], "POLYCAB")
        self.assertGreater(len(poly["financials"]), 0)
        self.assertEqual(len(poly["engineFindings"]), 5)

    def test_watchlist_and_note_write_endpoints(self):
        wl = self._post(
            "/api/watchlist",
            {"entityId": "issuer-polycab", "status": "watch", "author": "unit-test"},
        )
        self.assertEqual(wl["status"], "success")
        self.assertTrue(wl["revision_id"].startswith("watch-"))

        note = self._post(
            "/api/notes",
            {"entityId": "issuer-polycab", "thesis": "Unit test research thesis", "author": "unit-test"},
        )
        self.assertEqual(note["status"], "success")
        self.assertTrue(note["revision_id"].startswith("note-"))


if __name__ == "__main__":
    unittest.main()