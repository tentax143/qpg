"""
Bedrock Mantle client — uses the OpenAI-compatible Chat Completions endpoint
on bedrock-mantle.{region}.api.aws/v1.

The Converse / bedrock-runtime endpoint is not permitted for these API keys.
Key rotation: two keys from .env are round-robined automatically.
"""

import os
import time
import base64
import random
import hashlib
import threading
from contextlib import contextmanager

import requests


REGION    = os.environ.get("AWS_REGION", "ap-south-1")
BASE_URL  = f"https://bedrock-mantle.{REGION}.api.aws/v1"

# Best available models confirmed working via Chat Completions
GEN_MODEL = "deepseek.v3.2"           # primary — large, instruction-following
VAL_MODEL = "qwen.qwen3-32b"          # secondary — fast, accurate

# Paper-level audit model. Judging whether one question gives away another's answer is a
# reasoning task over the WHOLE assembled paper, not a per-question format check — it wants a
# stronger long-context model than VAL_MODEL. It must also NOT be GEN_MODEL: a model auditing
# its own output rationalises it, and cross-model disagreement is the entire point.
# Override with QPG_AUDIT_MODEL. This default is NOT confirmed against the endpoint the way
# GEN/VAL are, so callers must fall back to GEN_MODEL when it is not served (see
# section_generator._audit_converse).
AUDIT_MODEL = os.environ.get("QPG_AUDIT_MODEL", "").strip() or "zai.glm-5"

_key_index = 0
_key_lock = threading.Lock()   # converse() is now called from thread pools — keep rotation atomic


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


def num_keys():
    """How many Mantle API keys are configured — used to size parallel call pools
    (e.g. chunk enrichment runs N threads per key)."""
    return len(_get_keys())


def _next_key():
    global _key_index
    keys = _get_keys()
    if not keys:
        raise RuntimeError(
            "No Mantle API keys found. Set MANTLE_API_KEYS or "
            "LLM_API_1_MANTLE_KEY / LLM_API_2_MANTLE_KEY in .env"
        )
    with _key_lock:
        key = keys[_key_index % len(keys)]
        _key_index += 1
    return key


# ─────────────────────────────────────────────
# Observability
# ─────────────────────────────────────────────
# Celery redirects stdout into the worker log, so these prints land there. Every line is ASCII
# and key=value shaped, so `grep "[Mantle] OK"` / `grep "key=2/2"` stay usable in the ~200-line
# log a single paper produces.

_stage_local = threading.local()
_stats_lock = threading.Lock()
_call_seq = 0
_run_stats = {"calls": 0, "in": 0, "out": 0, "retries": 0, "failovers": 0, "failures": 0,
              "seconds": 0.0, "by_key": {}, "by_model": {}, "by_stage": {}}


def _stage_stack():
    if not hasattr(_stage_local, "stack"):
        _stage_local.stack = []
    return _stage_local.stack


def _slug(s) -> str:
    """Collapse whitespace to underscores. Section names and pipeline step titles contain
    spaces ('Section A — Objective', 'Answer-leak audit (V11)'), and an unquoted space inside a
    key=value log field makes the whole line unsplittable — `stage=Section B/gen model=...`
    parses as stage='Section' with a stray token. Slugging keeps lines both readable and
    greppable, which is the point of the format."""
    return "_".join(str(s or "").split())


@contextmanager
def stage(label):
    """Name what the calling thread is doing, so every converse() line says what it is FOR
    without threading a `purpose=` argument through ~30 call sites.

    Thread-local on purpose: sections are generated on a ThreadPoolExecutor, so three parallel
    sections each push their own label and never overwrite each other's context. Nested stages
    compose with '/' — "Section B:gen/v4-mcq-verify".
    """
    st = _stage_stack()
    st.append(str(label))
    try:
        yield
    finally:
        if st:
            st.pop()


def current_stage() -> str:
    """The calling thread's stage path, '-' when nothing is set."""
    return "/".join(_slug(x) for x in _stage_stack()) or "-"


def _key_label(key: str) -> str:
    """Identify a key WITHOUT ever printing it: 1-based position plus a 4-hex SHA-256
    fingerprint. Enough to tell which key is rate-limited, unauthorized or dead and to correlate
    that across lines; useless to anyone who reads the log or ships it to support."""
    keys = _get_keys()
    try:
        pos = keys.index(key) + 1
    except ValueError:
        pos = 0
    return f"{pos}/{len(keys)}:{hashlib.sha256(key.encode('utf-8')).hexdigest()[:4]}"


def _fmt_k(n) -> str:
    n = int(n or 0)
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def reset_run_stats():
    """Start a fresh tally. Called at the top of a Celery task so the running totals printed on
    every line are per-paper rather than per-worker-process."""
    global _call_seq
    with _stats_lock:
        _call_seq = 0
        _run_stats.update({"calls": 0, "in": 0, "out": 0, "retries": 0, "failovers": 0,
                           "failures": 0, "seconds": 0.0})
        for k in ("by_key", "by_model", "by_stage"):
            _run_stats[k] = {}


def run_stats() -> dict:
    with _stats_lock:
        out = dict(_run_stats)
        for k in ("by_key", "by_model", "by_stage"):
            out[k] = dict(_run_stats[k])
        return out


def run_stats_lines() -> list:
    """Multi-line end-of-run summary: totals, then the per-model and per-KEY split. The key split
    is what answers 'which key is actually being used' and shows an unbalanced rotation."""
    s = run_stats()
    lines = [
        f"calls={s['calls']} in={_fmt_k(s['in'])} out={_fmt_k(s['out'])} "
        f"llm_time={s['seconds']:.1f}s retries={s['retries']} "
        f"failovers={s['failovers']} failures={s['failures']}"
    ]
    if s["by_model"]:
        lines.append("by model: " + "  ".join(
            f"{m}={v['calls']}call/{_fmt_k(v['in'])}in/{_fmt_k(v['out'])}out/{v['seconds']:.0f}s"
            for m, v in sorted(s["by_model"].items())))
    if s["by_key"]:
        lines.append("by key:   " + "  ".join(
            f"{k}={v['calls']}call/{v['errors']}err" for k, v in sorted(s["by_key"].items())))
    if s["by_stage"]:
        top = sorted(s["by_stage"].items(), key=lambda kv: -kv[1]["seconds"])[:8]
        lines.append("slowest stages: " + "  ".join(
            f"{st}={v['seconds']:.1f}s/{v['calls']}call" for st, v in top))
    return lines


def keys_summary() -> str:
    """Which keys this worker will rotate through — fingerprints only, never the secrets."""
    keys = _get_keys()
    if not keys:
        return "NO KEYS CONFIGURED (set MANTLE_API_KEYS or LLM_API_1/2_MANTLE_KEY)"
    return f"{len(keys)} key(s) rotating: " + ", ".join(_key_label(k) for k in keys)


def models_summary() -> str:
    return f"gen={GEN_MODEL} val={VAL_MODEL} audit={AUDIT_MODEL} region={REGION}"


def _bump(bucket: str, name: str, **deltas):
    with _stats_lock:
        d = _run_stats[bucket].setdefault(
            name, {"calls": 0, "in": 0, "out": 0, "seconds": 0.0, "errors": 0})
        for k, v in deltas.items():
            d[k] = d.get(k, 0) + v


def _reserve_key_start():
    """Reserve a starting index into the key list for one converse() call and advance the
    shared rotation cursor. Each call begins on a different key (spreads load across keys under
    parallel use); converse() then walks forward from this start on auth failover, so a call
    that draws a dead key deterministically tries the OTHER key(s) next — regardless of what
    concurrent calls do to the shared cursor in between."""
    global _key_index
    with _key_lock:
        start = _key_index
        _key_index += 1
    return start


def _chat(
    model_id: str,
    messages: list,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    retries: int = 3,
    timeout=None,
    stage: str = "",
    size_label: str = "",
    kind: str = "text",
):
    """
    Shared core for every Mantle Chat Completions call — text AND vision.

    Both entry points come through here so they share ONE key rotation, ONE 401 failover and ONE
    set of log lines / counters. image_finder used to keep its own `_key_idx` cursor with no lock
    and no failover: two parallel sections could draw the same key, and a dead key just failed the
    vision call outright instead of trying its sibling.

    `timeout` is a (connect, read) tuple. When None it is derived from `max_tokens`: a short
    connect window so a stalled TLS handshake under parallel load fails fast and retries
    quickly (instead of burning the whole window), and a READ window that scales with the
    requested output — a large generation (e.g. an 8k-token Tamil section) legitimately
    streams for several minutes, where a flat 120s read timeout truncated it into a hard
    failure and the whole section was dropped from the paper.

    Returns:
        (text: str, input_tokens: int, output_tokens: int)
    """
    url = f"{BASE_URL}/chat/completions"

    if timeout is None:
        read_timeout = min(300, max(120, 90 + max_tokens * 0.05))
        timeout = (15, read_timeout)

    body = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    keys = _get_keys()
    if not keys:
        raise RuntimeError(
            "No Mantle API keys found. Set MANTLE_API_KEYS or "
            "LLM_API_1_MANTLE_KEY / LLM_API_2_MANTLE_KEY in .env"
        )
    n_keys = len(keys)
    key_start = _reserve_key_start()

    global _call_seq
    with _stats_lock:
        _call_seq += 1
        call_no = _call_seq
    # The thread-local stack says WHERE we are (which section, which pipeline pass); the optional
    # `stage` argument says WHICH CHECK is calling, so a line reads "Section_B/v4-mcq-verify".
    # Built from the parts rather than prefixing current_stage(), so a call with only the argument
    # set logs "v4-mcq-verify" and not the placeholder-prefixed "-/v4-mcq-verify".
    st = "/".join([_slug(x) for x in _stage_stack()] + ([_slug(stage)] if stage else [])) or "-"
    t_call = time.time()

    for attempt in range(retries):
        # Deterministic per-attempt key: attempt 0 uses the reserved start key; each retry
        # walks to the next key. Independent of the shared cursor, so the auth failover below
        # always reaches a DIFFERENT key even when concurrent calls churn the cursor.
        api_key = keys[(key_start + attempt) % n_keys]
        key_lbl = _key_label(api_key)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        # Printed BEFORE the request so a hung or timing-out call is visible while it hangs —
        # previously a stalled section produced no log line at all until it failed.
        print(
            f"[Mantle] START #{call_no} kind={kind} stage={st} model={model_id} key={key_lbl} "
            f"attempt={attempt + 1}/{retries} {size_label} "
            f"max_tok={max_tokens} timeout={timeout[0]}/{timeout[1]:.0f}s"
        )
        t_attempt = time.time()
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
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

            secs = time.time() - t_attempt
            with _stats_lock:
                _run_stats["calls"] += 1
                _run_stats["in"] += int(input_tokens or 0)
                _run_stats["out"] += int(output_tokens or 0)
                _run_stats["seconds"] += secs
                totals = (_run_stats["calls"], _run_stats["in"], _run_stats["out"])
            # 'in' is a keyword, so the token deltas go in through **kwargs.
            _bump("by_model", model_id, calls=1, seconds=secs,
                  **{"in": int(input_tokens or 0), "out": int(output_tokens or 0)})
            _bump("by_key", key_lbl, calls=1)
            _bump("by_stage", st, calls=1, seconds=secs)
            # Only quote a rate over a window long enough to mean anything — a sub-50ms call
            # (cached/stubbed/error-shaped) otherwise reports millions of tokens per second.
            rate = f" {(output_tokens or 0) / secs:.0f}tok/s" if secs >= 0.05 else ""
            print(
                f"[Mantle] OK    #{call_no} kind={kind} stage={st} model={model_id} key={key_lbl} "
                f"{secs:.1f}s in={input_tokens} out={output_tokens}{rate}"
                f"{' TRUNCATED?' if output_tokens and output_tokens >= max_tokens else ''}"
                f" | run: {totals[0]} calls in={_fmt_k(totals[1])} out={_fmt_k(totals[2])}"
            )
            return content.strip(), input_tokens, output_tokens

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            # An unauthorized/forbidden key is a per-KEY fault, not a transient one: retrying the
            # SAME key is pointless, but a sibling key may still be valid. Fail over to the next
            # key immediately (no backoff) while an untried key remains. This is the difference
            # between "~half of all LLM calls hard-fail on a rotated bad key" (whole sections
            # silently dropped from the paper) and "one dead key is skipped." A 401/403 with a
            # single key configured — or after every key has been tried — still raises.
            _bump("by_key", key_lbl, errors=1)
            if status in (401, 403) and n_keys > 1 and (attempt + 1) < min(retries, n_keys):
                with _stats_lock:
                    _run_stats["failovers"] += 1
                print(
                    f"[Mantle] KEYDEAD #{call_no} stage={st} model={model_id} key={key_lbl} "
                    f"HTTP {status} unauthorized after {time.time() - t_attempt:.1f}s — "
                    f"failing over to the next key ({attempt + 1}/{n_keys})"
                )
                continue
            if status in (429, 503) and attempt < retries - 1:
                wait = (2 ** attempt) + random.random()
                with _stats_lock:
                    _run_stats["retries"] += 1
                print(
                    f"[Mantle] RETRY #{call_no} stage={st} model={model_id} key={key_lbl} "
                    f"HTTP {status} ({'rate limited' if status == 429 else 'unavailable'}) "
                    f"— retry {attempt + 1}/{retries} in {wait:.1f}s"
                )
                time.sleep(wait)
                continue
            with _stats_lock:
                _run_stats["failures"] += 1
            print(f"[Mantle] FAIL  #{call_no} stage={st} model={model_id} key={key_lbl} "
                  f"HTTP {status} after {time.time() - t_call:.1f}s: {e}")
            raise

        except Exception as e:
            _bump("by_key", key_lbl, errors=1)
            if attempt < retries - 1:
                wait = (2 ** attempt) + random.random()
                with _stats_lock:
                    _run_stats["retries"] += 1
                print(
                    f"[Mantle] RETRY #{call_no} stage={st} model={model_id} key={key_lbl} "
                    f"{type(e).__name__} after {time.time() - t_attempt:.1f}s: {e} "
                    f"— retry {attempt + 1}/{retries} in {wait:.1f}s"
                )
                time.sleep(wait)
                continue
            with _stats_lock:
                _run_stats["failures"] += 1
            print(f"[Mantle] FAIL  #{call_no} stage={st} model={model_id} key={key_lbl} "
                  f"{type(e).__name__} after {time.time() - t_call:.1f}s: {e}")
            raise

    return "", 0, 0


def converse(
    model_id: str,
    prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    system_prompt: str = None,
    retries: int = 3,
    timeout=None,
    stage: str = "",
):
    """Text chat completion. Returns (text, input_tokens, output_tokens)."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return _chat(model_id, messages, max_tokens=max_tokens, temperature=temperature,
                 retries=retries, timeout=timeout, stage=stage, kind="text",
                 size_label=f"prompt={_fmt_k(len(prompt))}ch")


def converse_vision(
    model_id: str,
    prompt: str,
    image_bytes: bytes,
    mime: str = "image/png",
    max_tokens: int = 700,
    temperature: float = 0.1,
    retries: int = 3,
    timeout=None,
    stage: str = "",
):
    """Vision chat completion — a base64 data-URI image alongside the text prompt.

    Exists so image/vision traffic goes through the SAME path as text: same fingerprinted key
    logging, same 401 failover, same by-model/by-key/by-stage counters. Previously this lived in
    image_finder as a private `_vision_call` that logged only failures, so a paper's ~6 Kimi
    vision calls were invisible in the Celery log and absent from every token total.

    Returns (text, input_tokens, output_tokens); the caller decides what "" means.
    """
    data_uri = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]}]
    if timeout is None:
        timeout = (15, 90)          # the old _vision_call window; images are not streamed long
    return _chat(model_id, messages, max_tokens=max_tokens, temperature=temperature,
                 retries=retries, timeout=timeout, stage=stage, kind="vision",
                 size_label=f"prompt={_fmt_k(len(prompt))}ch img={len(image_bytes) // 1024}kb")


@contextmanager
def external_call(label: str, detail: str = ""):
    """Log a non-Mantle network call (Pollinations image gen, Wikimedia search, Ollama embed).

    These are not model completions so they carry no tokens and stay out of the LLM counters, but
    they can hang or fail and were previously silent on success. Emits [HTTP] START/OK/FAIL with
    the current stage, and never swallows the exception.
    """
    st = current_stage()
    lbl = _slug(label)
    print(f"[HTTP] START stage={st} target={lbl}{(' ' + detail) if detail else ''}")
    t = time.time()
    try:
        yield
    except Exception as e:
        print(f"[HTTP] FAIL  stage={st} target={lbl} {type(e).__name__} "
              f"after {time.time() - t:.1f}s: {e}")
        raise
    else:
        print(f"[HTTP] OK    stage={st} target={lbl} {time.time() - t:.1f}s")


def invoke_embed(model_id: str, input_text: str):
    """
    Titan embed is on bedrock-runtime which is blocked for these keys.
    Raise clearly so callers fall back to Ollama.
    """
    raise RuntimeError(
        "invoke_embed: bedrock-runtime is not accessible with Mantle API keys. "
        "Ensure Ollama is running for embeddings (USE_OLLAMA=True)."
    )
