"""Thin wrapper over Gemini: retries, model fallback, JSON output, call log.

Every call is appended to data/runtime/llm_calls.jsonl with model, token
counts and latency, so the cost and behaviour of the AI loops are visible.
"""
import json
import time
from datetime import datetime

from google import genai
from google.genai import errors, types

from . import config

_client = None


class LLMError(RuntimeError):
    pass


class Response:
    """The SDK response plus which model actually answered."""

    def __init__(self, resp, model):
        self._resp, self.model_used = resp, model

    def __getattr__(self, name):
        return getattr(self._resp, name)


def client():
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise LLMError("GEMINI_API_KEY is missing in .env")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _log(entry):
    entry["at"] = datetime.now().isoformat(timespec="seconds")
    with open(config.LLM_LOG, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def _retryable(e):
    code = getattr(e, "code", None)
    return code in (429, 500, 502, 503, 504) or "UNAVAILABLE" in str(e) or "overloaded" in str(e).lower()


def generate(contents, *, purpose, models=None, system=None, schema=None, tools=None,
             temperature=0.0, max_output_tokens=32768):
    """Call Gemini, falling back across models. Returns the raw response."""
    if config.BUDGET_INR and usage_summary()["est_inr"] >= config.BUDGET_INR:
        raise LLMError(f"Demo budget of Rs {config.BUDGET_INR:g} for AI calls is used up. "
                       "Everything that does not need the AI (comparison, review, award, Excel) still works.")
    models = models or config.EXTRACT_MODELS
    cfg = dict(temperature=temperature, max_output_tokens=max_output_tokens)
    if system:
        cfg["system_instruction"] = system
    if schema is not None:
        cfg["response_mime_type"] = "application/json"
        cfg["response_json_schema"] = schema
    if tools:
        cfg["tools"] = tools
        cfg["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
    last = None
    for model in models:
        for attempt in range(3):
            t0 = time.time()
            try:
                resp = client().models.generate_content(model=model, contents=contents,
                                                        config=types.GenerateContentConfig(**cfg))
                u = resp.usage_metadata
                _log({"purpose": purpose, "model": model, "ok": True, "secs": round(time.time() - t0, 1),
                      "in_tokens": getattr(u, "prompt_token_count", None),
                      "out_tokens": getattr(u, "candidates_token_count", None),
                      "thinking_tokens": getattr(u, "thoughts_token_count", None)})
                return Response(resp, model)
            except errors.APIError as e:
                last = e
                _log({"purpose": purpose, "model": model, "ok": False, "error": str(e)[:300]})
                if e.code in (401, 403):
                    raise LLMError(f"Gemini rejected the API key: {e}") from e
                if e.code == 402:
                    raise LLMError("Gemini credits are depleted - top up in AI Studio.") from e
                if e.code == 400 and schema is not None and "schema" in str(e).lower():
                    # Some models reject parts of JSON Schema; retry with the schema in the prompt instead.
                    cfg.pop("response_json_schema", None)
                    contents = list(contents) + [
                        "Return JSON only, matching this JSON Schema exactly:\n" + json.dumps(schema)]
                    continue
                if e.code == 404:
                    break  # model not available on this key - try the next one
                if _retryable(e):
                    time.sleep(2 * (attempt + 1))
                    continue
                break
    raise LLMError(f"All models failed for {purpose}: {last}")


def generate_json(contents, *, purpose, schema, models=None, system=None, temperature=0.0):
    resp = generate(contents, purpose=purpose, models=models, system=system, schema=schema,
                    temperature=temperature)
    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return json.loads(text), resp.model_used
    except json.JSONDecodeError as e:
        raise LLMError(f"Model returned invalid JSON for {purpose}: {text[:300]}") from e


def usage_summary():
    """Totals from the call log, for the sidebar."""
    calls = ok = tin = tout = 0
    if config.LLM_LOG.exists():
        for line in config.LLM_LOG.read_text().splitlines():
            r = json.loads(line)
            calls += 1
            if r.get("ok"):
                ok += 1
                tin += r.get("in_tokens") or 0
                tout += (r.get("out_tokens") or 0) + (r.get("thinking_tokens") or 0)
    est = tin / 1000 * config.COST_IN_PER_1K + tout / 1000 * config.COST_OUT_PER_1K
    return {"calls": calls, "ok": ok, "in_tokens": tin, "out_tokens": tout, "est_inr": round(est, 1)}
