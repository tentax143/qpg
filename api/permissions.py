from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    """Only superadmin role can access this view."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        try:
            return request.user.profile.role == 'superadmin'
        except Exception:
            return False


class IsSchoolAdminOrAbove(BasePermission):
    """school_admin or superadmin can access this view."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        try:
            return request.user.profile.role in ('superadmin', 'school_admin')
        except Exception:
            return False
