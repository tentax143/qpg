from django.urls import path
from . import views
from . import views_blueprint_ai
from . import views_blueprint_detail

urlpatterns = [
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("generate/", views.generate_view, name="generate"),
    path("patterns/", views.patterns_view, name="patterns"),
    path("upload/", views.upload_material, name="upload"),
    path("materials/", views.materials_list_view, name="materials_list"),
    path("materials/<int:material_id>/edit/", views.edit_material_view, name="edit_material"),
    path("materials/<int:material_id>/delete/", views.delete_material_view, name="delete_material"),
    path("materials/bulk-delete/", views.bulk_delete_materials_view, name="bulk_delete_materials"),
    path("get_subjects_for_class/", views.get_subjects_for_class, name="get_subjects_for_class"),
    path("get_chapters/", views.get_chapters, name="get_chapters"),
    path("get_blueprints/", views.get_blueprints, name="get_blueprints"),
    path("get_blueprint_details/<str:blueprint_id>/", views.get_blueprint_details, name="get_blueprint_details"),
    
    # Authentication URLs
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("clear-session/", views.clear_session_view, name="clear_session"),
    path('update_model_choice/', views.update_model_choice, name='update_model_choice'),
    path("register/", views.register_view, name="register"),
    
    # Retry functionality
    path("retry/<int:paper_id>/", views.retry_paper_view, name="retry_paper"),
    
    # Delete functionality
    path("delete/<int:paper_id>/", views.delete_paper_view, name="delete_paper"),
    path("bulk-delete-papers/", views.bulk_delete_papers_view, name="bulk_delete_papers"),
    # Admin user management (avoid Django admin namespace)
    path("users/create/", views.admin_create_user_view, name="admin_create_user"),
    # Password change prompt flow
    path("password/prompt/", views.password_change_prompt_view, name="password_change_prompt"),
    path("password/change/", views.password_change_form_view, name="password_change_form"),
    path("users/delete/<int:user_id>/", views.admin_delete_user_view, name="admin_delete_user"),

    # Edit functionality
    path("edit/<int:paper_id>/", views.edit_paper, name="edit_paper"),
    path("edit/<int:paper_id>/save/", views.save_paper_edits, name="save_paper_edits"),
    path("edit/<int:paper_id>/generate-pdf/", views.generate_paper_pdf, name="generate_paper_pdf"),
    
    # Pattern management
    path("patterns/", views.patterns_view, name="patterns"),
    path("pattern/<int:pattern_id>/", views.pattern_detail_view, name="pattern_detail"),
    path("pattern/<int:pattern_id>/edit/", views.pattern_edit_view, name="edit_pattern"),
    path("create-pattern/", views.create_pattern_view, name="create_pattern"),
    path("delete-pattern/<int:pattern_id>/", views.delete_pattern_view, name="delete_pattern"),
    path("api/pattern/<int:pattern_id>/details/", views.get_pattern_details, name="get_pattern_details"),
    
    # Blueprint management
    path("blueprints/", views.blueprint_list_view, name="blueprint_list"),
    path("blueprint-template/create/", views.blueprint_template_create_view, name="blueprint_template_create"),
    path("blueprint-template/edit/<int:template_id>/", views.blueprint_template_edit_view, name="blueprint_template_edit"),
    path("blueprint-template/delete/<int:template_id>/", views.blueprint_template_delete_view, name="blueprint_template_delete"),
    path("exam-blueprint/create/", views.exam_blueprint_create_view, name="exam_blueprint_create"),
    path("exam-blueprint/edit/<int:blueprint_id>/", views.exam_blueprint_edit_view, name="exam_blueprint_edit"),
    path("exam-blueprint/delete/<int:blueprint_id>/", views.exam_blueprint_delete_view, name="exam_blueprint_delete"),

    # AI-powered Blueprint Generation
    path("blueprint/create-from-text/", views_blueprint_ai.create_blueprint_from_text, name="create_blueprint_from_text"),
    path("api/generate-blueprint/", views_blueprint_ai.generate_blueprint_api, name="generate_blueprint_api"),
    path("blueprint/preview/", views_blueprint_ai.preview_blueprint, name="preview_blueprint"),

    # Detailed Blueprint Builder
    path("blueprint/detailed-builder/", views_blueprint_detail.detailed_blueprint_builder, name="detailed_blueprint_builder"),
    path("api/blueprint/save-detailed/", views_blueprint_detail.save_detailed_blueprint, name="save_detailed_blueprint"),
    path("api/blueprint/validate/", views_blueprint_detail.validate_blueprint_structure, name="validate_blueprint"),
    path("api/blueprint/parse-text/", views_blueprint_detail.parse_text_to_structure, name="parse_text_to_structure"),
    path("blueprint/detailed/list/", views_blueprint_detail.list_detailed_blueprints, name="list_detailed_blueprints"),
    path("blueprint/detailed/<int:blueprint_id>/load/", views_blueprint_detail.load_detailed_blueprint, name="load_detailed_blueprint"),
    path("blueprint/detailed/<int:blueprint_id>/delete/", views_blueprint_detail.delete_detailed_blueprint, name="delete_detailed_blueprint"),
]
