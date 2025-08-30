from django.contrib import admin
from django.urls import path
from app import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.dashboard_view, name="dashboard"),
    path("generate/", views.generate_view, name="generate"),
]
