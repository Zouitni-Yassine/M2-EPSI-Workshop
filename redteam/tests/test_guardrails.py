import contextlib
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import threading
import time
import unittest
import zipfile
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
    def test_package_contains_only_source_allowlist(self):
        package_spec=importlib.util.spec_from_file_location('redteam_package',pathlib.Path(__file__).parents[1]/'package.py')
        packer=importlib.util.module_from_spec(package_spec)
        package_spec.loader.exec_module(packer)
        with tempfile.TemporaryDirectory() as folder:
            archive=packer.package(pathlib.Path(folder)/'sources.zip')
            with zipfile.ZipFile(archive) as source:
                self.assertEqual(set(source.namelist()),{'redteam/'+x for x in packer.SOURCES}|{'redteam/SOURCE-MANIFEST.json'})
                manifest=json.loads(source.read('redteam/SOURCE-MANIFEST.json'))
                for name,digest in manifest['files_sha256'].items():
                    self.assertEqual(runner.hashlib.sha256(source.read('redteam/'+name)).hexdigest(),digest)

    def test_burst_http_success_does_not_validate_full_demo(self):
        with tempfile.TemporaryDirectory() as folder:
            records=[{'case':name,'pass':True,'status':status} for name,status in [('mode_check',200),('burst_probe',401),('burst',401)]]
            with patch.object(runner,'execute_burst',return_value=(records,None)), contextlib.redirect_stdout(io.StringIO()):
                code=runner.main(['--scenario','burst','--execute','--rate','1','--duration','1',
                                 '--scope',str(pathlib.Path(__file__).parents[1]/'scope.example.json'),
                                 '--output',folder])
            summary=json.loads(next(pathlib.Path(folder).glob('*/summary.json')).read_text())
            self.assertEqual(code,0)
            self.assertFalse(summary['full_subject_sequence_passed'])
            self.assertEqual(summary['ml_detection'],'not_verified')
            self.assertEqual(summary['automatic_remediation'],'not_verified')
            self.assertEqual(summary['new_business_transaction'],'not_verified')

    def test_public_host_is_exactly_scoped(self):
        target = "https://app.slabreze.fr"
        self.assertEqual(runner.validate_origin(target + "/", [target]), target)
        for value in ["https://app.slabreze.fr.evil.example", target + ":8443",
                      target + "?x=1", "https://other.example", "http://app.slabreze.fr"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.validate_origin(value, [target])

    def test_public_tls_uses_system_trust(self):
        with patch.object(runner.ssl, "create_default_context", wraps=runner.ssl.create_default_context) as trust:
            runner.build_opener(None)
        trust.assert_called_once_with(cafile=None)

    def test_public_relay_rejected_even_in_dry_run(self):
        with self.assertRaises(ValueError):
            runner.main(["--ssh-relay", "--scope", str(pathlib.Path(__file__).parents[1] / "scope.example.json")])

    def test_burst_caps_and_non_finite_values(self):
        runner.validate_burst(30, 25, 8, 800)
        for args in [(41,25,8,1200), (30,31,8,1200), (30,25,11,800),
                     (30,25,8,100), (float('nan'),25,8,800), (30,float('inf'),8,800)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                runner.validate_burst(*args)

    def test_burst_stops_before_load_if_precondition_fails(self):
        for statuses in [(False,200), (True,200)]:
            def fake(opener, origin, case, run_id, timeout):
                return {"case":case[0], "status":statuses[1], "pass":statuses[0] if case[0]=='mode_check' else False}
            with patch.object(runner, 'build_opener'), patch.object(runner, 'send', side_effect=fake) as send:
                records, reason=runner.execute_burst('https://app.slabreze.fr',None,'test',1,30,1,2,40,io.StringIO())
            self.assertIsNotNone(reason)
            self.assertLessEqual(send.call_count,2)

    def test_burst_rate_budget_and_concurrency(self):
        active=0
        peak=0
        starts=[]
        lock=threading.Lock()
        real_pool=runner.futures.ThreadPoolExecutor
        class TimedPool(real_pool):
            def submit(self,*args,**kwargs):
                starts.append(time.monotonic())
                return super().submit(*args,**kwargs)
        def fake(opener, origin, case, run_id, timeout):
            nonlocal active, peak
            if case[0]=='burst':
                with lock:
                    active+=1
                    peak=max(peak,active)
                time.sleep(.06)
                with lock:
                    active-=1
            return {'case':case[0], 'status':200 if case[0]=='mode_check' else 401, 'pass':True}
        with patch.dict(os.environ,{},clear=True), patch.object(runner,'build_opener'), patch.object(runner,'send',side_effect=fake), patch.object(runner.futures,'ThreadPoolExecutor',TimedPool), contextlib.redirect_stdout(io.StringIO()):
            records, reason=runner.execute_burst('https://app.slabreze.fr',None,'test',1,40,.2,2,10,io.StringIO())
        self.assertIsNone(reason)
        self.assertLessEqual(len(records),10)
        self.assertLessEqual(peak,2)
        self.assertGreater(peak,1)
        self.assertTrue(all(b-a>=.024 for a,b in zip(starts,starts[1:])))

    def test_burst_stops_on_ban_without_retry(self):
        def fake(opener, origin, case, run_id, timeout):
            return {'case':case[0], 'status':403 if case[0]=='burst' else 200 if case[0]=='mode_check' else 401, 'pass':case[0]!='burst'}
        with patch.dict(os.environ,{},clear=True), patch.object(runner,'build_opener'), patch.object(runner,'send',side_effect=fake), contextlib.redirect_stdout(io.StringIO()):
            records, reason=runner.execute_burst('https://app.slabreze.fr',None,'test',1,30,1,2,40,io.StringIO())
        self.assertEqual(len(records),3)
        self.assertIn('Confinement',reason)

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
