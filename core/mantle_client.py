"""
Bedrock Mantle client — uses the OpenAI-compatible Chat Completions endpoint
on bedrock-mantle.{region}.api.aws/v1.

The Converse / bedrock-runtime endpoint is not permitted for these API keys.
Key rotation: two keys from .env are round-robined automatically.
"""

import os
import time
import random
import requests


REGION    = os.environ.get("AWS_REGION", "ap-south-1")
BASE_URL  = f"https://bedrock-mantle.{REGION}.api.aws/v1"

# Best available models confirmed working via Chat Completions
GEN_MODEL = "deepseek.v3.2"           # primary — large, instruction-following
VAL_MODEL = "qwen.qwen3-32b"          # secondary — fast, accurate

_key_index = 0


def _get_keys():
    keys_csv = os.environ.get("MANTLE_API_KEYS", "")
    if keys_csv:
        return [k.strip() for k in keys_csv.split(",") if k.strip()]
    keys = []
    for var in ("LLM_API_1_MANTLE_KEY", "LLM_API_2_MANTLE_KEY"):
        v = os.environ.get(var, "").strip()
        if v:
            keys.append(v)
    return keys


def _next_key():
    global _key_index
    keys = _get_keys()
    if not keys:
        raise RuntimeError(
            "No Mantle API keys found. Set MANTLE_API_KEYS or "
            "LLM_API_1_MANTLE_KEY / LLM_API_2_MANTLE_KEY in .env"
        )
    key = keys[_key_index % len(keys)]
    _key_index += 1
    return key


def converse(
    model_id: str,
    prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    system_prompt: str = None,
    retries: int = 5,
):
    """
    Call the Mantle Chat Completions endpoint.

    Returns:
        (text: str, input_tokens: int, output_tokens: int)
    """
    url = f"{BASE_URL}/chat/completions"

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    for attempt in range(retries):
        api_key = _next_key()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=300)
            resp.raise_for_status()
            data = resp.json()

            choice  = data["choices"][0]["message"]
            content = choice.get("content") or ""
            # Some reasoning models put the answer in reasoning_content when content is None
            if not content:
                content = choice.get("reasoning_content") or ""

            usage        = data.get("usage", {})
            input_tokens  = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

            print(
                f"[Mantle] {model_id} — "
                f"in={input_tokens} out={output_tokens} tokens"
            )
            return content.strip(), input_tokens, output_tokens

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status in (429, 503) and attempt < retries - 1:
                wait = (2 ** attempt) + random.random()
                print(
                    f"[Mantle] HTTP {status} — "
                    f"retry {attempt + 1}/{retries} in {wait:.1f}s"
                )
                time.sleep(wait)
                continue
            print(f"[Mantle] HTTP error {status}: {e}")
            raise

        except Exception as e:
            if attempt < retries - 1:
                wait = (2 ** attempt) + random.random()
                print(
                    f"[Mantle] Error ({type(e).__name__}): {e} — "
                    f"retry {attempt + 1}/{retries} in {wait:.1f}s"
                )
                time.sleep(wait)
                continue
            raise

    return "", 0, 0


def invoke_embed(model_id: str, input_text: str):
    """
    Titan embed is on bedrock-runtime which is blocked for these keys.
    Raise clearly so callers fall back to Ollama.
    """
    raise RuntimeError(
        "invoke_embed: bedrock-runtime is not accessible with Mantle API keys. "
        "Ensure Ollama is running for embeddings (USE_OLLAMA=True)."
    )
