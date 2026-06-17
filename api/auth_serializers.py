from rest_framework import serializers
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token


class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    school_id = serializers.SerializerMethodField()
    school_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'is_staff', 'is_superuser',
                  'last_login', 'date_joined', 'role', 'school_id', 'school_name')
        read_only_fields = ('id', 'last_login', 'date_joined')

    def get_role(self, obj):
        try:
            return obj.profile.role
        except Exception:
            return 'teacher'

    def get_school_id(self, obj):
        try:
            return obj.profile.school_id
        except Exception:
            return None

    def get_school_name(self, obj):
        try:
            school = obj.profile.school
            return school.name if school else None
        except Exception:
            return None

class CreateUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    is_staff = serializers.BooleanField(default=False)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'is_staff')

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
            is_staff=validated_data.get('is_staff', False)
        )
        return user

class PasswordUpdateSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
    
class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name')

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        from django.contrib.auth import authenticate
        user = authenticate(
            username=data.get('username'),
            password=data.get('password')
        )
        if not user:
            raise serializers.ValidationError('Invalid credentials')
        data['user'] = user
        return data


