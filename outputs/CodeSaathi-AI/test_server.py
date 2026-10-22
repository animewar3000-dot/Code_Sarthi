import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import server


class AnalysisTests(unittest.TestCase):
    def test_empty_code_returns_helpful_validation(self):
        status, result = server.analyze_payload({"code": " \n", "language": "c"})
        self.assertEqual(status, 400)
        self.assertIn("Paste some code", result["error"])

    def test_valid_program_analyzed_with_retrieved_context(self):
        seen = {}

        def fake_generator(code, language, question, chunks):
            seen["chunks"] = chunks
            return {"summary": "Reads one line from standard input.", "bugs": [], "corrected_code": code,
                    "tests": [{"input": "hello", "expected": "hello", "purpose": "normal input"}],
                    "documentation_note": "The retrieved Python documentation describes input()."}

        status, result = server.analyze_payload({"code": "name = input()\nprint(name)", "language": "python"}, fake_generator)
        self.assertEqual(status, 200)
        self.assertTrue(seen["chunks"])
        self.assertEqual(result["sources"], seen["chunks"])
        self.assertTrue(result["rag"]["used_in_prompt"])

    def test_broken_c_scanf_flags_missing_address_operator(self):
        code = '#include <stdio.h>\nint main(void) { int value; scanf("%d", value); }'
        status, result = server.analyze_payload({"code": code, "language": "c"}, lambda *args: {
            "summary": "Reads an integer.", "bugs": [{"severity": "High", "line": 2, "title": "scanf needs an address", "reasoning": "The %d conversion stores through an int pointer; pass &value."}],
            "corrected_code": code.replace('scanf("%d", value)', 'scanf("%d", &value)'), "tests": [], "documentation_note": "The POSIX excerpt requires pointer arguments."})
        self.assertEqual(status, 200)
        self.assertTrue(any("address" in b["title"].lower() or "pointer" in b["reasoning"].lower() for b in result["bugs"]))
        self.assertTrue(any(s["id"] == "posix-scanf-arguments" for s in result["sources"]))

    def test_retrieved_chunks_are_in_generation_prompt(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only"}):
            with patch("server.urllib.request.urlopen") as open_url:
                open_url.return_value.__enter__.return_value.read.return_value = json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps({"summary": "ok", "bugs": [], "corrected_code": "x=1", "tests": [], "documentation_note": "context"})}]}}]}).encode()
                chunks = server.retrieve("input line python", "python")
                server.call_gemini("name = input()", "python", "", chunks)
                sent = json.loads(open_url.call_args.args[0].data.decode())
                prompt = sent["contents"][0]["parts"][0]["text"]
                self.assertIn(chunks[0]["text"], prompt)

    def test_missing_api_key_is_honest_error(self):
        with patch.dict("os.environ", {}, clear=True):
            status, result = server.analyze_payload({"code": "name = input()", "language": "python"})
        self.assertEqual(status, 503)
        self.assertIn("GEMINI_API_KEY", result["error"])
        self.assertNotIn("summary", result)

    def test_retrieval_failure_is_disclosed(self):
        with patch("server.retrieve", side_effect=OSError("missing corpus")):
            status, result = server.analyze_payload({"code": "name = input()", "language": "python"})
        self.assertEqual(status, 503)
        self.assertEqual(result["rag"]["status"], "failed")
        self.assertIn("retrieval failed", result["error"])

    def test_frontend_displays_only_returned_sources(self):
        js = (Path(__file__).parent / "static" / "app.js").read_text()
        self.assertIn("Array.isArray(result.sources)", js)
        self.assertIn("sources.map", js)
        self.assertIn("exact chunks passed to Gemini", js)

    def test_landing_and_workbench_are_separate_pages(self):
        root = Path(__file__).parent / "static"
        landing = (root / "index.html").read_text()
        workbench = (root / "workbench.html").read_text()
        carousel = (root / "landing.js").read_text()
        self.assertIn("Find the bug.", landing)
        self.assertNotIn('id="code"', landing)
        self.assertIn('id="code"', workbench)
        self.assertIn("data-slide-to", landing)
        self.assertIn("ArrowRight", carousel)
        self.assertIn("/workbench", landing)

    def test_frontend_backend_http_round_trip(self):
        class TestHandler(server.Handler):
            def log_message(self, fmt, *args):
                pass
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_port}/api/analyze", data=json.dumps({"code": " ", "language": "c"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req)
            self.assertEqual(caught.exception.code, 400)
            body = json.loads(caught.exception.read().decode())
            self.assertIn("Paste some code", body["error"])

            page = urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/workbench")
            self.assertIn(b'id="code"', page.read())
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
