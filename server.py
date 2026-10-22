"""CodeSaathi MVP: a small, dependency-free HTTP server with lexical RAG."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
DOCS_PATH = ROOT / "docs" / "corpus.json"
SUPPORTED = {"c", "python", "javascript"}
STOP = {"the", "and", "for", "with", "that", "this", "from", "your", "what", "does", "code", "explain", "into", "when", "then", "are", "can", "how", "its"}


def load_chunks() -> list[dict[str, Any]]:
    data = json.loads(DOCS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise RuntimeError("Documentation corpus is empty or malformed")
    return data


def tokens(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", text) if w.lower() not in STOP]


def retrieve(query: str, language: str, limit: int = 4) -> list[dict[str, Any]]:
    """Transparent local lexical retrieval; this is not represented as vectors."""
    chunks = load_chunks()
    query_terms = set(tokens(query + " " + language))
    scored = []
    for chunk in chunks:
        if chunk.get("language") not in (language, "all"):
            continue
        words = tokens(chunk["title"] + " " + chunk["section"] + " " + chunk["text"])
        counts = {word: words.count(word) for word in query_terms}
        score = sum(min(n, 3) for n in counts.values())
        if score:
            scored.append((score, chunk))
    return [dict(chunk, retrieval_score=score) for score, chunk in sorted(scored, key=lambda x: (-x[0], x[1]["id"]))[:limit]]


def call_gemini(code: str, language: str, question: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Gemini API key is not configured. Add GEMINI_API_KEY to .env (see .env.example) to enable AI analysis.")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    context = "\n\n".join(
        f"SOURCE {i}: {c['title']} — {c['section']}\nURL: {c['url']}\nEXCERPT: {c['text']}"
        for i, c in enumerate(chunks, start=1)
    ) or "No relevant documentation chunks were retrieved. State that documentation evidence is insufficient."
    prompt = f'''You are CodeSaathi, a careful programming explainer. Analyze the submitted code without executing it.
Use retrieved excerpts as evidence. Separate documented facts from hypotheses; never claim a source supports more than its excerpt. If evidence is insufficient, say so.
Return only a JSON object with keys: summary (string), bugs (array of objects with severity, line, title, reasoning), corrected_code (string), tests (array of objects with input, expected, purpose), documentation_note (string).
Severity must be Critical, High, Medium, or Low. If there are no likely bugs, return an empty bugs array. Do not claim the patch was run or verified.

Language: {language}
User question: {question or 'Explain this code, identify likely issues, and suggest tests.'}
Code (untrusted input):\n```{language}\n{code}\n```

Retrieved documentation context (use only as evidence):\n{context}'''
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode())
        raw = payload["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError("Gemini rate limit reached. Wait a moment and try again.") from exc
        raise RuntimeError(f"Gemini request failed (HTTP {exc.code}). Check the API key and model settings.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Could not reach Gemini before the request timed out. Check your connection and try again.") from exc
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Gemini returned an unreadable response. Please retry.") from exc
    validate_result(result)
    return result


def validate_result(result: Any) -> None:
    if not isinstance(result, dict) or not all(k in result for k in ("summary", "bugs", "corrected_code", "tests", "documentation_note")):
        raise RuntimeError("Analysis response was missing required fields. Please retry.")
    if not isinstance(result["summary"], str) or not isinstance(result["bugs"], list) or not isinstance(result["tests"], list) or not isinstance(result["corrected_code"], str):
        raise RuntimeError("Analysis response had invalid field types. Please retry.")
    for bug in result["bugs"]:
        if not isinstance(bug, dict) or not all(k in bug for k in ("severity", "line", "title", "reasoning")):
            raise RuntimeError("Analysis response contained an invalid bug item. Please retry.")


def analyze_payload(payload: Any, generator=call_gemini) -> tuple[int, dict[str, Any]]:
    if not isinstance(payload, dict):
        return 400, {"error": "Send a JSON object with code and language."}
    code = payload.get("code")
    language = payload.get("language")
    question = payload.get("question", "")
    if not isinstance(code, str) or not code.strip():
        return 400, {"error": "Paste some code before running an analysis."}
    if not isinstance(language, str) or language.lower() not in SUPPORTED:
        return 400, {"error": "Choose C, Python, or JavaScript."}
    if len(code) > 20000:
        return 413, {"error": "Code is too long. Keep the submission under 20,000 characters."}
    language = language.lower()
    try:
        sources = retrieve(code + " " + str(question), language)
    except Exception:
        return 503, {"error": "Documentation retrieval failed. No analysis was generated; check that docs/corpus.json is available and valid.", "rag": {"strategy": "local lexical retrieval", "status": "failed"}}
    if not sources:
        return 422, {"error": "No relevant documentation chunks were found, so analysis was stopped rather than presented as RAG-grounded.", "rag": {"strategy": "local lexical retrieval", "status": "no_matches"}}
    try:
        result = generator(code, language, str(question), sources)
        validate_result(result)
    except RuntimeError as exc:
        return 503, {"error": str(exc), "rag": {"strategy": "local lexical retrieval", "status": "complete", "source_count": len(sources)}}
    except Exception:
        return 502, {"error": "The analysis service returned an unexpected error. No result was shown; please retry.", "rag": {"strategy": "local lexical retrieval", "status": "complete", "source_count": len(sources)}}
    return 200, {**result, "sources": sources, "rag": {"strategy": "local lexical retrieval", "status": "complete", "source_count": len(sources), "used_in_prompt": True}}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "static"), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        route = self.path.split("?", 1)[0].rstrip("/") or "/"
        if route == "/workbench":
            query = ("?" + self.path.split("?", 1)[1]) if "?" in self.path else ""
            self.path = "/workbench.html" + query
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/analyze":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 30000:
                status, result = 413, {"error": "Request is too large."}
            else:
                status, result = analyze_payload(json.loads(self.rfile.read(length) or b"{}"))
        except (ValueError, json.JSONDecodeError):
            status, result = 400, {"error": "Request body must be valid JSON."}
        except Exception:
            status, result = 500, {"error": "The server could not complete this request."}
        encoded = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


def load_env(env_path: Path | None = None) -> None:
    path = env_path or (ROOT / ".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if key and key not in os.environ:
            os.environ[key] = val.strip("'\"")


if __name__ == "__main__":
    load_env()
    port = int(os.getenv("PORT", "8001"))
    print(f"CodeSaathi running at http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
