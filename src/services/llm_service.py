"""LLM service for OpenRouter API calls."""

import os
from typing import Optional
from openai import AsyncOpenAI

from src.config import get_settings, MODELS
from src.utils.logger import logger


_client: Optional[AsyncOpenAI] = None


def get_llm_client() -> AsyncOpenAI:
    """Get or create OpenRouter async client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
        )
    return _client


def _get_openai_client() -> AsyncOpenAI:
    """Get OpenAI client for embeddings."""
    settings = get_settings()
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.openrouter_api_key,
    )


def calculate_cost(usage, model: str) -> float:
    """Estimate cost based on model and usage."""
    # Approximate costs per 1M tokens (input/output)
    costs = {
        "anthropic/claude-sonnet-4-20250514": (3.0, 15.0),
        "anthropic/claude-haiku-4-5-20251001": (0.25, 1.25),
        "openai/text-embedding-3-small": (0.02, 0.0),
    }
    rates = costs.get(model, (3.0, 15.0))
    input_cost = (usage.prompt_tokens / 1_000_000) * rates[0]
    output_cost = (usage.completion_tokens / 1_000_000) * rates[1]
    return round(input_cost + output_cost, 6)


async def call_llm(
    messages: list,
    task_type: str = "qa",
    max_tokens: int = 2000,
    temperature: float = 0.7,
) -> dict:
    """Call LLM via OpenRouter with fallback."""
    client = get_llm_client()
    settings = get_settings()
    model = MODELS.get(task_type, MODELS["qa"])

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_headers={
                "HTTP-Referer": settings.app_url,
                "X-Title": settings.app_name,
            },
        )

        return {
            "content": response.choices[0].message.content,
            "tokens_input": response.usage.prompt_tokens,
            "tokens_output": response.usage.completion_tokens,
            "model": model,
            "cost": calculate_cost(response.usage, model),
        }

    except Exception as e:
        logger.error(f"OpenRouter error ({model}): {e}")
        # Fallback to Haiku for non-critical tasks
        if task_type in ("summary", "categorize", "direct_line_card"):
            raise
        if "claude-sonnet" in model:
            logger.info("Falling back to Haiku")
            fallback_model = "anthropic/claude-haiku-4-5-20251001"
            try:
                response = await client.chat.completions.create(
                    model=fallback_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_headers={
                        "HTTP-Referer": settings.app_url,
                        "X-Title": settings.app_name,
                    },
                )
                return {
                    "content": response.choices[0].message.content,
                    "tokens_input": response.usage.prompt_tokens,
                    "tokens_output": response.usage.completion_tokens,
                    "model": fallback_model,
                    "cost": calculate_cost(response.usage, fallback_model),
                }
            except Exception as e2:
                logger.error(f"Fallback also failed: {e2}")
                raise
        raise


async def get_embedding(text: str) -> list:
    """Generate embedding for text via OpenRouter."""
    client = _get_openai_client()
    settings = get_settings()

    # Truncate to ~8000 chars to stay within token limits
    text = text[:8000]

    response = await client.embeddings.create(
        model=MODELS["embedding"],
        input=text,
        extra_headers={
            "HTTP-Referer": settings.app_url,
            "X-Title": settings.app_name,
        },
    )

    return response.data[0].embedding
