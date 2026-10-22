# CodeSaathi AI — Code Workbench

A small hackathon MVP for explaining C, Python, and JavaScript snippets with documentation-grounded AI analysis. The app is built with Python's standard library and plain HTML/CSS/JavaScript, so there are no package installs or build step.

## Run it

1. Install Python 3.9 or newer.
2. In this folder, make a local `.env` file by copying `.env.example`, then add a Gemini API key. The app reads environment variables; it does not load `.env` itself.

   ```sh
   cp .env.example .env
   ```

3. In the same terminal, set the key and start the app:

   ```sh
   export GEMINI_API_KEY="your_key_here"
   python3 server.py
   ```

4. Open <http://127.0.0.1:8001> for the landing page. The workbench is a separate page at <http://127.0.0.1:8001/workbench>.

To use a different model or port, set `GEMINI_MODEL` or `PORT` before starting the server. The default port is 8001. Never commit `.env` or share your API key.

Without `GEMINI_API_KEY`, the interface and local retriever still run, but analysis displays a configuration error. No fake or local substitute analysis is presented as AI output.

## Pages and navigation

The landing page (`/`) contains the product introduction and an interactive three-screen walkthrough. Use the arrow buttons, dots, or left/right keys while the carousel is focused to change screens. It pauses while hovered or focused, and turns off automatic motion when reduced motion is enabled. **Open the workbench** navigates to `/workbench`, a separate page with the code editor and analysis panels. Both use a short browser page transition where supported.

## How retrieval works

`docs/corpus.json` contains short excerpts from official documentation with source URLs and section metadata. For each request, `server.py` tokenizes the submitted code and optional question, ranks same-language chunks by term overlap, and passes the selected chunk text and metadata inside Gemini's prompt. This is **local lexical retrieval**, not embeddings or a vector database. The response includes the retrieved chunks; the Sources tab renders those response objects directly. If the corpus cannot be read or retrieval has no matches, the server returns an explicit error and does not continue as if RAG succeeded.

The analysis path validates the model's JSON shape before returning it. Submitted code is never executed by this app. Suggested tests are generated text and are not run. Keep submissions below 20,000 characters.

## Test

Run the dependency-free automated suite:

```sh
python3 -m unittest -v
```

It covers empty input, a valid mocked analysis, a broken C `scanf` example, retrieval context passed into the Gemini prompt, missing credentials, retrieval failure, source provenance in the frontend, and an HTTP request through the backend.

## Two-minute demo

1. Start the server and open the workbench.
2. Leave C selected and click **Load sample**. The sample has `scanf("%d", number)`, which should pass an `int *` but receives an `int`.
3. Click **Analyze code**. Gemini receives the retrieved POSIX excerpt along with the code; the result includes a likely-bug list, a suggested correction, and unexecuted test ideas.
4. Open **Sources** to inspect the retrieved excerpt and its original URL. Explain that this MVP uses lexical retrieval over a compact local corpus, not embeddings.
5. Switch to Python or JavaScript and load a sample to show the language-specific documentation retrieval.
6. Clear `GEMINI_API_KEY` and analyze again to demonstrate the honest setup error. The server does not invent a result or run submitted code.

## Features and limitations

- Working code editor with C, Python, and JavaScript selection, local source-file loading for `.c`, `.h`, `.py`, `.js`, `.mjs`, `.jsx`, or `.txt`, sample snippets, optional question, line numbers, a 20,000-character limit, responsive layout, result tabs, and copy action for suggested code.
- Source files are read into the editor in the browser. Nothing is sent for analysis until the user chooses **Analyze code**; that request sends the code and retrieved documentation context to Gemini.
- One-click request to a Python HTTP backend, lexical retrieval from a small official-document corpus, Gemini context injection, structured response validation, and returned-source display.
- Helpful empty, loading, success, and error states. No submitted code execution.
- Gemini credentials are required for generated analysis. No credentials were bundled with this project.
- The corpus is intentionally small; lexical matching can miss relevant passages. This MVP does not use embeddings, FAISS, or ChromaDB.
- Model findings and suggested patches are hypotheses, not compiler-verified facts. Suggested tests are not executed.
- Browser font files are requested from Google Fonts; system font fallbacks keep the page usable offline.
