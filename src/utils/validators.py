"""Input validation utilities."""


def validate_message_length(text: str, max_length: int = 4000) -> bool:
    """Check if message is within allowed length."""
    return len(text) <= max_length


def validate_voice_duration(duration_seconds: int, max_seconds: int = 300) -> bool:
    """Check if voice message is within allowed duration."""
    return duration_seconds <= max_seconds


def sanitize_text(text: str) -> str:
    """Clean up user input text."""
    if not text:
        return ""
    # Strip whitespace, limit length
    text = text.strip()
    if len(text) > 4000:
        text = text[:4000]
    return text
