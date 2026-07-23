# llms.txt-first documentation retrieval

`docs_fetch` is Xenon's read-only tool for SDK, API, and platform documentation.
It implements the stable structure described by the
[llms.txt proposal](https://github.com/AnswerDotAI/llms-txt): an H1 title,
optional blockquote summary and details, followed by H2 groups of Markdown
links. The `Optional` group is treated as secondary context.

## Tool contract

```json
{
  "action": "docs_fetch",
  "action_input": {
    "url": "https://docs.example.com/sdk/",
    "query": "function calling schema",
    "max_pages": 4,
    "max_chars": 12000
  }
}
```

- `url` is required and may be a site, documentation subtree, ordinary page,
  or a direct llms context file.
- `query` is optional. Selection is deterministic and local: title matches
  outrank description, section, and URL matches.
- `max_pages` is clamped to 0–8. Zero returns the index summary without
  expanding links.
- `max_chars` is clamped to 1,000–30,000 and includes the truncation marker.

## Discovery and fallback

For a page below `/docs`, Xenon tries these bounded candidates in order:

1. `/docs/llms.txt`
2. `/llms.txt`
3. `/docs/llms-full.txt`
4. `/llms-full.txt`

Direct `llms.txt`, `llms-full.txt`, `llms-ctx.txt`, and
`llms-ctx-full.txt` URLs are fetched without additional discovery. A valid
index uses the `llms-index` strategy; a complete context file uses
`llms-full`. When no valid entry point exists, Xenon reuses the hardened
`web_fetch` implementation for the exact requested page and reports
`html-fallback` plus `degraded=true` instead of failing a useful research task.

Each result exposes the evidence needed to audit retrieval:

- discovery URL and attempts;
- total and Optional link counts;
- successfully selected source URLs;
- isolated per-source errors;
- content length and truncation state.

## Safety and budgets

Every discovery candidate and linked page passes Xenon's protocol, DNS/IP,
private-network, and redirect checks. A link supplied by an untrusted index
cannot bypass the SSRF boundary. Retrieved text remains untrusted tool output;
engine prompts explicitly forbid treating it as executable instruction.

`docs_fetch` is classified as an INFO/read-only tool. It can run in parallel
during exploration, but the ReAct convergence budget blocks further document
exploration so the model must synthesize an answer. Tool observations retain
up to 12,000 characters, compared with 3,000 for ordinary transient fetches,
because the selected bundle has already been budgeted and deduplicated.
