"""
Bedrock Mantle access tester.

1. Lists all models available on the Mantle endpoint (/v1/models)
2. Probes each model via:
   - Chat Completions  (bedrock-mantle  /v1/chat/completions)
   - Converse          (bedrock-runtime /model/{id}/converse)
3. Prints a clear pass/fail summary for both keys.

Usage:
    python test.py
    python test.py --region ap-south-1
"""

import os
import sys
import json
import argparse
import requests
from dotenv import load_dotenv
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).parent / ".env")

REGION = os.environ.get("AWS_REGION", "us-east-1")
MANTLE_BASE  = f"https://bedrock-mantle.{REGION}.api.aws/v1"
RUNTIME_BASE = f"https://bedrock-runtime.{REGION}.amazonaws.com"

TEST_PROMPT = "Reply with exactly three words: hello from bedrock"


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------
def get_keys() -> dict[str, str]:
    """Return {name: key} from .env."""
    keys = {}
    csv = os.environ.get("MANTLE_API_KEYS", "")
    if csv:
        for i, k in enumerate(csv.split(","), 1):
            k = k.strip()
            if k:
                name = os.environ.get(f"LLM_API_{i}_NAME", f"key-{i}")
                keys[name] = k
        return keys
    for i in range(1, 10):
        k = os.environ.get(f"LLM_API_{i}_MANTLE_KEY", "").strip()
        if not k:
            break
        name = os.environ.get(f"LLM_API_{i}_NAME", f"key-{i}")
        keys[name] = k
    if not keys:
        print("ERROR: No Mantle API keys found in .env")
        sys.exit(1)
    return keys


def headers(api_key: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


# ---------------------------------------------------------------------------
# 1. List models from Mantle /v1/models
# ---------------------------------------------------------------------------
def list_mantle_models(api_key: str) -> list[str]:
    """Fetch model IDs from the Mantle models endpoint."""
    url = f"{MANTLE_BASE}/models"
    try:
        r = requests.get(url, headers=headers(api_key), timeout=30)
        r.raise_for_status()
        data = r.json()
        # OpenAI-style: {"data": [{"id": "..."}, ...]}
        models = [m["id"] for m in data.get("data", [])]
        return sorted(models)
    except Exception as e:
        print(f"  [models endpoint error] {e}")
        return []


# ---------------------------------------------------------------------------
# 2. Test Chat Completions (Mantle /v1/chat/completions)
# ---------------------------------------------------------------------------
def test_chat_completions(model_id: str, api_key: str) -> tuple[bool, str]:
    """Return (success, detail)."""
    url = f"{MANTLE_BASE}/chat/completions"
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": TEST_PROMPT}],
        "max_tokens": 32,
        "temperature": 0,
    }
    try:
        r = requests.post(url, headers=headers(api_key), json=body, timeout=60)
        if r.status_code == 200:
            choice = r.json()["choices"][0]["message"]
            text = choice.get("content") or choice.get("reasoning_content") or ""
            return True, f'"{text[:80]}"'
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, str(e)[:120]


# ---------------------------------------------------------------------------
# 3. Test Converse (bedrock-runtime /model/{id}/converse)
# ---------------------------------------------------------------------------
def test_converse(model_id: str, api_key: str) -> tuple[bool, str]:
    """Return (success, detail)."""
    url = f"{RUNTIME_BASE}/model/{model_id}/converse"
    body = {
        "messages": [{"role": "user", "content": [{"text": TEST_PROMPT}]}],
        "inferenceConfig": {"maxTokens": 32, "temperature": 0},
    }
    try:
        r = requests.post(url, headers=headers(api_key), json=body, timeout=60)
        if r.status_code == 200:
            text = r.json()["output"]["message"]["content"][0]["text"].strip()
            return True, f'"{text[:80]}"'
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, str(e)[:120]


# ---------------------------------------------------------------------------
# Well-known models to always probe (even if not in /v1/models)
# ---------------------------------------------------------------------------
WELL_KNOWN_CONVERSE = [
    "amazon.nova-pro-v1:0",
    "amazon.nova-lite-v1:0",
    "amazon.nova-micro-v1:0",
    "amazon.nova-premier-v1:0",
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-lite-v1:0",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "us.anthropic.claude-sonnet-4-5-20251001",
    "us.anthropic.claude-haiku-4-5-20251001",
    "meta.llama3-70b-instruct-v1:0",
]

WELL_KNOWN_CHAT = [
    "openai.gpt-oss-120b",
    "openai.gpt-oss-20b",
    "amazon.nova-pro-v1:0",
    "amazon.nova-lite-v1:0",
]


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):  return f"{GREEN}✓  {msg}{RESET}"
def fail(msg): return f"{RED}✗  {msg}{RESET}"
def info(msg): return f"{CYAN}   {msg}{RESET}"


# ---------------------------------------------------------------------------
# Main probe for one key
# ---------------------------------------------------------------------------
def probe_key(key_name: str, api_key: str):
    print(f"\n{'='*70}")
    print(f"{BOLD}Key: {key_name}{RESET}  ({api_key[:12]}…)")
    print(f"{'='*70}")

    # ── Step 1: List Mantle models ──────────────────────────────────────────
    print(f"\n{BOLD}[1] Models available on Mantle endpoint ({MANTLE_BASE}/models){RESET}")
    mantle_models = list_mantle_models(api_key)
    if mantle_models:
        for m in mantle_models:
            print(f"   • {m}")
        print(f"   → {len(mantle_models)} model(s) listed")
    else:
        print(f"   {YELLOW}(no models returned or endpoint not reachable){RESET}")

    # ── Step 2: Chat Completions probe ─────────────────────────────────────
    chat_candidates = sorted(set(mantle_models + WELL_KNOWN_CHAT))
    print(f"\n{BOLD}[2] Chat Completions probe  ({MANTLE_BASE}/chat/completions){RESET}")
    print(f"   Testing {len(chat_candidates)} model(s) …")

    chat_results = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(test_chat_completions, m, api_key): m for m in chat_candidates}
        for f in as_completed(futures):
            m = futures[f]
            success, detail = f.result()
            chat_results[m] = (success, detail)

    for m in sorted(chat_results):
        s, d = chat_results[m]
        line = ok(m) if s else fail(m)
        print(f"   {line}")
        print(info(d))

    # ── Step 3: Converse probe ─────────────────────────────────────────────
    converse_candidates = sorted(set(mantle_models + WELL_KNOWN_CONVERSE))
    print(f"\n{BOLD}[3] Converse probe  ({RUNTIME_BASE}/model/…/converse){RESET}")
    print(f"   Testing {len(converse_candidates)} model(s) …")

    converse_results = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(test_converse, m, api_key): m for m in converse_candidates}
        for f in as_completed(futures):
            m = futures[f]
            success, detail = f.result()
            converse_results[m] = (success, detail)

    for m in sorted(converse_results):
        s, d = converse_results[m]
        line = ok(m) if s else fail(m)
        print(f"   {line}")
        print(info(d))

    # ── Summary ────────────────────────────────────────────────────────────
    chat_ok  = [m for m, (s, _) in chat_results.items()    if s]
    conv_ok  = [m for m, (s, _) in converse_results.items() if s]

    print(f"\n{BOLD}Summary for {key_name}:{RESET}")
    print(f"   Chat Completions accessible : {len(chat_ok)}/{len(chat_candidates)}")
    for m in sorted(chat_ok):
        print(f"     {GREEN}• {m}{RESET}")
    print(f"   Converse accessible         : {len(conv_ok)}/{len(converse_candidates)}")
    for m in sorted(conv_ok):
        print(f"     {GREEN}• {m}{RESET}")

    return {
        "mantle_models": mantle_models,
        "chat_ok": chat_ok,
        "converse_ok": conv_ok,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Test Bedrock Mantle API access")
    parser.add_argument("--region", default=None, help="AWS region (default: us-east-1)")
    args = parser.parse_args()

    if args.region:
        global REGION, MANTLE_BASE, RUNTIME_BASE
        REGION       = args.region
        MANTLE_BASE  = f"https://bedrock-mantle.{REGION}.api.aws/v1"
        RUNTIME_BASE = f"https://bedrock-runtime.{REGION}.amazonaws.com"

    print(f"{BOLD}Bedrock Mantle Access Tester{RESET}")
    print(f"Region : {REGION}")
    print(f"Mantle : {MANTLE_BASE}")
    print(f"Runtime: {RUNTIME_BASE}")

    keys = get_keys()
    print(f"Keys   : {list(keys.keys())}")

    all_results = {}
    for name, key in keys.items():
        all_results[name] = probe_key(name, key)

    # ── Cross-key comparison ───────────────────────────────────────────────
    if len(keys) > 1:
        print(f"\n{'='*70}")
        print(f"{BOLD}Cross-key comparison{RESET}")
        print(f"{'='*70}")
        all_conv = set()
        for r in all_results.values():
            all_conv.update(r["converse_ok"])
        for m in sorted(all_conv):
            who = [n for n, r in all_results.items() if m in r["converse_ok"]]
            print(f"   {GREEN}{m}{RESET}  →  {', '.join(who)}")

    print(f"\n{BOLD}Done.{RESET}\n")


if __name__ == "__main__":
    main()
