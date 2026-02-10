"""LLM service: OpenRouter for all LLM calls (chat + embeddings).

All models are accessed through OpenRouter API, which provides:
- Anthropic Claude (claude-sonnet-4-20250514)
- xAI Grok (x-ai/grok-4, etc.)
- Google Gemini (embeddings)
- Any other model via unified API

Includes retry logic and fallback models for resilience.
"""

import asyncio
from typing import Optional
from openai import AsyncOpenAI

from src.config import get_settings, MODELS
from src.utils.logger import logger


_openrouter_client: Optional[AsyncOpenAI] = None

# Fallback models: primary -> fallback
FALLBACK_MODELS = {
    "anthropic/claude-sonnet-4-20250514": "google/gemini-2.0-flash-001",
    "google/gemini-2.0-flash-001": "google/gemini-2.5-flash-preview-05-20",
}

# Max retry attempts per model
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1.0


def _get_openrouter_client() -> AsyncOpenAI:
    """Get OpenRouter client (used for all LLM and embedding calls)."""
    global _openrouter_client
    if _openrouter_client is None:
        settings = get_settings()
        _openrouter_client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
            default_headers={
                "HTTP-Referer": settings.app_url,
                "X-Title": settings.app_name,
            },
        )
    return _openrouter_client


def get_llm_client() -> AsyncOpenAI:
    """Get LLM client for chat completions (OpenRouter)."""
    return _get_openrouter_client()


def calculate_cost(usage, model: str) -> float:
    """Estimate cost based on model and usage (per 1M tokens)."""
    costs = {
        # Anthropic via OpenRouter
        "anthropic/claude-sonnet-4-20250514": (3.0, 15.0),
        "anthropic/claude-3-5-haiku-20241022": (0.80, 4.0),
        # Google via OpenRouter
        "google/gemini-2.0-flash-001": (0.10, 0.40),
        "google/gemini-embedding-001": (0.15, 0.0),
        # xAI via OpenRouter (if used)
        "x-ai/grok-4": (3.0, 15.0),
        "x-ai/grok-3-mini": (0.50, 2.0),
    }
    rates = costs.get(model, (1.0, 4.0))
    input_cost = (usage.prompt_tokens / 1_000_000) * rates[0]
    output_cost = (usage.completion_tokens / 1_000_000) * rates[1]
    return round(input_cost + output_cost, 6)


async def _call_single(
    client: AsyncOpenAI,
    model: str,
    messages: list,
    max_tokens: int,
    temperature: float,
) -> dict:
    """Call a single LLM model with retry logic."""
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return {
                "content": response.choices[0].message.content,
                "tokens_input": response.usage.prompt_tokens,
                "tokens_output": response.usage.completion_tokens,
                "model": model,
                "cost": calculate_cost(response.usage, model),
            }
        except Exception as e:
            last_error = e
            status_code = getattr(e, "status_code", None)

            # Don't retry on 4xx errors (except 429 rate limit)
            if status_code and 400 <= status_code < 500 and status_code != 429:
                raise

            logger.warning(
                f"LLM attempt {attempt + 1}/{MAX_RETRIES} failed for {model}: "
                f"[{type(e).__name__}] status={status_code}"
            )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY_SECONDS * (attempt + 1))

    raise last_error


async def call_llm(
    messages: list,
    task_type: str = "qa",
    max_tokens: int = 2000,
    temperature: float = 0.7,
) -> dict:
    """Call LLM with retry and fallback model support.
    
    Tries the primary model first with retries, then falls back to
    an alternative model if the primary fails.
    """
    client = get_llm_client()
    model = MODELS.get(task_type, MODELS["qa"])
    fallback = FALLBACK_MODELS.get(model)

    # Try primary model
    try:
        return await _call_single(client, model, messages, max_tokens, temperature)
    except Exception as primary_error:
        logger.warning(
            f"Primary model {model} failed: {type(primary_error).__name__}: {primary_error}"
        )

        # Try fallback model
        if fallback:
            try:
                logger.info(f"Trying fallback model: {fallback}")
                return await _call_single(
                    client, fallback, messages, max_tokens, temperature
                )
            except Exception as fallback_error:
                logger.error(
                    f"Fallback model {fallback} also failed: "
                    f"{type(fallback_error).__name__}: {fallback_error}"
                )

        # All models failed
        raise primary_error


async def get_embedding(text: str) -> list:
    """Generate embedding for text via OpenRouter.
    
    Includes retry logic for transient failures.
    """
    client = _get_openrouter_client()
    model = MODELS["embedding"]

    # Truncate to ~8000 chars for embedding models
    text = text[:8000]

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = await client.embeddings.create(
                model=model,
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            last_error = e
            status_code = getattr(e, "status_code", None)
            if status_code and 400 <= status_code < 500 and status_code != 429:
                raise
            logger.warning(
                f"Embedding attempt {attempt + 1}/{MAX_RETRIES} failed: "
                f"[{type(e).__name__}] status={status_code}"
            )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY_SECONDS * (attempt + 1))

    raise last_error
