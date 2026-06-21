"""
image_finder.py — generates images for CBQ/image-based questions.

Pipeline (question-first with smart routing):
  1. section_generator generates the CBQ question + sub_questions from chapter knowledge
  2. generate_image_for_question(question_text, sub_questions, subject, chapter) is called
  3. [Router] ONE LLM call classifies the image need AND extracts what's needed:
       - "rdkit"   → molecular structure diagram for a specific organic compound
       - "diagram" → scientific diagram (biology, physics, chemistry apparatus, etc.)
  4a. rdkit path:  RDKit renders SMILES → clean PNG → Kimi verifies sub-questions
      (on failure) → falls back to Pollinations with router's image_prompt
  4b. diagram path: Wikimedia Commons searched → if suitable: Kimi verifies
                    else: Pollinations with router's image_prompt → Kimi verifies
  5. Return image_path + Kimi-corrected sub_questions for DOCX rendering

Called from section_generator._post_process_cbq_images() after question validation.
Fails silently — returns None so generation continues without image on any error.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import time
import urllib.parse

import requests

from django.conf import settings

from . import mantle_client

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

REGION       = os.environ.get("AWS_REGION", "ap-south-1")
_MANTLE_BASE = f"https://bedrock-mantle.{REGION}.api.aws/v1"
VISION_MODEL = "moonshotai.kimi-k2.5"

POLLINATIONS_KEY   = os.environ.get("POLLINATIONS_API_KEY", "").strip()
POLLINATIONS_MODEL = "gpt-image-2"

_UA = "QPG-ImageFinder/1.0"

# Minimum Kimi score for a Wikimedia image to be accepted
_SCORE_THRESHOLD = 7


# ─── Mantle key rotation (direct HTTP for vision — mantle_client.converse has no image support) ─

_key_idx = 0

def _next_mantle_key() -> str:
    global _key_idx
    keys_csv = os.environ.get("MANTLE_API_KEYS", "")
    keys = [k.strip() for k in keys_csv.split(",") if k.strip()] if keys_csv else []
    if not keys:
        for var in ("LLM_API_1_MANTLE_KEY", "LLM_API_2_MANTLE_KEY"):
            v = os.environ.get(var, "").strip()
            if v:
                keys.append(v)
    if not keys:
        raise RuntimeError("No Mantle API keys found")
    key = keys[_key_idx % len(keys)]
    _key_idx += 1
    return key


def _vision_call(prompt: str, image_bytes: bytes, mime: str, max_tokens: int = 700) -> str:
    """Direct HTTP to Mantle Kimi K2.5 with a base64-encoded image. Returns model text."""
    b64      = base64.b64encode(image_bytes).decode()
    data_uri = f"data:{mime};base64,{b64}"
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ],
    }]
    url = f"{_MANTLE_BASE}/chat/completions"
    for attempt in range(3):
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {_next_mantle_key()}",
                         "Content-Type": "application/json"},
                json={"model": VISION_MODEL, "messages": messages,
                      "max_tokens": max_tokens, "temperature": 0.1},
                timeout=90,
            )
            if not resp.ok:
                logger.warning("[ImageFinder] Kimi %s: %s", resp.status_code, resp.text[:200])
            resp.raise_for_status()
            choice = resp.json()["choices"][0]["message"]
            return (choice.get("content") or choice.get("reasoning_content") or "").strip()
        except Exception as exc:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            logger.error("[ImageFinder] vision call failed: %s", exc)
            return ""
    return ""


# ─── Step 0: Router — classify image type + extract what's needed ─────────────

def _route_and_extract(
    question_text: str,
    sub_questions: list[dict],
    subject: str,
    chapter: str,
) -> dict:
    """
    ONE LLM call that does two things at once:
      - Classifies whether the image should be a molecular structure (rdkit) or a diagram
      - For rdkit: extracts SMILES string + compound name
      - For diagram: writes the Pollinations image generation prompt

    Returns a dict with at minimum {"image_type": "rdkit"|"diagram"}.
    rdkit  → also has "smiles" and "compound_name"
    diagram → also has "image_prompt"

    Falls back to {"image_type": "diagram", "image_prompt": ""} on any error.
    """
    sub_q_lines = "\n".join(
        f"  ({chr(97 + i)}) {sq.get('text', '')} [{sq.get('marks', 1)}m]"
        for i, sq in enumerate(sub_questions[:4])
    )
    system = (
        "You classify CBSE Class 10 CBQ image requirements and extract what is needed to generate the image.\n\n"
        "Classify as 'rdkit' ONLY when the image must show a structural formula diagram of a SPECIFIC organic "
        "compound drawn with covalent bonds and atom symbols "
        "(e.g., ethanoic acid, glucose, methanol, naphthalene, benzene, amino acids). "
        "Do NOT use rdkit for: ionic compounds (NaCl, NaOH, HCl), reaction setups, "
        "apparatus, biological diagrams, or anything that is NOT a single molecule's bond structure.\n\n"
        "Classify as 'diagram' for everything else: biological diagrams (cell, photosynthesis, food chain, "
        "ecosystem, mitosis), chemistry apparatus setups (electrolysis, titration, distillation), "
        "physics experiments (circuits, lenses, prisms, magnets), ionic compounds, "
        "reaction mechanism diagrams, any process or system.\n\n"
        "Return ONLY valid JSON — no markdown, no extra text:\n"
        "  rdkit:   {\"image_type\": \"rdkit\", \"smiles\": \"SMILES_STRING\", \"compound_name\": \"Name\"}\n"
        "  diagram: {\"image_type\": \"diagram\", \"image_prompt\": \"detailed generation prompt\"}\n\n"
        "The image_prompt for diagram must describe: single clean scientific diagram, "
        "pure white background, black line art, NCERT textbook style, "
        "key parts labeled with arrows A/B/C where applicable, no color fills, no shading, "
        "specific enough that an image model draws EXACTLY what the student observes to answer the sub-questions."
    )
    prompt = (
        f"Subject: {subject}, Chapter: {chapter}\n\n"
        f"Question: {question_text}\n\n"
        f"Sub-questions the student must answer by observing the image:\n{sub_q_lines}\n\n"
        "Classify the image type and provide what is needed to generate it."
    )
    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.GEN_MODEL,
            prompt=prompt,
            system_prompt=system,
            max_tokens=350,
            temperature=0.1,
        )
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            result = json.loads(m.group())
            image_type = result.get("image_type", "diagram")
            if image_type == "rdkit":
                logger.info("[ImageFinder] Router → rdkit | compound=%r smiles=%r",
                            result.get("compound_name"), result.get("smiles", "")[:30])
            else:
                logger.info("[ImageFinder] Router → diagram | prompt=%r",
                            result.get("image_prompt", "")[:80])
            return result
    except Exception as exc:
        logger.warning("[ImageFinder] Router LLM call failed: %s", exc)

    return {"image_type": "diagram", "image_prompt": ""}


# ─── RDKit molecular structure renderer ───────────────────────────────────────

def _render_rdkit(smiles: str, compound_name: str) -> tuple[bytes, str]:
    """
    Render a clean molecular structure PNG using RDKit.
    Tries Cairo (highest quality) first, falls back to PIL.
    Returns (png_bytes, "image/png").
    Raises RuntimeError/ValueError on failure — caller handles fallback.
    """
    try:
        from rdkit import Chem
        from rdkit.Chem.Draw import rdMolDraw2D
    except ImportError:
        raise RuntimeError("RDKit not installed — run: pip install rdkit")

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")

    # Cairo produces the cleanest raster output
    try:
        drawer = rdMolDraw2D.MolDraw2DCairo(900, 550)
        _set_draw_options(drawer)
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        png_bytes = drawer.GetDrawingText()
        logger.info("[ImageFinder] RDKit (Cairo) rendered %r — %d bytes", compound_name, len(png_bytes))
        return png_bytes, "image/png"
    except Exception:
        pass

    # PIL fallback (always available when rdkit is installed)
    try:
        from rdkit.Chem import Draw
        img = Draw.MolToImage(mol, size=(900, 550), kekulize=True)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        logger.info("[ImageFinder] RDKit (PIL) rendered %r — %d bytes", compound_name, len(png_bytes))
        return png_bytes, "image/png"
    except Exception as exc:
        raise RuntimeError(f"RDKit rendering failed (both Cairo and PIL): {exc}") from exc


def _set_draw_options(drawer) -> None:
    """Apply clean NCERT-style drawing options to an RDKit drawer."""
    opts = drawer.drawOptions()
    opts.addAtomIndices    = False
    opts.addStereoAnnotation = True
    opts.bondLineWidth     = 2.5
    opts.padding           = 0.15
    opts.backgroundColor   = (1, 1, 1, 1)  # white
    opts.atomLabelFontSize = 16


# ─── Fallback: build image prompt from question context ───────────────────────

def _build_prompt_from_question(
    question_text: str,
    sub_questions: list[dict],
    subject: str,
    chapter: str,
) -> str:
    """
    Fallback: ask LLM for a Pollinations prompt when the router didn't supply one.
    """
    sub_q_lines = "\n".join(
        f"  ({chr(97 + i)}) {sq.get('text', '')} [{sq.get('marks', 1)}m]"
        for i, sq in enumerate(sub_questions[:4])
    )
    system = (
        "You write image generation prompts for CBSE Class 10 exam question papers. "
        "Output ONLY the image generation prompt string — no explanation, no quotes. "
        "The image must be a single clean scientific diagram that students observe to answer the questions. "
        "Style requirements: ONE experiment/process/structure (no collage), pure white background, "
        "black line art, key components labeled with arrows marked A, B, C (if applicable), "
        "NCERT textbook style, no color fills, no shading, simple and unambiguous."
    )
    prompt = (
        f"Subject: {subject}, Chapter: {chapter}\n\n"
        f"Question: {question_text}\n\n"
        f"Sub-questions:\n{sub_q_lines}\n\n"
        "Write a super-detailed image generation prompt describing exactly what diagram to draw."
    )
    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.GEN_MODEL,
            prompt=prompt,
            system_prompt=system,
            max_tokens=200,
            temperature=0.2,
        )
        result = raw.strip().strip('"').strip("'")
        logger.info("[ImageFinder] Fallback prompt: %s", result[:100])
        if "white background" not in result.lower():
            result += ", pure white background, black line art, labeled arrows A B C, NCERT textbook diagram"
        return result
    except Exception as exc:
        logger.warning("[ImageFinder] Fallback prompt generation failed: %s", exc)
        return (
            f"Single labeled scientific diagram of {chapter} {subject}, "
            "pure white background, black line art, arrows labeled A B C, "
            "NCERT textbook style, no color, no shading"
        )


# ─── Wikimedia Commons search (question-aware) ────────────────────────────────

_COMMONS = "https://commons.wikimedia.org/w/api.php"


def _generate_queries_from_question(
    question_text: str,
    sub_questions: list[dict],
    subject: str,
    chapter: str,
) -> list[str]:
    """Generate specific Wikimedia queries grounded in the actual question content."""
    sub_q_brief = " | ".join(sq.get("text", "")[:60] for sq in sub_questions[:2])
    system = (
        "You find labeled scientific diagram images on Wikimedia Commons for CBSE exam papers. "
        "Return ONLY a JSON array of 3 search query strings, most-to-least specific. "
        "Target: single clear experiment/biological/chemical diagrams with labeled parts. "
        "Be specific — include the process name, experiment type, or structure name. "
        "Under 7 words each. Return ONLY the JSON array."
    )
    prompt = (
        f"Chapter: {chapter}, Subject: {subject}\n"
        f"Question: {question_text[:150]}\n"
        f"Sub-questions: {sub_q_brief}\n\n"
        "Generate 3 Wikimedia Commons search queries to find a labeled diagram "
        "a student can observe to answer these questions. "
        "Be very specific — avoid generic words that match unrelated articles."
    )
    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.GEN_MODEL,
            prompt=prompt,
            system_prompt=system,
            max_tokens=120,
            temperature=0.2,
        )
        m = re.search(r'\[.*?\]', raw, re.DOTALL)
        if m:
            queries = json.loads(m.group())
            if isinstance(queries, list) and queries:
                result = [str(q) for q in queries[:3]]
                logger.info("[ImageFinder] Wikimedia queries: %s", result)
                return result
    except Exception as exc:
        logger.warning("[ImageFinder] query generation failed: %s", exc)
    fallback = f"{chapter} {subject} diagram labeled"
    logger.info("[ImageFinder] Wikimedia queries (fallback): [%r]", fallback)
    return [fallback]


def _search_wikimedia(query: str, limit: int = 8) -> list[dict]:
    resp = requests.get(
        _COMMONS,
        params={"action": "query", "list": "search", "srnamespace": "6",
                "srsearch": query, "srlimit": str(limit), "format": "json"},
        timeout=20, headers={"User-Agent": _UA},
    )
    resp.raise_for_status()
    return resp.json().get("query", {}).get("search", [])


def _get_image_info(titles: list[str]) -> dict[str, dict]:
    resp = requests.get(
        _COMMONS,
        params={"action": "query", "titles": "|".join(titles),
                "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": "800", "format": "json"},
        timeout=20, headers={"User-Agent": _UA},
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    result = {}
    for page in pages.values():
        title = page.get("title", "")
        ii    = (page.get("imageinfo") or [{}])[0]
        result[title] = {
            "title": title.replace("File:", ""),
            "full_title": title,
            "url":   ii.get("url", ""),
            "thumb": ii.get("thumburl", ii.get("url", "")),
            "mime":  ii.get("mime", ""),
            "width": ii.get("width", 0),
            "height": ii.get("height", 0),
        }
    return result


def _collect_candidates(queries: list[str], target: int = 5) -> list[dict]:
    seen, candidates = set(), []
    for query in queries:
        if len(candidates) >= target:
            break
        try:
            results = _search_wikimedia(query, limit=target * 2)
        except Exception:
            continue
        titles = [r["title"] for r in results if r["title"] not in seen][:target]
        if not titles:
            continue
        try:
            info = _get_image_info(titles)
        except Exception:
            continue
        for title, meta in info.items():
            if len(candidates) >= target:
                break
            if meta.get("url") and meta.get("mime", "").startswith("image/"):
                candidates.append(meta)
                seen.add(title)
    return candidates


def _fetch_bytes(url: str) -> bytes:
    for attempt in range(4):
        if attempt > 0:
            time.sleep(3 * attempt)
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": _UA})
            if resp.status_code == 429:
                continue
            resp.raise_for_status()
            return resp.content
        except Exception:
            if attempt == 3:
                raise
    raise RuntimeError("Could not download image")


def _evaluate_wikimedia_candidates(candidates: list[dict]) -> list[dict]:
    """Evaluate candidates with Kimi vision — mark each suitable/unsuitable."""
    system = (
        "You evaluate images for CBSE Class 10 exam papers. "
        "Mark suitable=false for: collages, multiple unrelated items, decorative/artistic images, "
        "blurry images, images with no single clear educational subject. "
        "Mark suitable=true only for a single clear diagram, experiment setup, or scientific structure. "
        "If the image has labeled parts (arrows with A, B, C), set has_labels=true. "
        "Reply ONLY as JSON: {\"suitable\": bool, \"score\": 1-10, \"has_labels\": bool, "
        "\"what_is_shown\": \"one sentence\", \"reason\": \"why\"}"
    )
    for i, c in enumerate(candidates):
        if i > 0:
            time.sleep(1.5)
        if "svg" in c.get("mime", ""):
            c["eval"] = {"suitable": False, "score": 0, "has_labels": False,
                         "what_is_shown": "", "reason": "SVG"}
            continue
        eval_url = c.get("thumb") or c.get("url")
        if not eval_url:
            c["eval"] = {"suitable": False, "score": 0, "has_labels": False,
                         "what_is_shown": "", "reason": "no URL"}
            continue
        try:
            img_bytes = _fetch_bytes(eval_url)
            prompt    = f"Image title: {c['title']}\nEvaluate this image for a CBSE Class 10 exam question paper."
            raw       = _vision_call(prompt, img_bytes, c["mime"], max_tokens=200)
            m         = re.search(r'\{.*\}', raw, re.DOTALL)
            result    = json.loads(m.group()) if m else {}
            result.setdefault("suitable", False)
            result.setdefault("score", 0)
            result.setdefault("has_labels", False)
            result.setdefault("what_is_shown", c["title"])
            result.setdefault("reason", "")
            c["eval"] = result
            logger.info("[ImageFinder] Wikimedia %s → suitable=%s score=%s",
                        c["title"][:50], result["suitable"], result["score"])
        except Exception as exc:
            logger.warning("[ImageFinder] Wikimedia eval failed %s: %s", c["title"][:40], exc)
            c["eval"] = {"suitable": False, "score": 0, "has_labels": False,
                         "what_is_shown": "", "reason": str(exc)}
    return candidates


# ─── Pollinations image generation ────────────────────────────────────────────

def _generate_pollinations(prompt: str) -> tuple[bytes, str]:
    url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
    params = {"model": POLLINATIONS_MODEL, "width": 1024, "height": 1024,
              "nologo": "true", "private": "true"}
    if POLLINATIONS_KEY:
        params["token"] = POLLINATIONS_KEY
    logger.info("[ImageFinder] Pollinations generating image...")
    resp = requests.get(url, params=params, timeout=120)
    resp.raise_for_status()
    mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    return resp.content, mime


# ─── V9.1 — Multi-image generation + Kimi ranking ─────────────────────────────

_POLLINATIONS_VARIANTS = 3  # how many images to generate before picking best


def _rank_images_with_kimi(
    question_text: str,
    sub_questions: list[dict],
    candidates: list[tuple[bytes, str]],  # (img_bytes, mime)
) -> tuple[bytes, str]:
    """
    V9.1 — Show all candidate images to Kimi and pick the best one.
    Returns (best_img_bytes, best_mime).
    Falls back to first candidate on any error.
    """
    if len(candidates) == 1:
        return candidates[0]

    sub_q_lines = "\n".join(
        f"  ({chr(97 + i)}) {sq.get('text', '')} [{sq.get('marks', 1)}m]"
        for i, sq in enumerate(sub_questions[:4])
    )

    scores = []
    for idx, (img_bytes, mime) in enumerate(candidates):
        prompt = (
            f"This is candidate image {idx + 1} for the following CBSE question:\n\n"
            f"QUESTION: {question_text}\n"
            f"SUB-QUESTIONS:\n{sub_q_lines}\n\n"
            "Score this image from 1–10 on:\n"
            "  - scientific_accuracy (is it scientifically correct?)\n"
            "  - relevance (does it clearly show what the sub-questions ask about?)\n"
            "  - label_clarity (are key parts labeled A/B/C or clearly identifiable?)\n"
            "  - exam_suitability (is it clean and appropriate for a CBSE exam paper?)\n\n"
            "Output JSON only:\n"
            '{"scientific_accuracy": 8, "relevance": 9, "label_clarity": 7, "exam_suitability": 8}'
        )
        try:
            raw = _vision_call(prompt, img_bytes, mime, max_tokens=150)
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            result = json.loads(m.group()) if m else {}
            total = (
                result.get("scientific_accuracy", 5)
                + result.get("relevance", 5)
                + result.get("label_clarity", 5)
                + result.get("exam_suitability", 5)
            )
            scores.append(total)
            logger.info(
                "[V9.1-Rank] Candidate %d: scientific=%d relevance=%d label=%d exam=%d → total=%d",
                idx + 1,
                result.get("scientific_accuracy", 5),
                result.get("relevance", 5),
                result.get("label_clarity", 5),
                result.get("exam_suitability", 5),
                total,
            )
        except Exception as exc:
            logger.warning("[V9.1-Rank] Kimi scoring failed for candidate %d: %s", idx + 1, exc)
            scores.append(0)

    best_idx = scores.index(max(scores))
    logger.info("[V9.1-Rank] Best candidate: %d (score=%d)", best_idx + 1, scores[best_idx])
    return candidates[best_idx]


def _generate_pollinations_multi(
    prompt: str,
    question_text: str,
    sub_questions: list[dict],
    n: int = _POLLINATIONS_VARIANTS,
) -> tuple[bytes, str]:
    """
    V9.1 — Generate N Pollinations images, rank with Kimi, return best.
    Falls back to single-image if generation fails.
    """
    base_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
    base_params = {
        "model": POLLINATIONS_MODEL,
        "width": 1024,
        "height": 1024,
        "nologo": "true",
        "private": "true",
    }
    if POLLINATIONS_KEY:
        base_params["token"] = POLLINATIONS_KEY

    candidates = []
    for i in range(n):
        try:
            params = dict(base_params, seed=str(42 + i * 17))
            resp = requests.get(base_url, params=params, timeout=120)
            resp.raise_for_status()
            mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            candidates.append((resp.content, mime))
            logger.info("[V9.1-Multi] Generated Pollinations candidate %d/%d", i + 1, n)
        except Exception as exc:
            logger.warning("[V9.1-Multi] Pollinations candidate %d failed: %s", i + 1, exc)

    if not candidates:
        raise RuntimeError("All Pollinations candidates failed")

    return _rank_images_with_kimi(question_text, sub_questions, candidates)


# ─── V9.2 — Scientific accuracy check ─────────────────────────────────────────

def _check_scientific_accuracy(
    question_text: str,
    image_bytes: bytes,
    mime: str,
    subject: str,
    source: str,
) -> dict:
    """
    V9.2 — Ask Kimi to check if the generated image is scientifically accurate.
    Skips for rdkit (structurally generated from SMILES — always accurate).
    Returns {"accurate": bool, "issues": [str], "score": int}.
    """
    if source == "rdkit":
        return {"accurate": True, "issues": [], "score": 10}

    prompt = (
        f"You are a CBSE {subject} expert. Examine this scientific diagram.\n\n"
        f"Context: This image illustrates a concept for the question:\n{question_text[:200]}\n\n"
        "Check for scientific accuracy:\n"
        "1. Are all labeled structures/parts correctly named?\n"
        "2. Are proportions/relationships scientifically valid?\n"
        "3. Are any labels or arrows misleading or wrong?\n"
        "4. Is the diagram consistent with NCERT Class 10 content?\n\n"
        "Output JSON only:\n"
        '{"accurate": true, "score": 8, "issues": []}\n'
        "score: 1–10 (10=perfectly accurate). issues: list any specific errors found."
    )
    try:
        raw = _vision_call(prompt, image_bytes, mime, max_tokens=300)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            result = json.loads(m.group())
            score = result.get("score", 5)
            issues = result.get("issues", [])
            accurate = result.get("accurate", score >= 6)
            logger.info(
                "[V9.2-SciAccuracy] source=%s accurate=%s score=%d issues=%s",
                source, accurate, score, issues,
            )
            return {"accurate": accurate, "score": score, "issues": issues}
    except Exception as exc:
        logger.warning("[V9.2-SciAccuracy] Kimi check failed: %s", exc)

    return {"accurate": True, "issues": [], "score": 5}


# ─── Kimi K2.5 verification + sub-question correction ─────────────────────────

def _verify_and_correct(
    question_text: str,
    sub_questions: list[dict],
    image_bytes: bytes,
    mime: str,
) -> list[dict]:
    """
    Send the question + image to Kimi K2.5.
    Kimi checks whether sub-questions match what's visible in the image.
    Returns corrected sub-questions (or originals if verification fails).
    """
    sub_q_lines = "\n".join(
        f"  ({chr(97 + i)}) {sq.get('text', '')} [{sq.get('marks', 1)}m]"
        for i, sq in enumerate(sub_questions[:4])
    )
    prompt = (
        "You are a CBSE Class 10 teacher verifying an image-based question.\n\n"
        f"QUESTION: {question_text}\n\n"
        f"SUB-QUESTIONS:\n{sub_q_lines}\n\n"
        "Look at the image carefully. For EACH sub-question ask:\n"
        "  1. Can a student answer this by observing THIS specific image?\n"
        "  2. If a sub-question references labels (A, B, C) that DON'T exist in the image → remove the label reference.\n"
        "  3. If a sub-question asks about something NOT clearly visible → rewrite it to ask about what IS visible.\n"
        "  4. Keep the marks values exactly as given.\n\n"
        "Return ONLY valid JSON:\n"
        '{"verified": true/false, '
        '"sub_questions": [{"text": "...", "marks": 1}, ...], '
        '"notes": "brief summary of corrections made"}'
    )
    logger.info("[ImageFinder] Kimi verifying question against image...")
    raw = _vision_call(prompt, image_bytes, mime, max_tokens=700)
    m   = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        logger.warning("[ImageFinder] Kimi verification returned no JSON — using originals")
        return sub_questions
    try:
        result = json.loads(m.group())
        verified_sqs = result.get("sub_questions", [])
        if not verified_sqs:
            return sub_questions
        # Preserve original marks if Kimi omitted them
        for i, vsq in enumerate(verified_sqs):
            if i < len(sub_questions) and "marks" not in vsq:
                vsq["marks"] = sub_questions[i].get("marks", 1)
        notes = result.get("notes", "")
        logger.info("[ImageFinder] Kimi verified=%s notes=%r",
                    result.get("verified"), notes[:100] if notes else "")
        return verified_sqs
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("[ImageFinder] Kimi verification parse failed: %s", exc)
        return sub_questions


# ─── Image storage ────────────────────────────────────────────────────────────

def _save_image(image_bytes: bytes, mime: str, name_hint: str) -> str:
    ext      = mime.split("/")[-1].replace("svg+xml", "svg")
    digest   = hashlib.sha256(image_bytes).hexdigest()[:16]
    safe     = re.sub(r"[^\w\-]", "_", name_hint)[:40]
    filename = f"{safe}_{digest}.{ext}"
    out_dir  = os.path.join(settings.MEDIA_ROOT, "question_images")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, filename)
    if not os.path.exists(out_path):
        with open(out_path, "wb") as f:
            f.write(image_bytes)
    return out_path


# ─── Main entry point ─────────────────────────────────────────────────────────

def generate_image_for_question(
    question_text: str,
    sub_questions: list[dict],
    subject: str,
    chapter: str,
) -> dict | None:
    """
    Generate an image matching an already-written CBQ question, verify with
    Kimi K2.5, and return corrected sub-questions.

    Flow:
      1. Router LLM → classify as "rdkit" or "diagram" + extract data
      2a. rdkit:   RDKit renders SMILES → PNG → Kimi verify → return
                   (on RDKit failure → falls back to Pollinations)
      2b. diagram: Wikimedia search → if suitable: Kimi verify → return
                   else: Pollinations with router's image_prompt → Kimi verify → return

    Returns {"image_path", "mime", "source", "verified_sub_questions"} or None.
    """
    name_hint = re.sub(r"\W+", "_", f"{chapter}_{subject}")[:40]
    logger.info("[ImageFinder] Starting question-first image flow: chapter=%r subject=%r",
                chapter, subject)

    # ── Step 0: Route ──────────────────────────────────────────────────────────
    route      = _route_and_extract(question_text, sub_questions, subject, chapter)
    image_type = route.get("image_type", "diagram")

    # ── Step 1: RDKit path (molecular structure) ───────────────────────────────
    if image_type == "rdkit":
        smiles        = route.get("smiles", "").strip()
        compound_name = route.get("compound_name", chapter)
        if smiles:
            try:
                img_bytes, mime = _render_rdkit(smiles, compound_name)
                image_path      = _save_image(img_bytes, mime, name_hint)
                logger.info("[ImageFinder] RDKit image saved: %s", image_path)
                # V9.2 — scientific accuracy (rdkit always passes, but log it)
                _check_scientific_accuracy(question_text, img_bytes, mime, subject, "rdkit")
                verified_sqs = _verify_and_correct(question_text, sub_questions, img_bytes, mime)
                return {
                    "image_path":             image_path,
                    "mime":                   mime,
                    "source":                 "rdkit",
                    "verified_sub_questions": verified_sqs,
                }
            except Exception as exc:
                logger.warning("[ImageFinder] RDKit failed (%s) — falling back to Pollinations", exc)
        else:
            logger.warning("[ImageFinder] Router returned rdkit but no SMILES — using diagram flow")
        # Fall through to Pollinations using image_prompt from router
        image_type = "diagram"

    # ── Step 2: Diagram path — Wikimedia first ─────────────────────────────────
    try:
        queries    = _generate_queries_from_question(question_text, sub_questions, subject, chapter)
        candidates = _collect_candidates(queries, target=5)

        if candidates:
            candidates = _evaluate_wikimedia_candidates(candidates)
            suitable   = [c for c in candidates
                          if c.get("eval", {}).get("suitable")
                          and c.get("eval", {}).get("score", 0) >= _SCORE_THRESHOLD]

            if suitable:
                winner    = max(suitable, key=lambda c: c["eval"]["score"])
                dl_url    = winner.get("thumb") or winner.get("url")
                img_bytes = _fetch_bytes(dl_url)
                image_path = _save_image(img_bytes, winner["mime"], name_hint)
                logger.info("[ImageFinder] Wikimedia winner: %s (score=%s)",
                            winner["title"][:50], winner["eval"]["score"])
                # V9.2 — scientific accuracy check on Wikimedia image
                sci_check = _check_scientific_accuracy(
                    question_text, img_bytes, winner["mime"], subject, "wikimedia"
                )
                if not sci_check.get("accurate") and sci_check.get("score", 10) < 5:
                    logger.warning(
                        "[V9.2] Wikimedia image low accuracy (score=%d) — falling through to Pollinations",
                        sci_check.get("score", 0),
                    )
                    raise ValueError("Wikimedia image failed scientific accuracy check")
                verified_sqs = _verify_and_correct(question_text, sub_questions,
                                                   img_bytes, winner["mime"])
                return {
                    "image_path":             image_path,
                    "mime":                   winner["mime"],
                    "source":                 "wikimedia",
                    "verified_sub_questions": verified_sqs,
                    "sci_accuracy":           sci_check,
                }
    except Exception as exc:
        logger.warning("[ImageFinder] Wikimedia path failed: %s", exc)

    # ── Step 3: Pollinations — multi-image + Kimi ranking (V9.1) ───────────────
    try:
        gen_prompt = route.get("image_prompt") or _build_prompt_from_question(
            question_text, sub_questions, subject, chapter
        )
        # V9.1: generate N candidates and let Kimi pick the best one
        img_bytes, mime = _generate_pollinations_multi(
            gen_prompt, question_text, sub_questions, n=_POLLINATIONS_VARIANTS
        )
        image_path      = _save_image(img_bytes, mime, name_hint)
        logger.info("[ImageFinder] Pollinations best image saved: %s", image_path)
        # V9.2 — scientific accuracy check on winner
        sci_check = _check_scientific_accuracy(
            question_text, img_bytes, mime, subject, "pollinations"
        )
        verified_sqs = _verify_and_correct(question_text, sub_questions, img_bytes, mime)
        return {
            "image_path":             image_path,
            "mime":                   mime,
            "source":                 "pollinations",
            "verified_sub_questions": verified_sqs,
            "sci_accuracy":           sci_check,
        }
    except Exception as exc:
        logger.error("[ImageFinder] Pollinations path failed: %s", exc)

    return None
