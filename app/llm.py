# Talks to the LLM (Google Gemini) with timeout, retry and fallback.
#
# Logic of ask_llm():
#   try the main model      -> up to LLM_MAX_RETRIES times, waiting 1s, 2s, ... between tries
#   if it still fails, try the fallback model the same way
#   if that also fails, raise LLMError (main.py turns it into HTTP 503)

import logging
import time

from app import config

logger = logging.getLogger(__name__)

_gemini_client = None


class LLMError(Exception):
    pass


def get_gemini_client():
    # Create the client only once and reuse it.
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        from google.genai import types

        _gemini_client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            # timeout is in milliseconds; a hanging call is stopped after this
            http_options=types.HttpOptions(timeout=config.LLM_TIMEOUT_SECONDS * 1000),
        )
    return _gemini_client


def call_model(model, question):
    # One single call to the LLM. Returns answer text + token usage.
    if config.LLM_PROVIDER == "mock":
        answer = f"(mock answer) You asked: {question}"
        return {
            "answer": answer,
            "model": "mock",
            "prompt_tokens": len(question.split()),
            "answer_tokens": len(answer.split()),
        }

    client = get_gemini_client()
    response = client.models.generate_content(model=model, contents=question)
    usage = response.usage_metadata
    return {
        "answer": response.text or "",
        "model": model,
        "prompt_tokens": (usage.prompt_token_count or 0) if usage else 0,
        "answer_tokens": (usage.candidates_token_count or 0) if usage else 0,
    }


def ask_llm(question):
    models = [config.LLM_MODEL, config.LLM_FALLBACK_MODEL]

    for model in models:
        for attempt in range(1, config.LLM_MAX_RETRIES + 1):
            try:
                return call_model(model, question)
            except Exception as error:
                logger.warning("LLM call failed (model=%s, attempt=%s): %s", model, attempt, error)
                if attempt < config.LLM_MAX_RETRIES:
                    time.sleep(2 ** (attempt - 1))  # exponential backoff: 1s, 2s, 4s...
        logger.warning("Model %s failed, trying fallback (if any)", model)

    raise LLMError("All LLM models failed")
