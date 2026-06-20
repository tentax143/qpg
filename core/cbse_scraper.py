"""
CBSE SQP web scraper.

Fetches the actual Sample Question Paper (SQP) PDF from cbseacademic.nic.in
for a given subject/class and extracts its text so the LLM has real source
content instead of relying on training-data memory alone.

Strategy:
  1. Fetch the known CBSE SQP index page for the class (9-12).
  2. Find the SQP PDF whose filename best matches the subject.
     (The anchor text is always just "SQP" — match by filename in href.)
  3. Download the PDF and extract text from the first 6 pages (pdfplumber).
  4. Fallback: DuckDuckGo Lite search for cbseacademic.nic.in PDFs.
  5. Return up to 4000 chars or '' on complete failure.
"""

import io
import re
import logging

import requests
import pdfplumber
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
}

_CBSE_BASE = 'https://cbseacademic.nic.in'

# Known SQP index pages
_SQP_INDEX = {
    '12': f'{_CBSE_BASE}/SQP_CLASSXII_2025-26.html',
    '11': f'{_CBSE_BASE}/SQP_CLASSXI_2025-26.html',
    '10': f'{_CBSE_BASE}/SQP_CLASSX_2025-26.html',
    '9':  f'{_CBSE_BASE}/SQP_CLASSIX_2025-26.html',
}

# PDF directory names (differ from index URL case/separator style)
_PDF_FOLDER = {
    '12': 'ClassXII_2025_26',
    '11': 'ClassXI_2025_26',
    '10': 'ClassX_2025_26',
    '9':  'ClassIX_2025_26',
}

# Subject name → likely filename stem on CBSE website
# Each value is a list of filename stems to try in order (most likely first).
# Derived from the actual filenames on cbseacademic.nic.in SQP pages.
_SUBJECT_ALIASES: dict[str, list[str]] = {
    # Core sciences
    'physics':                        ['Physics'],
    'chemistry':                      ['Chemistry'],
    'biology':                        ['Biology'],
    'biotechnology':                  ['Biotechnology'],
    # Mathematics — class 12 uses "Maths"; class 10 uses "MathsStandard"/"MathsBasic"
    'mathematics':                    ['Maths', 'Mathematics'],
    'mathematics standard':           ['MathsStandard', 'Maths_Standard'],
    'mathematics basic':              ['MathsBasic', 'Maths_Basic'],
    'applied mathematics':            ['AppliedMathematics', 'Applied_Maths'],
    # Commerce
    'accountancy':                    ['Accountancy'],
    'economics':                      ['Economics'],
    'business studies':               ['BusinessStudies'],
    # Humanities / Social
    'history':                        ['History'],
    'geography':                      ['Geography'],
    'political science':              ['PolSci', 'PoliticalScience'],
    'sociology':                      ['Sociology'],
    'psychology':                     ['Psychology'],
    'social science':                 ['SocialScience', 'Social_Science'],
    # IT / Computers — class 10 uses "ComputerApplication"
    'computer science':               ['ComputerScience', 'ComputerApplication'],
    'informatics practices':          ['InformaticsPractices'],
    'computer application':           ['ComputerApplication'],
    # PE / Home Science
    'physical education':             ['PhysicalEducation'],
    'home science':                   ['HomeScience'],
    # Languages — class 10 English uses "EnglishL" not "English"/"EnglishCore"
    'english core':                   ['EnglishCore', 'English'],
    'english elective':               ['EnglishElective'],
    'english language & literature':  ['EnglishL', 'EnglishCore', 'English'],
    'english language and literature': ['EnglishL', 'EnglishCore', 'English'],
    'english communicative':          ['EnglishComm', 'English'],
    'hindi core':                     ['HindiCore', 'Hindi'],
    'hindi elective':                 ['HindiElective'],
    'hindi course a':                 ['HindiCourseA', 'Hindi_A', 'HindiCore'],
    'hindi course b':                 ['HindiCourseB', 'Hindi_B', 'HindiElective'],
    'sanskrit':                       ['SanskritCore', 'Sanskrit'],
    # Arts / Music
    'legal studies':                  ['LegalStudies'],
    'entrepreneurship':               ['Entrepreneurship'],
    'fine arts':                      ['FineArts', 'Painting'],
    'painting':                       ['Painting'],
    'dance':                          ['Dance', 'Bharatnatyam'],
    'music hindustani':               ['HindustaniMelodic', 'MusicHindustani'],
    'music carnatic':                 ['CarnaticMusicVocal', 'MusicCarnatic'],
}


def _slug(text: str) -> str:
    """Normalise to lowercase, no spaces/punctuation — for fuzzy matching."""
    return re.sub(r'[^a-z0-9]', '', text.lower())


def _subject_score(href: str, subject: str) -> int:
    """
    Score how well a PDF href's filename matches the subject.
    Higher = better match.
    """
    # Get just the filename stem: "Biology-SQP.pdf" -> "biology"
    fname = href.rsplit('/', 1)[-1].lower()
    fname = fname.replace('-sqp', '').replace('_sqp', '').replace('.pdf', '')
    fname = re.sub(r'[^a-z0-9]', '', fname)

    subject_slug = _slug(subject)

    # Exact
    if fname == subject_slug:
        return 100

    # Subject fully contained in filename or vice-versa
    if subject_slug in fname or fname in subject_slug:
        return 80

    # Word-level overlap
    words = re.split(r'[^a-z]+', subject.lower())
    score = sum(10 for w in words if w and w in fname)
    return score


def _abs_url(href: str) -> str:
    if href.startswith('http'):
        return href
    if href.startswith('//'):
        return 'https:' + href
    if href.startswith('/'):
        return _CBSE_BASE + href
    return _CBSE_BASE + '/' + href


def _pdf_text(content: bytes, max_pages: int = 6) -> str:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = pdf.pages[:max_pages]
            return '\n'.join(p.extract_text() or '' for p in pages).strip()
    except Exception as e:
        log.warning('[cbse_scraper] pdfplumber error: %s', e)
        return ''


def _find_sqp_pdf_on_index(page_url: str, subject: str) -> str | None:
    """
    Fetch a CBSE SQP index page and return the SQP PDF URL whose filename
    best matches `subject`. Only English-language SQPs (not _hi.pdf).
    """
    try:
        resp = requests.get(page_url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        log.warning('[cbse_scraper] Index fetch failed %s: %s', page_url, e)
        return None

    # Strategy A: use alias list → try HEAD request for each stem
    class_name_for_folder = None
    for cls, idx_url in _SQP_INDEX.items():
        if idx_url == page_url:
            class_name_for_folder = cls
            break
    folder = _PDF_FOLDER.get(class_name_for_folder, '')

    stems = _SUBJECT_ALIASES.get(subject.lower(), [])
    for stem in stems:
        direct = f"{_CBSE_BASE}/web_material/SQP/{folder}/{stem}-SQP.pdf"
        try:
            chk = requests.head(direct, headers=_HEADERS, timeout=10)
            if chk.status_code == 200:
                log.info('[cbse_scraper] Direct URL hit: %s', direct)
                return direct
        except Exception:
            pass

    # Strategy B: fuzzy-match against all PDF hrefs on the page
    soup = BeautifulSoup(resp.text, 'lxml')
    best_score = 0
    best_url = None

    for a in soup.find_all('a', href=True):
        href = a['href']
        if '_hi.pdf' in href.lower() or '-ms' in href.lower():
            continue
        if not href.lower().endswith('.pdf'):
            continue
        score = _subject_score(href, subject)
        if score > best_score:
            best_score = score
            best_url = _abs_url(href)

    if best_url and best_score >= 10:
        log.info('[cbse_scraper] Fuzzy match (score=%d) for "%s": %s', best_score, subject, best_url)
        return best_url

    log.info('[cbse_scraper] No PDF found for "%s" on %s', subject, page_url)
    return None


def _duckduckgo_pdf(class_name: str, subject: str) -> str | None:
    """DuckDuckGo Lite fallback — search cbseacademic.nic.in for a matching PDF."""
    query = f'site:cbseacademic.nic.in {subject} class {class_name} sample question paper 2025-26'
    url = f'https://lite.duckduckgo.com/lite/?q={requests.utils.quote(query)}'
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'cbseacademic' in href and href.lower().endswith('.pdf') and 'sqp' in href.lower():
                return href
    except Exception as e:
        log.warning('[cbse_scraper] DDG search failed: %s', e)
    return None


def fetch_sqp_text(class_name: str, subject: str, max_chars: int = 4000) -> str:
    """
    Public entry point. Returns up to `max_chars` of text from the CBSE SQP
    PDF for (class_name, subject), or '' on complete failure.
    """
    pdf_url = None

    # Strategy 1: known index page for classes 9-12
    if class_name in _SQP_INDEX:
        pdf_url = _find_sqp_pdf_on_index(_SQP_INDEX[class_name], subject)

    # Strategy 2: DuckDuckGo fallback (for 6-8 or if index failed)
    if not pdf_url:
        log.info('[cbse_scraper] DDG fallback for %s class %s', subject, class_name)
        pdf_url = _duckduckgo_pdf(class_name, subject)

    if not pdf_url:
        log.info('[cbse_scraper] No SQP PDF found for %s class %s', subject, class_name)
        return ''

    try:
        log.info('[cbse_scraper] Downloading: %s', pdf_url)
        pdf_resp = requests.get(pdf_url, headers=_HEADERS, timeout=30)
        pdf_resp.raise_for_status()
    except Exception as e:
        log.warning('[cbse_scraper] PDF download failed %s: %s', pdf_url, e)
        return ''

    text = _pdf_text(pdf_resp.content)
    if text:
        log.info('[cbse_scraper] Extracted %d chars', len(text))
    return text[:max_chars]
