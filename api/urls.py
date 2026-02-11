from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ExamPatternViewSet,
    QuestionPaperViewSet,
    MaterialViewSet,
    BlueprintTemplateViewSet,
    ExamBlueprintViewSet,
    get_subjects_for_class,
    get_chapters,
    get_blueprints,
    get_blueprint_details,
    model_choice,
)
from .auth_views import login, register, logout, user_profile, user_management, delete_user, change_password

# Create a router and register our viewsets
router = DefaultRouter()
router.register(r'patterns', ExamPatternViewSet, basename='exampattern')
router.register(r'papers', QuestionPaperViewSet, basename='questionpaper')
router.register(r'materials', MaterialViewSet, basename='material')
router.register(r'templates', BlueprintTemplateViewSet, basename='blueprinttemplate')
router.register(r'blueprints', ExamBlueprintViewSet, basename='examblueprint')

# The API URLs are determined automatically by the router
urlpatterns = [
    path('auth/login/', login, name='api_login'),
    path('auth/register/', register, name='api_register'),
    path('auth/logout/', logout, name='api_logout'),
    path('auth/profile/', user_profile, name='api_profile'),
    path('auth/change-password/', change_password, name='api_change_password'),
    
    # Utility Endpoints
    path('get_subjects_for_class/', get_subjects_for_class, name='api_get_subjects'),
    path('get_chapters/', get_chapters, name='api_get_chapters'),
    path('get_blueprints/', get_blueprints, name='api_get_blueprints'),
    path('get_blueprint_details/<str:blueprint_id>/', get_blueprint_details, name='api_get_blueprint_details'),
    path('config/model-choice/', model_choice, name='api_model_choice'),
    path('users/', user_management, name='api_user_management'),
    path('users/<int:pk>/', delete_user, name='api_delete_user'),
    
    # Discovery utility endpoints for generator
    path('get_subjects_for_class/', get_subjects_for_class, name='api_get_subjects'),
    path('get_chapters/', get_chapters, name='api_get_chapters'),
    path('get_blueprints/', get_blueprints, name='api_get_blueprints'),
    path('get_blueprint_details/<str:blueprint_id>/', get_blueprint_details, name='api_get_blueprint_details'),
    
    path('', include(router.urls)),
]
