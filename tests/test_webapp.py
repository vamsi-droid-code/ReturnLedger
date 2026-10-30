import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from returnledger.webapp import App, make_handler

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "starter")


@unittest.skipUnless(os.path.exists(os.path.join(DATA, "reports", "validation_summary.json")),
                     "run `python -m returnledger run --scale starter` first")
class WebAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(DATA)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        with urlopen(self.base + path) as resp:
            body = resp.read()
            return json.loads(body) if resp.headers["Content-Type"].startswith("application/json") else body

    def test_static_and_api_endpoints(self):
        self.assertIn(b"ReturnLedger", self.get("/"))
        for path in ("/api/summary", "/api/rmas", "/api/exceptions", "/api/rules", "/api/quality"):
            self.assertTrue(self.get(path), path)

    def test_rma_list_covers_every_request(self):
        self.assertEqual(len(self.get("/api/rmas")), len(self.app.t["return_request"]))

    def test_rma_trace_includes_ground_truth_for_anomalies(self):
        rid = next(iter(self.app.gt_by_rma))
        trace = self.get(f"/api/rma/{rid}")
        self.assertEqual(trace["rma"]["rma_id"], rid)
        self.assertTrue(trace["lines"])
        self.assertTrue(trace["ground_truth"])
        self.assertTrue(trace["events"])

    def test_unknown_rma_and_path_traversal_are_404(self):
        for path in ("/api/rma/RMA-0000-000000", "/api/nope", "/..%2F..%2FREADME.md"):
            with self.assertRaises(HTTPError) as ctx:
                urlopen(self.base + path)
            self.assertEqual(ctx.exception.code, 404, path)


if __name__ == "__main__":
    unittest.main()
