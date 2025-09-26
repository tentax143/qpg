from django.urls import path
from . import views

urlpatterns = [
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("generate/", views.generate_view, name="generate"),
    path("patterns/", views.patterns_view, name="patterns"),
    path("upload/", views.upload_material, name="upload"),
    path("get_chapters/", views.get_chapters, name="get_chapters"),
    path("get_blueprints/", views.get_blueprints, name="get_blueprints"),
    path("get_blueprint_details/<str:blueprint_id>/", views.get_blueprint_details, name="get_blueprint_details"),
    
    # Authentication URLs
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("clear-session/", views.clear_session_view, name="clear_session"),
    path("register/", views.register_view, name="register"),
    
    # Retry functionality
    path("retry/<int:paper_id>/", views.retry_paper_view, name="retry_paper"),
    
    # Delete functionality
    path("delete/<int:paper_id>/", views.delete_paper_view, name="delete_paper"),
    
    # Pattern management
    path("create-pattern/", views.create_pattern_view, name="create_pattern"),
    path("delete-pattern/<int:pattern_id>/", views.delete_pattern_view, name="delete_pattern"),
    
    # Blueprint management
    path("blueprints/", views.blueprint_list_view, name="blueprint_list"),
    path("blueprint-template/create/", views.blueprint_template_create_view, name="blueprint_template_create"),
    path("blueprint-template/edit/<int:template_id>/", views.blueprint_template_edit_view, name="blueprint_template_edit"),
    path("blueprint-template/delete/<int:template_id>/", views.blueprint_template_delete_view, name="blueprint_template_delete"),
    path("exam-blueprint/create/", views.exam_blueprint_create_view, name="exam_blueprint_create"),
    path("exam-blueprint/edit/<int:blueprint_id>/", views.exam_blueprint_edit_view, name="exam_blueprint_edit"),
    path("exam-blueprint/delete/<int:blueprint_id>/", views.exam_blueprint_delete_view, name="exam_blueprint_delete"),
]
