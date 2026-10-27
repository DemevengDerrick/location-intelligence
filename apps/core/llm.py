"""The one place the platform calls an LLM (Claude): area-signals extraction (FR-26) and the
analyst's "suggest wording" button (FR-43). Nothing calls it unless ANTHROPIC_API_KEY is set.

Customer-facing findings are never written here (FR-58): extraction output waits for an
analyst's approval, and wording suggestions must be accepted one by one."""

from django.conf import settings

# Refused requests are re-run server-side on a fallback model chosen by refusal category.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LlmUnavailable(RuntimeError):
    """No API key configured."""


class LlmRefused(RuntimeError):
    """The model (and its fallback) declined the request."""


def available():
    return bool(settings.ANTHROPIC_API_KEY)


def _client():
    import anthropic

    if not available():
        raise LlmUnavailable("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=120, max_retries=3)


def parse(*, system, prompt, schema, effort="medium", max_tokens=8000):
    """One structured-output call: returns a validated `schema` instance."""
    response = _client().beta.messages.parse(
        model=settings.LLM_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=schema,
        output_config={"effort": effort},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise LlmRefused(getattr(response.stop_details, "explanation", "") or "refused")
    if response.parsed_output is None:
        raise ValueError(f"No structured output (stop reason {response.stop_reason})")
    return response.parsed_output
