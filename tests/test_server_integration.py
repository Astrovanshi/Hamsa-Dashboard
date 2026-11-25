"""Integration tests for HAMSA Analytical REST Server."""

import json
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

from hamsa.server.app import run_server


class HamsaServerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = run_server(port=0)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

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
        self.assertEqual(data["schemaVersion"], 7)
        self.assertEqual(data["admittedIssuers"], 40)

    def test_market_radar_endpoint(self):
        radar = self._get("/api/radar")
        self.assertEqual(radar["exchange"], "NSE")
        self.assertGreater(radar["totalTurnoverCr"], 0)
        self.assertGreaterEqual(len(radar["dislocations"]), 1)

    def test_companies_and_single_company_endpoints(self):
        comps = self._get("/api/companies")
        self.assertEqual(len(comps), 40)
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