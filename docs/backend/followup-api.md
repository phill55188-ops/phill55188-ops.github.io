# SignalBrief follow-up research API

Implemented November 16, 2026 (Eastern Time). The existing `/api/analyze` request and response are preserved. `POST /api/followup` uses the same `X-SignalBrief-Access` authentication and origin policy as analysis. No new secret, permission or API provider is introduced.

## Request

```json
{
  "question": "What could change this conclusion?",
  "section": { "title": "Risks and catalysts", "text": "Selected rendered analysis" },
  "context": { "subject": "Research subject", "source": "Original source text", "support": [] },
  "history": [{ "question": "Previous follow-up", "answer": "Previous answer" }],
  "evidence": [{ "name": "notes.txt", "type": "text/plain", "data": "Raw UTF-8 text" }]
}
```

`history` and `evidence` are optional. Question must contain 1–4,000 characters and a completed section must be selected. Context is bounded to 2,000 subject characters, 48,000 source characters and 24,000 serialized supporting-material characters; section to 300 title and 16,000 text characters. Only the latest six prior turns are used, each bounded to 4,000 question/24,000 answer characters.

Evidence: at most three files, each at most 4 MiB. TXT (`text/plain`), Markdown (`text/markdown`), CSV (`text/csv`) and JSON (`application/json`) are supplied as raw text, totaling at most 120,000 characters. PDF (`application/pdf`), PNG (`image/png`), JPEG (`image/jpeg`) and WebP (`image/webp`) use a MIME-matched base64 data URL. Binary files become OpenAI `input_file` or `input_image` items without a separate persistent Files upload. Unsupported/oversized files produce an explicit validation error. The streaming request parser enforces an 18 MiB total-body limit, including JSON and base64 overhead.

## Research and response

Uses the existing `gpt-5.6-terra` model with high reasoning effort, a 6,000-token output budget, forced `web_search`, high search context and `store: false`. Instructions are server-owned; client `system` fields cannot override them. Evidence and source context are marked untrusted. The prompt asks for alternative scenarios, counterarguments, primary sources, distinctions between supplied/retrieved evidence and uncertainty. It instructs searches to avoid private contents and identifiers. This instruction reduces accidental disclosure risk; it is not a mathematical guarantee about model behavior.

```json
{
  "text": "Research answer with provider citation markers",
  "citations": [{ "url": "https://example.org/report", "title": "Report" }],
  "research": { "webSearchUsed": true },
  "response_id": "resp_...",
  "model": "gpt-5.6-terra",
  "incomplete": false
}
```

Citation URLs come from actual `url_citation` annotations and are deduplicated; only HTTP(S), without embedded credentials, is returned. `webSearchUsed` requires a completed `web_search_call`. Incomplete provider responses remain visibly classifiable through `incomplete: true`. Empty outputs and unreadable upstream data return 502. Rate limiting returns 429. The upstream request and response body share a three-minute timeout, returning 504 when exceeded. No sensitive payloads or keys are logged by this handler. Cancellation in the client stops waiting locally; it cannot guarantee that a server-side OpenAI request already started has stopped or will not be billed.

## Verification

`node --test tests/followup-worker.test.mjs`

Tests cover authentication/origin rejection, omitted evidence, forced research/high reasoning/server-owned instructions, safe citation extraction, question/section/file/body validation, text/PDF/image input shapes, upstream failures/incomplete responses, malformed provider output/content/annotation shapes and unchanged original-analysis request behavior. Seven tests pass after a review-discovered malformed-annotation failure was reproduced and repaired. Tests use a mocked OpenAI network boundary; they do not establish deployed runtime or live provider acceptance. MIME, base64 and size validation does not prove a binary file is well formed; actual attachment readability is validated by the provider.

Official API documentation checked during implementation:

- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/docs/guides/file-inputs
- https://developers.openai.com/api/docs/models/gpt-5.6-terra

The current Terra model page documents high reasoning and web search support. The web search guide documents forced tool choice and URL-citation annotations. The file-input guide documents base64 file data.
