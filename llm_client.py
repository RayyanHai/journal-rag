# Shared Gemini client using Google's OpenAI-compatible endpoint.
#
# The compatibility endpoint is still in beta, so requests use retry handling
# and include a fallback for unsupported structured-output behavior.

import json
import os
import sys
import time
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, BadRequestError
from pydantic_core import PydanticUndefined

load_dotenv()

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# Use a concrete model name so an alias cannot silently move to a model with
# different limits or behavior.
GEMINI_MODEL = "gemini-3.1-flash-lite"

DEFAULT_MAX_TOKENS = 1500

MAX_RATE_LIMIT_RETRIES = 5
_RATE_LIMIT_BASE_DELAY = 5  # seconds; doubles each retry if the server gives no Retry-After
# A long Retry-After usually means the daily quota is exhausted rather than a brief
# throttle. Sleeping for that entire period would hang the process, so treat anything
# over this as unrecoverable right now and fail fast.
_MAX_HONORED_RETRY_AFTER = 120

# Carried over from the Groq client defensively - Gemini's function calling is
# first-party and hasn't shown this failure mode in testing, but if the beta
# OpenAI-compat shim ever surfaces an equivalent 'tool_use_failed', a bare retry
# (different sampling) is the same cheap fix.
MAX_TOOL_CALL_RETRIES = 5


def _is_tool_use_failed(e):
    if isinstance(e.body, dict) and e.body.get("error", {}).get("code") == "tool_use_failed":
        return True
    # e.body's shape isn't guaranteed across SDK versions/proxies - fall back to
    # a plain substring check on the exception text, which always contains this.
    return "tool_use_failed" in str(e)


def get_client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY in .env (from aistudio.google.com/apikey) to call Gemini.")
    return OpenAI(base_url=GEMINI_BASE_URL, api_key=key)


def create_completion(client, **kwargs):
    """
    Thin wrapper around client.chat.completions.create with retry/backoff on 429s,
    plus a few immediate retries on a 'tool_use_failed'-style malformed function
    call (sampling variance, not a real error - usually valid on retry). Honors
    the server's Retry-After header when present, otherwise backs off exponentially.
    """
    delay = _RATE_LIMIT_BASE_DELAY
    tool_call_attempt = 0
    for attempt in range(MAX_RATE_LIMIT_RETRIES):
        try:
            return client.chat.completions.create(**kwargs)
        except BadRequestError as e:
            if not _is_tool_use_failed(e) or tool_call_attempt >= MAX_TOOL_CALL_RETRIES - 1:
                raise
            tool_call_attempt += 1
            print(
                f"[malformed tool call] retrying ({tool_call_attempt + 1}/{MAX_TOOL_CALL_RETRIES})...",
                file=sys.stderr,
            )
        except RateLimitError as e:
            retry_after = e.response.headers.get("retry-after") if e.response is not None else None
            wait = float(retry_after) if retry_after else delay
            if wait > _MAX_HONORED_RETRY_AFTER:
                raise RuntimeError(
                    f"Gemini says wait {wait:.0f}s ({wait / 3600:.1f}h) — that's a quota "
                    "reset, not a brief throttle. Giving up rather than blocking for that "
                    "long; try again once the quota resets."
                ) from e
            if attempt == MAX_RATE_LIMIT_RETRIES - 1:
                raise
            print(
                f"[rate limited] waiting {wait:.0f}s before retry "
                f"{attempt + 2}/{MAX_RATE_LIMIT_RETRIES}...",
                file=sys.stderr,
            )
            time.sleep(wait)
            delay *= 2


def _loads_lenient(content):
    """
    Parse the FIRST complete JSON object out of a model response, tolerating two
    quirks of the (beta) OpenAI-compat layer that plain json.loads chokes on:
      - a leading ```json / ``` markdown fence, and
      - trailing text after the object (we saw a real 'Extra data' crash where the
        model appended prose after valid JSON).
    Locate the first '{' and use raw_decode, which stops at the end of the first
    value and ignores anything after it.
    """
    start = content.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model response.")
    obj, _ = json.JSONDecoder().raw_decode(content[start:])
    return obj


def _drop_defaultable_nulls(data, model_cls):
    """
    The model sometimes emits an explicit `null` for a field that has a real
    (non-None) default - e.g. `"recency": null` instead of `"recency": "none"`.
    Plain JSON mode doesn't enforce our schema, so nothing stops that. Drop such
    keys so Pydantic falls back to the field's own default instead of raising.
    Fields whose actual default IS None (e.g. Optional date bounds) are left
    untouched - null is a legitimate value there.
    """
    for name, field in model_cls.model_fields.items():
        if name not in data or data[name] is not None:
            continue
        has_real_default = field.default is not PydanticUndefined and field.default is not None
        has_factory_default = field.default_factory is not None
        if has_real_default or has_factory_default:
            del data[name]
    return data


def parse_structured(
    model_cls,
    system_prompt,
    user_prompt,
    model=GEMINI_MODEL,
    max_tokens=DEFAULT_MAX_TOKENS,
):
    """
    Call the model in JSON mode and validate the response against a Pydantic model.
    Client-side validation handles cases where the compatibility endpoint does
    not support the requested structured-output format. Callers should catch
    malformed or empty responses and fall back as needed.
    """
    client = get_client()
    schema = model_cls.model_json_schema()
    response = create_completion(
        client,
        model=model,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "system",
                "content": system_prompt
                + "\n\nRespond with ONLY a single valid JSON object — no prose, no "
                "markdown code fences — matching exactly this JSON schema:\n"
                + json.dumps(schema),
            },
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Model returned an empty response.")
    data = _drop_defaultable_nulls(_loads_lenient(content), model_cls)
    return model_cls.model_validate(data)
