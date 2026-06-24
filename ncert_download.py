#!/usr/bin/env python3
"""
NCERT textbook bulk downloader (Classes 1-12, all subjects, all available books).

How it works
------------
The catalogue on https://ncert.nic.in/textbook.php is not a static list — the
class/subject/book dropdowns are populated by an inline JavaScript function
``change1()`` whose entries look like:

    if((document.test.tclass.value==12) && (...text=="Chemistry")) {
        document.test.tbook.options[1].text="Chemistry Part-I";
        document.test.tbook.options[1].value="textbook.php?lech1=0-5"
        ...

From each entry we recover four things:
    * class number   (from `tclass.value==N`)
    * subject name   (from the `...text=="..."` in the condition)
    * book title     (from `tbook.options[i].text="..."`)
    * **book code**   (from `textbook.php?CODE=START-END`)  e.g. "lech1"

NCERT serves the *complete* book as a single zip at a deterministic URL:

    https://ncert.nic.in/textbook/pdf/<CODE>dd.zip      e.g. lech1dd.zip

(Books with multiple parts — Part I / Part II — have separate codes such as
`lech1`, `lech2`, so each part is downloaded as its own zip.)

This script harvests every active code from the live page, then downloads each
``<code>dd.zip`` into a tidy folder tree:

    <out>/Class_12/Chemistry/lech1 - Chemistry Part-I.zip

Usage
-----
    # 1) Safe first step — just print/save the catalogue, download nothing:
    python ncert_download.py --list-only

    # 2) Download everything (resumable — re-running skips files already on disk):
    python ncert_download.py --out ncert_books

    # 3) Narrow it down:
    python ncert_download.py --classes 11 12 --subjects Physics Chemistry Biology

    # 4) Unzip each book after download, and/or fall back to per-chapter PDFs
    #    when a book has no complete-book zip:
    python ncert_download.py --unzip --chapters

Only the Python standard library + ``requests`` is required:
    pip install requests
"""

import argparse
import csv
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

CATALOG_URL = "https://ncert.nic.in/textbook.php"
PDF_BASE = "https://ncert.nic.in/textbook/pdf"          # /<code>dd.zip , /<code><nn>.pdf
USER_AGENT = "Mozilla/5.0 (compatible; ncert-bulk-downloader/1.0)"

# class number -> folder-friendly label. NCERT's dropdown uses 13 for the
# "Class XI & XII Combined" books and 14 for the "Vocational" category.
CLASS_LABEL = {13: "Class_11-12_Combined", 14: "Vocational"}
# Fallback: the first letter of a code also encodes the class (a=1 … l=12),
# used only when the JS condition didn't yield a class number.
_CODE_CLASS_LETTER = {chr(ord("a") + i): i + 1 for i in range(12)}


# ──────────────────────────────────────────────────────────────────────────
# Catalogue parsing
# ──────────────────────────────────────────────────────────────────────────
_RE_CONDITION = re.compile(r'tclass\.value\s*==\s*(\d+).*?\.text\s*==\s*"([^"]+)"')
_RE_TEXT = re.compile(r'tbook\.options\[(\d+)\]\.text\s*=\s*"([^"]*)"')
_RE_VALUE = re.compile(r'tbook\.options\[(\d+)\]\.value\s*=\s*"textbook\.php\?([A-Za-z0-9]+)=(\d+)-(\d+)"')


def parse_catalog(html):
    """Parse the textbook.php HTML into a list of book dicts.

    Each dict: {code, class_num, subject, title, ch_start, ch_end}.
    Skips commented-out (// or /* */) dropdown entries.
    """
    books = []
    seen = set()
    cur_class, cur_subject = None, None
    titles = {}            # option-index -> last seen title within current block
    in_block_comment = False

    for raw in html.splitlines():
        line = raw.strip()

        # Handle /* ... */ block comments spanning lines.
        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
                line = line.split("*/", 1)[1].strip()
            else:
                continue
        if "/*" in line and "*/" not in line:
            in_block_comment = True
            line = line.split("/*", 1)[0].strip()

        # Skip single-line JS comments outright.
        if line.startswith("//"):
            continue

        cond = _RE_CONDITION.search(line)
        if cond:
            cur_class = int(cond.group(1))
            cur_subject = cond.group(2).strip()
            titles = {}
            # A condition line may also carry a text/value; fall through to parse it.

        for idx, title in _RE_TEXT.findall(line):
            titles[int(idx)] = title.strip()

        m = _RE_VALUE.search(line)
        if m:
            idx, code, start, end = int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4))
            if code in seen:
                continue
            seen.add(code)
            cls = cur_class
            if cls is None:
                cls = _CODE_CLASS_LETTER.get(code[0].lower())
            books.append({
                "code": code,
                "class_num": cls,
                "subject": cur_subject or "Unknown",
                "title": titles.get(idx, code),
                "ch_start": start,
                "ch_end": end,
            })
    return books


def fetch_catalog(session):
    resp = session.get(CATALOG_URL, timeout=60)
    resp.raise_for_status()
    return parse_catalog(resp.text)


# ──────────────────────────────────────────────────────────────────────────
# Filesystem helpers
# ──────────────────────────────────────────────────────────────────────────
def _sanitize(name, maxlen=80):
    name = re.sub(r'[<>:"/\\|?*]+', " ", name)        # illegal on Windows
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:maxlen] if name else "untitled"


def class_folder(class_num):
    if class_num in CLASS_LABEL:
        return CLASS_LABEL[class_num]
    return f"Class_{class_num:02d}" if class_num else "Class_Unknown"


def book_dir(out_dir, book):
    d = os.path.join(out_dir, class_folder(book["class_num"]), _sanitize(book["subject"]))
    os.makedirs(d, exist_ok=True)
    return d


# ──────────────────────────────────────────────────────────────────────────
# Downloading
# ──────────────────────────────────────────────────────────────────────────
def _download_file(session, url, dest, retries, timeout=120):
    """Stream a URL to dest. Returns (ok, note). Skips if already present."""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return True, "exists"

    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            with session.get(url, stream=True, timeout=timeout) as r:
                if r.status_code == 404:
                    return False, "404"
                r.raise_for_status()
                tmp = dest + ".part"
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
                if os.path.getsize(tmp) == 0:
                    os.remove(tmp)
                    last_err = "empty"
                else:
                    os.replace(tmp, dest)
                    return True, "downloaded"
        except Exception as e:                                  # noqa: BLE001
            last_err = str(e)
        time.sleep(min(2 ** attempt, 15))                       # backoff
    return False, last_err or "failed"


def _maybe_unzip(zip_path):
    try:
        target = os.path.splitext(zip_path)[0]
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(target)
        return True
    except Exception as e:                                      # noqa: BLE001
        print(f"      ! unzip failed for {os.path.basename(zip_path)}: {e}")
        return False


# Best-effort per-chapter fallback. NCERT chapter PDFs are <code><suffix>.pdf;
# the suffix convention varies (prelims = ps, chapters = 01..NN, answers = an),
# so this tries the common suffixes within the declared chapter range.
def _download_chapters(session, book, dest_dir, retries, delay):
    code, ok_any = book["code"], False
    suffixes = ["ps"] + [f"{n:02d}" for n in range(book["ch_start"], book["ch_end"] + 1)] + ["an"]
    chap_dir = os.path.join(dest_dir, _sanitize(f"{code} - {book['title']}"))
    os.makedirs(chap_dir, exist_ok=True)
    for suf in suffixes:
        url = f"{PDF_BASE}/{code}{suf}.pdf"
        dest = os.path.join(chap_dir, f"{code}{suf}.pdf")
        ok, _ = _download_file(session, url, dest, retries)
        ok_any = ok_any or ok
        time.sleep(delay)
    return ok_any


def process_book(session, book, out_dir, args):
    dest_dir = book_dir(out_dir, book)
    fname = _sanitize(f"{book['code']} - {book['title']}") + ".zip"
    dest = os.path.join(dest_dir, fname)
    url = f"{PDF_BASE}/{book['code']}dd.zip"

    ok, note = _download_file(session, url, dest, args.retries)
    status = note
    if ok:
        if args.unzip and note == "downloaded":
            _maybe_unzip(dest)
    elif note == "404" and args.chapters:
        # No complete-book zip — fall back to individual chapter PDFs.
        if _download_chapters(session, book, dest_dir, args.retries, args.delay):
            status = "chapters"
        else:
            status = "no-zip,no-chapters"
    return {**book, "url": url, "dest": dest, "status": status, "ok": ok or status == "chapters"}


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Bulk-download NCERT textbooks (Class 1-12).")
    ap.add_argument("--out", default="ncert_books", help="Output directory (default: ncert_books).")
    ap.add_argument("--classes", nargs="+", type=int, help="Only these class numbers (e.g. 11 12).")
    ap.add_argument("--subjects", nargs="+", help="Only these subjects (case-insensitive substring match).")
    ap.add_argument("--list-only", action="store_true", help="Print/save the catalogue and exit (no downloads).")
    ap.add_argument("--unzip", action="store_true", help="Extract each zip after download.")
    ap.add_argument("--chapters", action="store_true", help="Fallback to per-chapter PDFs if a book has no zip.")
    ap.add_argument("--workers", type=int, default=4, help="Concurrent downloads (default: 4 — be polite).")
    ap.add_argument("--retries", type=int, default=3, help="Retries per file (default: 3).")
    ap.add_argument("--delay", type=float, default=0.5, help="Delay between requests in seconds (default: 0.5).")
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    print(f"Fetching catalogue from {CATALOG_URL} …")
    try:
        books = fetch_catalog(session)
    except Exception as e:                                      # noqa: BLE001
        print(f"ERROR: could not fetch/parse catalogue: {e}")
        sys.exit(1)
    print(f"Found {len(books)} books across all classes.\n")

    # Apply filters.
    if args.classes:
        books = [b for b in books if b["class_num"] in set(args.classes)]
    if args.subjects:
        wanted = [s.lower() for s in args.subjects]
        books = [b for b in books if any(w in b["subject"].lower() for w in wanted)]
    books.sort(key=lambda b: (b["class_num"] or 99, b["subject"], b["code"]))

    os.makedirs(args.out, exist_ok=True)
    manifest_path = os.path.join(args.out, "catalog.csv")
    with open(manifest_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["class", "subject", "title", "code", "chapters", "zip_url"])
        for b in books:
            w.writerow([b["class_num"], b["subject"], b["title"], b["code"],
                        f"{b['ch_start']}-{b['ch_end']}", f"{PDF_BASE}/{b['code']}dd.zip"])
    print(f"Catalogue written to {manifest_path}  ({len(books)} books after filters)\n")

    if args.list_only:
        for b in books:
            print(f"  Class {b['class_num']:>2}  {b['subject'][:22]:22}  {b['code']:10}  {b['title']}")
        print("\n--list-only: nothing downloaded.")
        return

    # Download.
    results, done = [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_book, session, b, args.out, args): b for b in books}
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            done += 1
            flag = "ok " if res["ok"] else "FAIL"
            print(f"  [{done}/{len(books)}] {flag} {res['code']:10} "
                  f"C{res['class_num']} {res['subject'][:18]:18} {res['status']}")

    ok = sum(1 for r in results if r["ok"])
    print("\n" + "-" * 60)
    print(f"Done. {ok}/{len(results)} books downloaded into '{args.out}'.")
    fails = [r for r in results if not r["ok"]]
    if fails:
        print(f"{len(fails)} failed:")
        for r in fails:
            print(f"   {r['code']:10} C{r['class_num']} {r['subject']}  -> {r['status']}")


if __name__ == "__main__":
    main()
