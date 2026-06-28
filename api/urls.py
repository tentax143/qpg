from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ExamPatternViewSet,
    QuestionPaperViewSet,
    MaterialViewSet,
    BlueprintTemplateViewSet,
    ExamBlueprintViewSet,
    get_subjects_for_class,
    subjects_list,
    cbse_exam_types,
    cbse_subject_pattern,
    get_chapters,
    get_blueprints,
    get_blueprint_details,
    model_choice,
)
from .auth_views import login, logout, user_profile, user_management, delete_user, change_password, first_login_password, register_school, google_login
from .admin_views import (
    superadmin_dashboard,
    schools_list,
    school_detail,
    school_users,
    school_user_remove,
    school_usage,
    school_papers,
    school_user_usage,
    school_resync_vectorstore,
    my_school,
    update_cbse_patterns,
    cbse_update_status,
    cbse_patterns_list,
)

# Create a router and register our viewsets
router = DefaultRouter()
router.register(r'patterns', ExamPatternViewSet, basename='exampattern')
router.register(r'papers', QuestionPaperViewSet, basename='questionpaper')
router.register(r'materials', MaterialViewSet, basename='material')
router.register(r'templates', BlueprintTemplateViewSet, basename='blueprinttemplate')
router.register(r'blueprints', ExamBlueprintViewSet, basename='examblueprint')

urlpatterns = [
    path('auth/login/', login, name='api_login'),
    path('auth/google/', google_login, name='api_google_login'),
    path('auth/logout/', logout, name='api_logout'),
    path('auth/register/', register_school, name='api_register_school'),
    path('auth/profile/', user_profile, name='api_profile'),
    path('auth/change-password/', change_password, name='api_change_password'),
    path('auth/first-login-password/', first_login_password, name='api_first_login_password'),

    # User management
    path('users/', user_management, name='api_user_management'),
    path('users/<int:pk>/', delete_user, name='api_delete_user'),

    # Utility endpoints
    path('subjects/', subjects_list, name='api_subjects'),
    path('cbse/exam-types/', cbse_exam_types, name='api_cbse_exam_types'),
    path('cbse/pattern/', cbse_subject_pattern, name='api_cbse_subject_pattern'),
    path('get_subjects_for_class/', get_subjects_for_class, name='api_get_subjects'),
    path('get_chapters/', get_chapters, name='api_get_chapters'),
    path('get_blueprints/', get_blueprints, name='api_get_blueprints'),
    path('get_blueprint_details/<str:blueprint_id>/', get_blueprint_details, name='api_get_blueprint_details'),
    path('config/model-choice/', model_choice, name='api_model_choice'),

    # SuperAdmin — school management
    path('admin/dashboard/', superadmin_dashboard, name='api_superadmin_dashboard'),
    path('admin/schools/', schools_list, name='api_schools_list'),
    path('admin/schools/<int:pk>/', school_detail, name='api_school_detail'),
    path('admin/schools/<int:pk>/users/', school_users, name='api_school_users'),
    path('admin/schools/<int:pk>/users/<int:user_id>/', school_user_remove, name='api_school_user_remove'),
    path('admin/schools/<int:pk>/usage/', school_usage, name='api_school_usage'),
    path('admin/schools/<int:pk>/papers/', school_papers, name='api_school_papers'),
    path('admin/schools/<int:pk>/user-usage/', school_user_usage, name='api_school_user_usage'),
    path('admin/schools/<int:pk>/resync-vectorstore/', school_resync_vectorstore, name='api_school_resync_vectorstore'),
    path('admin/my-school/', my_school, name='api_my_school'),
    path('admin/cbse-patterns/', cbse_patterns_list, name='api_cbse_patterns_list'),
    path('admin/cbse-patterns/update/', update_cbse_patterns, name='api_update_cbse_patterns'),
    path('admin/cbse-patterns/status/<str:task_id>/', cbse_update_status, name='api_cbse_update_status'),

    path('', include(router.urls)),
]
