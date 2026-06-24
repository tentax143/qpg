import os
import re

from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.http import HttpResponse, Http404
from django.views.static import serve

from core.media_access import is_protected, media_path_is_valid


def robots_txt(request):
    robots_path = settings.BASE_DIR / "robots.txt"
    try:
        content = robots_path.read_text(encoding="utf-8")
    except OSError:
        content = "User-agent: *\nDisallow: /\n"
    return HttpResponse(content, content_type="text/plain")


def serve_media(request, path):
    """Serve media files regardless of DEBUG, with fallback for Django's FileField rename suffix.

    When FileField.save() finds a collision it appends _XXXXXXX (7 alphanumeric chars) before
    the extension. Old DB records store the renamed path but the disk file has the original name.
    This view tries the exact path first, then strips the suffix and retries.

    Protected subtrees (question papers, materials) require a valid signed token (?sig=) so
    they can't be downloaded by guessing the URL or by another school. The API hands signed,
    expiring URLs to authorized users only (see core.media_access).
    """
    if is_protected(path) and not media_path_is_valid(path, request.GET.get("sig", "")):
        raise Http404("Media file not found")

    if os.path.exists(os.path.join(settings.MEDIA_ROOT, path)):
        return serve(request, path, document_root=settings.MEDIA_ROOT)

    # Strip Django rename suffix: filename_XXXXXXX.ext → filename.ext
    stripped = re.sub(r"_[A-Za-z0-9]{7}(\.[^.]+)$", r"\1", path)
    if stripped != path and os.path.exists(os.path.join(settings.MEDIA_ROOT, stripped)):
        return serve(request, stripped, document_root=settings.MEDIA_ROOT)

    raise Http404("Media file not found")


urlpatterns = [
    path("robots.txt", robots_txt),
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    re_path(r"^media/(?P<path>.*)$", serve_media),
]
