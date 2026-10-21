import contextlib
import importlib.util
import io
import json
import os
import pathlib
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("redteam", pathlib.Path(__file__).parents[1] / "run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class Response:
    def __init__(self, code):
        self.code = code
        self.headers = {"X-Request-ID": "test-id"}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, limit):
        return b"test body"


class Opener:
    def __init__(self, codes):
        self.codes = iter(codes)
        self.called = []
    def open(self, req, timeout):
        self.called.append(req.full_url)
        return Response(next(self.codes))


class Guardrails(unittest.TestCase):
    def test_scope_rejects_external_credentials_and_paths(self):
        allowed = ["https://10.0.0.10:8443"]
        for url in ["https://example.com", "http://10.0.0.10:8443",
                    "https://10.0.0.11:8443", "https://user:pw@10.0.0.10:8443",
                    "https://10.0.0.10:8443/path", "https://10.0.0.10:8443#x"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                runner.validate_origin(url, allowed)
        self.assertEqual(runner.validate_origin(allowed[0], allowed), allowed[0])

    def test_no_network_without_execute(self):
        with patch.object(runner, "build_opener", side_effect=AssertionError("network")):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(["--scenario", "soc", "--scope", str(pathlib.Path(__file__).parents[1] / "scope.example.json")]), 0)

    def test_stop_before_attack_when_baseline_fails(self):
        op = Opener([503])
        with contextlib.redirect_stdout(io.StringIO()):
            records, reason = runner.execute(op, "https://10.0.0.10:8443", runner.make_plan("soc", "test"), "test", 1, 1, io.StringIO())
        self.assertEqual(len(op.called), 1)
        self.assertFalse(records[0]["pass"])
        self.assertIsNotNone(reason)

    def test_stop_when_waf_accepts_payload(self):
        op = Opener([200, 200, 200, 200])
        with patch.object(runner.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            records, reason = runner.execute(op, "https://10.0.0.10:8443", runner.make_plan("waf", "test"), "test", 1, 1, io.StringIO())
        self.assertEqual(len(op.called), 4)
        self.assertFalse(records[-1]["pass"])
        self.assertEqual(records[-1]["case"], "sql")

    def test_counts_and_successful_sequence(self):
        for scenario, expected in [("waf", 12), ("soc", 26)]:
            plan = runner.make_plan(scenario, "test")
            self.assertEqual(len(plan), expected)
            self.assertLessEqual(len(plan), 40)
            op = Opener([x[2] for x in plan])
            log = io.StringIO()
            with patch.object(runner.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
                records, reason = runner.execute(op, "https://10.0.0.10:8443", plan, "test", 1, 1, log)
            self.assertTrue(all(x["pass"] for x in records))
            self.assertIsNone(reason)
            self.assertEqual(len(log.getvalue().splitlines()), expected)
            self.assertTrue(all("body" not in json.loads(x) for x in log.getvalue().splitlines()))

    def test_ml_cancelled_without_confirmed_test_mode(self):
        op = Opener([200])
        with contextlib.redirect_stdout(io.StringIO()):
            records, reason = runner.execute(op, "https://10.0.0.10:8443", runner.make_plan("ml", "test"), "test", 1, 5, io.StringIO())
        self.assertEqual(len(op.called), 1)
        self.assertFalse(records[0]["pass"])
        self.assertIsNotNone(reason)

    def test_ml_has_fixed_budget_and_no_writes(self):
        plan = runner.make_plan("ml", "test")
        self.assertEqual(len(plan), 102)
        self.assertEqual(plan[0][0], "mode_check")
        self.assertTrue(all(x[1] in ["/api/health", "/api/status", "/"] for x in plan))

    def test_authenticated_payload_keeps_cookie_out_of_evidence(self):
        seen=[]
        class Capture:
            def open(self, request, timeout):
                seen.append(request)
                return Response(422)
        with patch.dict(os.environ, {'REDTEAM_SESSION_COOKIE':'session=dummy-test-value'}):
            result=runner.send(Capture(), 'https://10.0.0.10:8443', ('invalid_payment','/api/payment_intents',422), 'test', 1)
        self.assertTrue(result['pass'])
        self.assertEqual(seen[0].get_method(),'POST')
        self.assertEqual(json.loads(seen[0].data)['amount'],-1)
        self.assertNotIn('dummy-test-value',json.dumps(result))

    def test_session_header_injection_rejected(self):
        with patch.dict(os.environ, {'REDTEAM_SESSION_COOKIE':'x=y\r\nInjected: true'}):
            with self.assertRaises(ValueError):
                runner.send(Opener([200]), 'https://10.0.0.10:8443', ('baseline','/',200), 'test', 1)

    def test_redirect_not_followed(self):
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/outside-scope")
                self.end_headers()
            def log_message(self, *args):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), runner.NoRedirect())
            with self.assertRaises(urllib.error.HTTPError) as error:
                opener.open("http://127.0.0.1:" + str(server.server_port) + "/start", timeout=2)
            self.assertEqual(error.exception.code, 302)
            self.assertEqual(hits, ["/start"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
