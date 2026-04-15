import os
from typing import Optional, Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def get_provider_config(provider: str) -> Dict[str, Any]:
    provider = provider.lower().strip()

    if provider == "openai":
        return {
            "provider": "openai",
            "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
            "base_url": None,
            "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        }

    if provider == "deepseek":
        return {
            "provider": "deepseek",
            "api_key": os.getenv("DEEPSEEK_API_KEY", "").strip(),
            "base_url": "https://api.deepseek.com/v1",
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        }

    raise ValueError(f"Unbekannter Provider: {provider}")


def build_client(provider: str) -> OpenAI:
    cfg = get_provider_config(provider)

    if not cfg["api_key"]:
        raise RuntimeError(f"Kein API-Key für Provider '{provider}' hinterlegt.")

    if cfg["base_url"]:
        return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])

    return OpenAI(api_key=cfg["api_key"])


def check_provider_availability(provider: str) -> Dict[str, Any]:
    """
    Prüft grob:
    - Ist Key vorhanden?
    - Kann ein Minimal-Request erfolgreich ausgeführt werden?
    """
    try:
        cfg = get_provider_config(provider)

        if not cfg["api_key"]:
            return {
                "provider": provider,
                "available": False,
                "reason": "API-Key fehlt",
            }

        client = build_client(provider)

        # Kleiner Test-Call
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": "Antwort nur mit 'ok'."},
                {"role": "user", "content": "Test"}
            ],
            max_tokens=5,
            temperature=0
        )

        content = response.choices[0].message.content or ""

        return {
            "provider": provider,
            "available": True,
            "reason": None,
            "model": cfg["model"],
            "test_response": content.strip(),
        }

    except Exception as e:
        return {
            "provider": provider,
            "available": False,
            "reason": str(e),
        }


def ask_llm(prompt: str, provider: str = "deepseek", system_prompt: Optional[str] = None) -> str:
    cfg = get_provider_config(provider)
    client = build_client(provider)

    if not system_prompt:
        system_prompt = "Du bist ein Spielleiter für ein Fantasy-Textabenteuer."

    response = client.chat.completions.create(
        model=cfg["model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=500,
    )

    return response.choices[0].message.content or ""
