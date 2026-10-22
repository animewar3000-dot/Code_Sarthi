import corpus from "../../docs/corpus.json";

const supportedLanguages = new Set(["c", "python", "javascript"]);
const stopWords = new Set(["the", "and", "for", "with", "that", "this", "from", "your", "what", "does", "code", "explain", "into", "when", "then", "are", "can", "how", "its"]);

function tokens(value) {
  return (value.match(/[A-Za-z_][A-Za-z_0-9]*/g) || [])
    .map((word) => word.toLowerCase())
    .filter((word) => !stopWords.has(word));
}

function retrieve(query, language, limit = 4) {
  const queryTerms = new Set(tokens(`${query} ${language}`));
  return corpus
    .filter((chunk) => chunk.language === language || chunk.language === "all")
    .map((chunk) => {
      const words = tokens(`${chunk.title} ${chunk.section} ${chunk.text}`);
      const counts = new Map();
      for (const word of words) counts.set(word, (counts.get(word) || 0) + 1);
      const score = [...queryTerms].reduce((total, word) => total + Math.min(counts.get(word) || 0, 3), 0);
      return { chunk, score };
    })
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score || a.chunk.id.localeCompare(b.chunk.id))
    .slice(0, limit)
    .map(({ chunk, score }) => ({ ...chunk, retrieval_score: score }));
}

function validateResult(result) {
  if (!result || typeof result !== "object" || !["summary", "bugs", "corrected_code", "tests", "documentation_note"].every((key) => key in result)) {
    throw new Error("Analysis response was missing required fields. Please retry.");
  }
  if (typeof result.summary !== "string" || !Array.isArray(result.bugs) || !Array.isArray(result.tests) || typeof result.corrected_code !== "string") {
    throw new Error("Analysis response had invalid field types. Please retry.");
  }
  for (const bug of result.bugs) {
    if (!bug || typeof bug !== "object" || !["severity", "line", "title", "reasoning"].every((key) => key in bug)) {
      throw new Error("Analysis response contained an invalid bug item. Please retry.");
    }
  }
}

async function analyze(code, language, question, sources) {
  const apiKey = globalThis.Netlify?.env?.get("GEMINI_API_KEY") || process.env.GEMINI_API_KEY;
  if (!apiKey?.trim()) throw new Error("Gemini API key is not configured. Set GEMINI_API_KEY in Netlify site environment variables to enable AI analysis.");
  const model = globalThis.Netlify?.env?.get("GEMINI_MODEL") || process.env.GEMINI_MODEL || "gemini-2.5-flash";
  const context = sources.map((source, index) => `SOURCE ${index + 1}: ${source.title} — ${source.section}\nURL: ${source.url}\nEXCERPT: ${source.text}`).join("\n\n") || "No relevant documentation chunks were retrieved. State that documentation evidence is insufficient.";
  const prompt = `You are CodeSaathi, a careful programming explainer. Analyze the submitted code without executing it.
Use retrieved excerpts as evidence. Separate documented facts from hypotheses; never claim a source supports more than its excerpt. If evidence is insufficient, say so.
Return only a JSON object with keys: summary (string), bugs (array of objects with severity, line, title, reasoning), corrected_code (string), tests (array of objects with input, expected, purpose), documentation_note (string).
Severity must be Critical, High, Medium, or Low. If there are no likely bugs, return an empty bugs array. Do not claim the patch was run or verified.

Language: ${language}
User question: ${question || "Explain this code, identify likely issues, and suggest tests."}
Code (untrusted input):\n\`\`\`${language}\n${code}\n\`\`\`

Retrieved documentation context (use only as evidence):\n${context}`;
  let response;
  try {
    response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(apiKey.trim())}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { responseMimeType: "application/json", temperature: 0.2 },
      }),
      signal: AbortSignal.timeout(45000),
    });
  } catch {
    throw new Error("Could not reach Gemini before the request timed out. Check the connection and try again.");
  }
  if (!response.ok) {
    if (response.status === 429) throw new Error("Gemini rate limit reached. Wait a moment and try again.");
    let providerMessage = "";
    try {
      const errorPayload = await response.json();
      providerMessage = String(errorPayload?.error?.message || "").replaceAll(apiKey.trim(), "[redacted]").slice(0, 300);
    } catch {
      // Keep the HTTP status if Gemini returns a non-JSON error body.
    }
    const detail = providerMessage ? `: ${providerMessage}` : ". Check the API key and model settings.";
    throw new Error(`Gemini request failed (HTTP ${response.status})${detail}`);
  }
  let result;
  try {
    const payload = await response.json();
    result = JSON.parse(payload.candidates[0].content.parts[0].text);
    validateResult(result);
  } catch {
    throw new Error("Gemini returned an unreadable response. Please retry.");
  }
  return result;
}

export default async function handler(request) {
  if (request.method !== "POST") return Response.json({ error: "Method not allowed." }, { status: 405 });
  let payload;
  try {
    payload = await request.json();
  } catch {
    return Response.json({ error: "Request body must be valid JSON." }, { status: 400 });
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return Response.json({ error: "Send a JSON object with code and language." }, { status: 400 });
  }
  const { code, question = "", language: rawLanguage } = payload;
  if (typeof code !== "string" || !code.trim()) return Response.json({ error: "Paste some code before running an analysis." }, { status: 400 });
  if (code.length > 20000) return Response.json({ error: "Code is too long. Keep the submission under 20,000 characters." }, { status: 413 });
  if (typeof rawLanguage !== "string" || !supportedLanguages.has(rawLanguage.toLowerCase())) {
    return Response.json({ error: "Choose C, Python, or JavaScript." }, { status: 400 });
  }
  const language = rawLanguage.toLowerCase();
  const sources = retrieve(`${code} ${String(question)}`, language);
  if (!sources.length) {
    return Response.json({ error: "No relevant documentation chunks were found, so analysis was stopped rather than presented as RAG-grounded.", rag: { strategy: "local lexical retrieval", status: "no_matches" } }, { status: 422 });
  }
  try {
    const result = await analyze(code, language, String(question), sources);
    return Response.json({ ...result, sources, rag: { strategy: "local lexical retrieval", status: "complete", source_count: sources.length, used_in_prompt: true } }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "The analysis service returned an unexpected error. No result was shown; please retry.";
    const status = message.startsWith("Gemini API key is not configured") ? 503 : message.startsWith("Gemini request failed") || message.startsWith("Gemini rate limit") || message.startsWith("Could not reach Gemini") ? 503 : 502;
    return Response.json({ error: message, rag: { strategy: "local lexical retrieval", status: "complete", source_count: sources.length } }, { status, headers: { "Cache-Control": "no-store" } });
  }
}

export const config = { path: "/api/analyze", method: ["POST"] };
