"""Signed, expiring URLs for protected media (question papers + uploaded materials).

The /media/ route used to serve every file publicly — anyone could download any school's
papers by URL. We now require a valid time-limited signature on protected paths. The API
only hands signed URLs to authorized users (its querysets are school-scoped), so a school
never receives another school's link, and links expire. Signed URLs work with plain browser
downloads (<a href>, window.open) since the token rides in the query string — no auth header
needed, unlike the Token-authenticated JSON API.
"""

from django.core import signing

_SALT = "qpg.media.v1"
MAX_AGE = 60 * 60 * 24  # signed links valid for 24h

# Only these media subtrees are access-controlled. Generated diagram images are not
# school-sensitive and must stay loadable in the editor iframe, so they remain open.
PROTECTED_PREFIXES = ("question_papers/", "materials/")


def _norm(path):
    return str(path or "").replace("\\", "/").lstrip("/")


def is_protected(path):
    return _norm(path).startswith(PROTECTED_PREFIXES)


def sign_media_path(path):
    return signing.TimestampSigner(salt=_SALT).sign(_norm(path))


def media_path_is_valid(path, token):
    if not token:
        return False
    try:
        original = signing.TimestampSigner(salt=_SALT).unsign(token, max_age=MAX_AGE)
    except signing.BadSignature:   # also covers SignatureExpired (a subclass)
        return False
    return original == _norm(path)


def signed_file_url(request, filefield):
    """Absolute, signed (if protected) URL for a media FileField, or None if no file."""
    if not filefield:
        return None
    rel = _norm(getattr(filefield, "name", filefield))
    if not rel:
        return None
    url = f"/media/{rel}?sig={sign_media_path(rel)}" if is_protected(rel) else f"/media/{rel}"
    return request.build_absolute_uri(url) if request is not None else url
