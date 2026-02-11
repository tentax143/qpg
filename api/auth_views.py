from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.authtoken.models import Token
from django.contrib.auth import login as django_login, logout as django_logout
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from .auth_serializers import (
    LoginSerializer, RegisterSerializer, UserSerializer,
    CreateUserSerializer, PasswordUpdateSerializer, ProfileUpdateSerializer
)


@api_view(['POST'])
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
@permission_classes([AllowAny])
def register(request):
    """
    Register endpoint - creates new user and returns token
    """
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user': UserSerializer(user).data
        }, status=status.HTTP_201_CREATED)
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
    List and create users (Admin only)
    """
    if not (request.user.is_staff or request.user.is_superuser):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        users = User.objects.all().order_by('-date_joined')
        return Response(UserSerializer(users, many=True).data)

    elif request.method == 'POST':
        serializer = CreateUserSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
def delete_user(request, pk):
    """
    Delete a user (Admin only)
    """
    if not (request.user.is_staff or request.user.is_superuser):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user_to_delete = get_object_or_404(User, pk=pk)
    
    if user_to_delete.is_superuser:
        return Response({'error': 'Cannot delete superuser'}, status=status.HTTP_400_BAD_REQUEST)
        
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
