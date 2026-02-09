"""LLM service: xAI Grok for chat, OpenRouter/Gemini for embeddings."""

from typing import Optional
from openai import AsyncOpenAI

from src.config import get_settings, MODELS
from src.utils.logger import logger


_llm_client: Optional[AsyncOpenAI] = None
_embedding_client: Optional[AsyncOpenAI] = None


def get_llm_client() -> AsyncOpenAI:
    """Get or create xAI Grok client for chat completions."""
    global _llm_client
    if _llm_client is None:
        settings = get_settings()
        _llm_client = AsyncOpenAI(
            base_url="https://api.x.ai/v1",
            api_key=settings.xai_api_key,
        )
    return _llm_client


def _get_embedding_client() -> AsyncOpenAI:
    """Get OpenRouter client for embeddings (Gemini Embedding)."""
    global _embedding_client
    if _embedding_client is None:
        settings = get_settings()
        _embedding_client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
        )
    return _embedding_client


def calculate_cost(usage, model: str) -> float:
    """Estimate cost based on model and usage (per 1M tokens)."""
    costs = {
        "grok-4": (3.0, 15.0),
        "grok-4-1-fast-reasoning": (0.20, 0.50),
        "grok-4-1-fast-non-reasoning": (0.20, 0.50),
        "grok-3": (2.0, 8.0),
        "grok-3-mini": (0.50, 2.0),
        "google/gemini-embedding-001": (0.15, 0.0),
    }
    rates = costs.get(model, (1.0, 4.0))
    input_cost = (usage.prompt_tokens / 1_000_000) * rates[0]
    output_cost = (usage.completion_tokens / 1_000_000) * rates[1]
    return round(input_cost + output_cost, 6)


async def call_llm(
    messages: list,
    task_type: str = "qa",
    max_tokens: int = 2000,
    temperature: float = 0.7,
) -> dict:
    """Call LLM via xAI Grok API."""
    client = get_llm_client()
    model = MODELS.get(task_type, MODELS["qa"])

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
        error_type = type(e).__name__
        status_code = getattr(e, "status_code", None)
        logger.error(
            f"xAI Grok error ({model}): [{error_type}] status={status_code} {e}",
            exc_info=True,
        )
        raise


async def get_embedding(text: str) -> list:
    """Generate embedding for text via OpenRouter (google/gemini-embedding-001)."""
    client = _get_embedding_client()
    settings = get_settings()
    model = MODELS["embedding"]

    # Gemini embedding max ~2048 tokens; truncate to ~8000 chars
    text = text[:8000]

    try:
        response = await client.embeddings.create(
            model=model,
            input=text,
            extra_headers={
                "HTTP-Referer": settings.app_url,
                "X-Title": settings.app_name,
            },
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(
            f"Embedding error ({model}): [{type(e).__name__}] "
            f"status={getattr(e, 'status_code', None)} {e}"
        )
        raise
