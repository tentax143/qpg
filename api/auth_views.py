from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.authtoken.models import Token
from django.contrib.auth import login as django_login, logout as django_logout
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
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

    if not (is_superadmin or is_school_admin or request.user.is_staff or request.user.is_superuser):
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
            users = User.objects.all().select_related('profile__school').order_by('-date_joined')
        return Response(UserSerializer(users, many=True).data)

    elif request.method == 'POST':
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

    if not (role in ('superadmin', 'school_admin') or request.user.is_staff or request.user.is_superuser):
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
        return Response({'message': 'Password updated successfully'})
        
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
