import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai


load_dotenv(Path(__file__).resolve().parent / ".env")

def _build_genai_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=api_key)


client = _build_genai_client()


def summarize_review(prompt: str, comments_text: str) -> str:
    # Use models/* format (same style as backend) to avoid 404s on provider-prefixed names.
    preferred_model = os.getenv("SUMMARY_MODEL", "models/gemini-2.5-flash")
    fallbacks = [
        preferred_model,
        "models/gemini-2.5-flash-lite",
        "models/gemini-2.0-flash",
        "models/gemini-1.5-flash",
    ]

    last_error: Exception | None = None
    for model in fallbacks:
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[prompt, comments_text],
            )
            text = getattr(resp, "text", None)
            if text is None:
                raise RuntimeError(f"Model returned no text content for {model}")
            return str(text)
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"Failed to summarize review comments: {last_error}")
