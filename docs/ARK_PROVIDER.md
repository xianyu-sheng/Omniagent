# Volcengine Ark Provider

Xenon exposes Volcengine Ark as the stable provider identity `ark`. It uses the
official OpenAI-compatible data plane for text chat, streaming, structured
outputs, and native function calling.

## Configure

Environment variables are the simplest non-interactive path:

```bash
export ARK_API_KEY="your-ark-api-key"
# Optional proxy or compatible gateway override:
export ARK_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"

xenon --model ark/doubao-seed-2-1-pro-260628
```

Interactive users can select **火山方舟 Ark** in `/setup`. The credential is
stored in `~/.xenon/credentials.yaml` with private file permissions, using the
same credential lifecycle as other built-in providers.

Xenon also recognizes an older Ark entry stored under `_custom_providers` when
there is exactly one unambiguous API key for the official Ark hostname. Reading
that compatibility view does not rewrite the credentials file. Explicitly
configuring `ark` creates the new top-level form; deleting Ark removes both the
new key and obsolete official-host custom entries.

## Model discovery

The primary source is the authenticated `/models` response. Ark's catalog
contains multiple product domains, so Xenon only admits entries whose
`task_type` contains `TextGeneration`, or whose declared output modality is
text. Image generation, video generation, and embedding models therefore do
not accidentally enter the chat failover pool.

For admitted models Xenon records non-secret capability metadata in memory:

- `token_limits.context_window`
- `token_limits.max_output_token_length`
- `features.tools.function_calling`
- structured-output and cache capability fields

Discovery metadata drives the runtime context window when present. If the
directory is unavailable, Xenon keeps a small offline fallback list; the live
directory remains authoritative.

## Protocol and telemetry

Ark shares Xenon's tested OpenAI-compatible request path:

- `POST /chat/completions`
- Bearer authentication
- non-streaming text responses
- SSE streaming
- `tools` and `tool_choice`
- `response_format`

For streaming, Xenon requests `stream_options.include_usage=true`. Both
blocking and streaming telemetry retain the canonical `ark/<model>` identity.
Cache parsing understands Ark/OpenAI-style
`usage.prompt_tokens_details.cached_tokens`; the uncached part is derived as
`prompt_tokens - cached_tokens` only when that nested field is present. Missing
cache fields continue to mean “unavailable”, not a fabricated 0% hit rate.

## Error behavior

- HTTP 401/403: credential/configuration failure; do not retry the same key.
- HTTP 400/404/422: request or model configuration failure in Direct mode.
- HTTP 429 and 5xx: transient; use bounded retry and model failover.
- network timeouts/protocol failures: transient; use bounded retry and
  circuit-breaker health accounting.

Xenon never logs or emits the Ark API key in model-discovery, integration CLI,
or cache telemetry output.
