from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.authtoken.models import Token
from django.contrib.auth import login as django_login, logout as django_logout
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
from .auth_serializers import (
    LoginSerializer, UserSerializer,
    CreateUserSerializer, PasswordUpdateSerializer, ProfileUpdateSerializer
)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def login(request):
    """
    Login endpoint - returns authentication token
    """
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data['user']
        # Sign in the user in the session to support legacy views (CSRF/Model choice)
        django_login(request, user)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user': UserSerializer(user).data
        })
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



@api_view(['POST'])
def logout(request):
    """
    Logout endpoint - deletes user token
    """
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Not authenticated'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    # Also logout from session
    django_logout(request)
    request.user.auth_token.delete()
    return Response({'message': 'Logged out successfully'})


@api_view(['GET', 'POST'])
def user_management(request):
    """
    List and create users.
    - superadmin: sees all users
    - school_admin: sees only users in their school
    """
    try:
        role = request.user.profile.role
    except Exception:
        role = None

    is_superadmin = role == 'superadmin'
    is_school_admin = role == 'school_admin'

    if not (is_superadmin or is_school_admin or request.user.is_superuser):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        if is_superadmin or request.user.is_superuser:
            users = User.objects.all().select_related('profile__school').order_by('-date_joined')
        elif is_school_admin:
            try:
                school = request.user.profile.school
                users = User.objects.filter(profile__school=school).select_related('profile__school').order_by('-date_joined') if school else User.objects.none()
            except Exception:
                users = User.objects.none()
        else:
            users = User.objects.none()
        return Response(UserSerializer(users, many=True).data)

    elif request.method == 'POST':
        # Teacher limit check for school admins
        if is_school_admin:
            try:
                school = request.user.profile.school
                plan = school.effective_plan() if school else None
                if plan and not plan.is_unlimited_teachers:
                    current_count = User.objects.filter(profile__school=school).count()
                    if current_count >= plan.teacher_limit:
                        return Response(
                            {'error': f'Teacher limit reached ({current_count}/{plan.teacher_limit} on the {plan.display_name} plan). '
                                      'Upgrade your plan to add more teachers.'},
                            status=status.HTTP_402_PAYMENT_REQUIRED,
                        )
            except Exception:
                pass

        serializer = CreateUserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            # Assign school and role for school admins creating users
            if is_school_admin:
                try:
                    profile = user.profile
                    profile.school = request.user.profile.school
                    profile.role = 'teacher'  # school admins can only create teachers
                    profile.require_password_change = True
                    allowed_subject = request.data.get('allowed_subject', '') or None
                    profile.allowed_subject = allowed_subject
                    profile.save()
                except Exception:
                    pass
            return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
def delete_user(request, pk):
    """
    Delete a user.
    - superadmin: can delete anyone except themselves
    - school_admin: can only delete users in their school
    """
    try:
        role = request.user.profile.role
    except Exception:
        role = None

    if not (role in ('superadmin', 'school_admin') or request.user.is_superuser):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    user_to_delete = get_object_or_404(User, pk=pk)

    if user_to_delete.id == request.user.id:
        return Response({'error': 'Cannot delete yourself'}, status=status.HTTP_400_BAD_REQUEST)

    # School admin: enforce school boundary
    if role == 'school_admin':
        try:
            school = request.user.profile.school
            if not school or user_to_delete.profile.school_id != school.id:
                return Response({'error': 'Cannot delete users outside your school'}, status=status.HTTP_403_FORBIDDEN)
        except Exception:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

    user_to_delete.delete()
    return Response({'message': 'User deleted successfully'})


@api_view(['GET', 'PATCH'])
def user_profile(request):
    """
    Get or update current user profile
    """
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Not authenticated'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    if request.method == 'GET':
        return Response(UserSerializer(request.user).data)
    
    elif request.method == 'PATCH':
        serializer = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(UserSerializer(request.user).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def change_password(request):
    """
    Change password for current user
    """
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=status.HTTP_401_UNAUTHORIZED)

    serializer = PasswordUpdateSerializer(data=request.data)
    if serializer.is_valid():
        if not request.user.check_password(serializer.validated_data['old_password']):
            return Response({'error': 'Incorrect old password'}, status=status.HTTP_400_BAD_REQUEST)

        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save()
        _clear_password_change_flag(request.user)
        return Response({'message': 'Password updated successfully'})

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def _clear_password_change_flag(user):
    try:
        profile = user.profile
        if profile.require_password_change:
            profile.require_password_change = False
            profile.save(update_fields=['require_password_change'])
    except Exception:
        pass


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def register_school(request):
    """Public endpoint: create a new school + school_admin user on a 14-day Pro trial.

    Body: { school_name, admin_name, email, password }
    Returns the same token/user shape as login so the frontend can log in immediately.
    """
    from core.models import School, Plan

    school_name = (request.data.get('school_name') or '').strip()
    admin_name  = (request.data.get('admin_name') or '').strip()
    email       = (request.data.get('email') or '').strip().lower()
    password    = request.data.get('password', '')

    # Basic validation
    errors = {}
    if not school_name:
        errors['school_name'] = 'School name is required.'
    if not admin_name:
        errors['admin_name'] = 'Your name is required.'
    if not email:
        errors['email'] = 'Email is required.'
    elif User.objects.filter(email__iexact=email).exists():
        errors['email'] = 'An account with this email already exists.'
    if len(password) < 8:
        errors['password'] = 'Password must be at least 8 characters.'
    if errors:
        return Response(errors, status=status.HTTP_400_BAD_REQUEST)

    # Build username from email prefix, ensuring uniqueness
    base_username = email.split('@')[0][:30]
    username = base_username
    suffix = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{suffix}"
        suffix += 1

    # Create Django user
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=admin_name.split()[0][:30],
        last_name=' '.join(admin_name.split()[1:])[:150] if len(admin_name.split()) > 1 else '',
    )

    # 14-day Pro trial
    try:
        pro_plan = Plan.objects.get(name=Plan.PLAN_PRO)
    except Plan.DoesNotExist:
        pro_plan = None

    now = timezone.now()
    school = School.objects.create(
        name=school_name,
        email=email,
        plan=pro_plan,
        trial_started_at=now,
        plan_expires_at=now + timedelta(days=14),
        is_active=True,
    )

    # Assign school_admin role; no password-change prompt (they just set it)
    profile = user.profile
    profile.school = school
    profile.role = 'school_admin'
    profile.require_password_change = False
    profile.save()

    token, _ = Token.objects.get_or_create(user=user)
    return Response({
        'token': token.key,
        'user': UserSerializer(user).data,
        'trial_ends_at': school.plan_expires_at,
        'plan': pro_plan.display_name if pro_plan else 'Pro',
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def google_login(request):
    """Verify a Google OAuth access token and return a DRF auth token.

    Body: { access_token: "<Google OAuth access token>" }
    Matches the Google account email to an existing Django user.
    """
    import os
    import requests as http_requests

    access_token = (request.data.get('access_token') or '').strip()
    if not access_token:
        return Response({'error': 'access_token is required'}, status=status.HTTP_400_BAD_REQUEST)

    resp = http_requests.get(
        'https://www.googleapis.com/oauth2/v3/userinfo',
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=10,
    )
    if resp.status_code != 200:
        return Response({'error': 'Invalid Google token'}, status=status.HTTP_400_BAD_REQUEST)

    google_data = resp.json()
    email = google_data.get('email', '').lower()

    if not email or not google_data.get('email_verified'):
        return Response({'error': 'Google account email is not verified'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        return Response(
            {'error': 'No Shiken account found with this Google email. Please register first.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if not user.is_active:
        return Response({'error': 'This account is inactive'}, status=status.HTTP_403_FORBIDDEN)

    django_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    token, _ = Token.objects.get_or_create(user=user)
    return Response({'token': token.key, 'user': UserSerializer(user).data})


@api_view(['POST'])
def first_login_password(request):
    """First-login prompt: set a new password, OR skip. Both clear the require-password-change
    flag so the user isn't asked again. No old password needed (the user just authenticated);
    setting a new one this way is only allowed while the flag is set (first-login window)."""
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=status.HTTP_401_UNAUTHORIZED)

    if request.data.get('skip'):
        _clear_password_change_flag(request.user)
        return Response({'message': 'Skipped — you can change your password later in settings.'})

    try:
        must_change = bool(request.user.profile.require_password_change)
    except Exception:
        must_change = False
    if not must_change:
        return Response({'error': 'Use the regular change-password form (current password required).'},
                        status=status.HTTP_400_BAD_REQUEST)

    new_password = str(request.data.get('new_password', ''))
    if len(new_password) < 8:
        return Response({'error': 'Password must be at least 8 characters.'},
                        status=status.HTTP_400_BAD_REQUEST)

    request.user.set_password(new_password)   # token auth → token stays valid, user stays logged in
    request.user.save()
    _clear_password_change_flag(request.user)
    return Response({'message': 'Password updated successfully'})
