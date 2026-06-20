from rest_framework import serializers
from core.models import ExamPattern, QuestionPaper, Material, BlueprintTemplate, ExamBlueprint
from django.contrib.auth.models import User


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model - basic info only"""
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']
        read_only_fields = ['id']


class ExamPatternSerializer(serializers.ModelSerializer):
    """Serializer for ExamPattern model"""
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = ExamPattern
        fields = [
            'id', 'name', 'description', 'subject', 'class_name',
            'sections', 'total_marks', 'total_questions', 'pattern_source',
            'ai_prompt', 'status', 'task_id',
            'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'status', 'task_id', 'created_at', 'updated_at']


class QuestionPaperSerializer(serializers.ModelSerializer):
    """Serializer for QuestionPaper model"""
    pattern = ExamPatternSerializer(read_only=True)
    pattern_id = serializers.PrimaryKeyRelatedField(
        queryset=ExamPattern.objects.all(),
        source='pattern',
        write_only=True
    )
    created_by = UserSerializer(read_only=True)
    
    class Meta:
        model = QuestionPaper
        fields = [
            'id', 'class_name', 'subject', 'pattern', 'pattern_id',
            'chapters', 'difficulty', 'file', 'status', 'task_id',
            'edited_content', 'cost', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'file', 'status', 'task_id']


class QuestionPaperListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing question papers"""
    pattern_name = serializers.CharField(source='pattern.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    has_paper_data = serializers.SerializerMethodField()

    def get_has_paper_data(self, obj):
        return obj.paper_data is not None

    class Meta:
        model = QuestionPaper
        fields = [
            'id', 'class_name', 'subject', 'pattern_name', 'difficulty',
            'status', 'cost', 'created_by_name', 'created_at', 'file',
            'has_paper_data'
        ]
        read_only_fields = fields


class MaterialSerializer(serializers.ModelSerializer):
    """Serializer for Material model"""
    uploaded_by = UserSerializer(read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    
    class Meta:
        model = Material
        fields = [
            'id', 'class_name', 'subject', 'unit', 'title', 'type', 'type_display',
            'file', 'metadata', 'school', 'uploaded_by', 'uploaded_at'
        ]
        read_only_fields = ['id', 'school', 'uploaded_at']


class BlueprintTemplateSerializer(serializers.ModelSerializer):
    """Serializer for BlueprintTemplate model"""
    created_by = UserSerializer(read_only=True)
    
    class Meta:
        model = BlueprintTemplate
        fields = [
            'id', 'name', 'subject', 'class_name', 'description',
            'blueprint', 'is_default', 'is_active', 'created_by',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ExamBlueprintSerializer(serializers.ModelSerializer):
    """Serializer for ExamBlueprint model"""
    template = BlueprintTemplateSerializer(read_only=True)
    template_id = serializers.PrimaryKeyRelatedField(
        queryset=BlueprintTemplate.objects.all(),
        source='template',
        write_only=True,
        required=False,
        allow_null=True
    )
    created_by = UserSerializer(read_only=True)
    
    class Meta:
        model = ExamBlueprint
        fields = [
            'id', 'class_name', 'subject', 'code',
            'blueprint', 'template', 'template_id', 'is_active',
            'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

