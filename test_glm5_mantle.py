"""
Manual test: hit the GLM 5 model (`zai.glm-5`) on Bedrock Mantle using BOTH configured
Mantle API keys.

  * Part 1 tests each of the two keys individually (proves both keys authenticate against
    glm-5), calling the OpenAI-compatible /v1/chat/completions endpoint directly.
  * Part 2 uses the app's core.mantle_client.converse(), which round-robins the two keys
    automatically — two calls, so key #1 then key #2 are exercised through the real client.

Run:
    PYTHONUTF8=1 conda run -n tpm --no-capture-output python test_glm5_mantle.py
    python test_glm5_mantle.py "Your custom prompt here"          # optional prompt
    python test_glm5_mantle.py --model zai.glm-4.7 "prompt"        # optional model override

Keys are read from .env (MANTLE_API_KEYS, or LLM_API_1_MANTLE_KEY / LLM_API_2_MANTLE_KEY).
Keys are never printed in full — only a masked fingerprint.
"""
import os
import sys
import argparse
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

REGION = os.environ.get("AWS_REGION", "ap-south-1")
BASE_URL = f"https://bedrock-mantle.{REGION}.api.aws/v1"
DEFAULT_MODEL = "zai.glm-5"


def _load_keys() -> list:
    """Same resolution order as core.mantle_client — CSV first, then the two named vars."""
    csv = os.environ.get("MANTLE_API_KEYS", "")
    keys = [k.strip() for k in csv.split(",") if k.strip()]
    for var in ("LLM_API_1_MANTLE_KEY", "LLM_API_2_MANTLE_KEY"):
        v = os.environ.get(var, "").strip()
        if v and v not in keys:
            keys.append(v)
    return keys


def _mask(key: str) -> str:
    return f"{key[:6]}…{key[-4:]} (len {len(key)})" if len(key) > 12 else "****"


def call_direct(key: str, model: str, prompt: str) -> tuple:
    """One direct chat-completions call with a specific key. Returns (text, in_tok, out_tok)."""
    resp = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
            "temperature": 0.7,
        },
        timeout=(15, 120),
    )
    resp.raise_for_status()
    data = resp.json()
    msg = data["choices"][0]["message"]
    text = (msg.get("content") or msg.get("reasoning_content") or "").strip()
    usage = data.get("usage", {})
    return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def main() -> int:
    ap = argparse.ArgumentParser(description="Test GLM 5 on Mantle with both API keys.")
    ap.add_argument("prompt", nargs="?",
                    default="In one sentence, confirm you are the GLM model and state your version.")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Model id (default {DEFAULT_MODEL})")
    args = ap.parse_args()

    keys = _load_keys()
    print(f"Region     : {REGION}")
    print(f"Model      : {args.model}")
    print(f"Prompt     : {args.prompt}")
    print(f"Keys found : {len(keys)}")
    for i, k in enumerate(keys, 1):
        print(f"   key #{i}: {_mask(k)}")
    if len(keys) < 2:
        print("\n✗ Need at least 2 Mantle API keys configured in .env — aborting.")
        return 1

    # ── Part 1: each key individually ────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("PART 1 — each key called directly against", args.model)
    print("=" * 70)
    ok = 0
    for i, key in enumerate(keys[:2], 1):
        print(f"\n--- Key #{i} ({_mask(key)}) ---")
        try:
            text, itok, otok = call_direct(key, args.model, args.prompt)
            print(f"tokens: in={itok} out={otok}")
            print("response:")
            print(text or "(empty)")
            ok += 1
        except Exception as e:
            print(f"✗ FAILED: {type(e).__name__}: {str(e)[:300]}")

    # ── Part 2: the app client (auto key rotation) ───────────────────────────────
    print("\n" + "=" * 70)
    print("PART 2 — core.mantle_client.converse (round-robins the two keys)")
    print("=" * 70)
    try:
        from core import mantle_client
        for call in (1, 2):
            text, itok, otok = mantle_client.converse(
                model_id=args.model, prompt=args.prompt, max_tokens=512, temperature=0.7,
            )
            print(f"\n--- converse call {call} (client picked the next key) ---")
            print(f"tokens: in={itok} out={otok}")
            print(text or "(empty)")
    except Exception as e:
        print(f"✗ converse path FAILED: {type(e).__name__}: {str(e)[:300]}")
        return 1

    print("\n" + "=" * 70)
    print(f"RESULT: {ok}/2 keys returned a GLM response directly.")
    print("=" * 70)
    return 0 if ok == 2 else 1


if __name__ == "__main__":
    sys.exit(main())
