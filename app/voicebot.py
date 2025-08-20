"""Simple wrapper around the OpenAI Chat API used for lead engagement."""

import os
from openai import OpenAI

MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def coldcall_lead(messages: list, temperature: float = 0.7, model: str = MODEL_NAME) -> str:
    """Return the assistant's reply for the provided chat ``messages``."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content
    except Exception as e:
        raise RuntimeError(f"AI response failed: {str(e)}") from e

