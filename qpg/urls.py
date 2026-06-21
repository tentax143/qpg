from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse


def robots_txt(request):
    robots_path = settings.BASE_DIR / "robots.txt"
    try:
        content = robots_path.read_text(encoding="utf-8")
    except OSError:
        content = "User-agent: *\nDisallow: /\n"
    return HttpResponse(content, content_type="text/plain")


urlpatterns = [
    path("robots.txt", robots_txt),
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
