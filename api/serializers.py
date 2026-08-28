from rest_framework import serializers
from core.models import ExamPattern, QuestionPaper, Material, BlueprintTemplate, ExamBlueprint, Issue
from core.media_access import signed_file_url
from django.contrib.auth.models import User


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model - basic info only"""
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']
        read_only_fields = ['id']


class IssueSerializer(serializers.ModelSerializer):
    """User-reported issue. Reporters supply title + description; status and admin_note are
    managed by superadmin (the view forces safe defaults on create and gates edits)."""
    created_by = UserSerializer(read_only=True)
    school_name = serializers.CharField(source='school.name', read_only=True)

    class Meta:
        model = Issue
        fields = [
            'id', 'title', 'description', 'status', 'admin_note',
            'created_by', 'school_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_by', 'school_name', 'created_at', 'updated_at']


class ExamPatternSerializer(serializers.ModelSerializer):
    """Serializer for ExamPattern model"""
    created_by = UserSerializer(read_only=True)
    owner_school = serializers.SerializerMethodField()
    is_editable = serializers.SerializerMethodField()
    # How to describe this pattern's class scope: a band ("Classes 1-10") for the official sample
    # papers, the single class for everything else. Computed here so the UI never has to know the
    # band rules.
    class_label = serializers.CharField(read_only=True)

    def _school_of(self, obj):
        """The school that owns this pattern, via its creator's profile. None for premade
        templates (no creator) and for patterns whose creator has been deleted."""
        creator = obj.created_by
        profile = getattr(creator, 'profile', None) if creator else None
        return getattr(profile, 'school', None) if profile else None

    def get_owner_school(self, obj):
        """Named so the UI can say whose pattern this is — patterns are visible to every school
        now, so 'who made this' stops being obvious from the fact that you can see it."""
        school = self._school_of(obj)
        return school.name if school else None

    def get_is_editable(self, obj):
        """Whether the requesting user may edit/delete this one.

        Patterns are readable across schools but writable only by the school that made them, so
        the front end needs this to hide Edit/Delete rather than let a teacher click through to a
        403. Mirrors ExamPatternViewSet._assert_owned — the API stays the real enforcement point.
        """
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user is None or not getattr(user, 'is_authenticated', False):
            return False
        if getattr(user, 'is_superuser', False) or \
                getattr(getattr(user, 'profile', None), 'role', None) == 'superadmin':
            return True
        if obj.pattern_source in ('cbse_official', 'cbse_sqp', 'one_mark_test'):
            return False
        owner_school = self._school_of(obj)
        user_school = getattr(getattr(user, 'profile', None), 'school', None)
        if owner_school is not None and user_school is not None:
            return owner_school == user_school
        # No school on either side: fall back to "did I create it".
        return obj.created_by_id == user.id

    class Meta:
        model = ExamPattern
        fields = [
            'id', 'name', 'description', 'subject', 'class_name',
            'sections', 'total_marks', 'total_questions', 'pattern_source',
            'ai_prompt', 'status', 'task_id',
            'created_by', 'owner_school', 'is_editable',
            'class_min', 'class_max', 'class_label',
            'created_at', 'updated_at',
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
    file = serializers.SerializerMethodField()
    answer_key_status = serializers.SerializerMethodField()

    def get_file(self, obj):
        return signed_file_url(self.context.get('request'), obj.file)

    def get_answer_key_status(self, obj):
        # Raw stored status (no staleness re-hash here — the /answer_key/ endpoint does
        # that on read; hashing paper_data for every listed paper would be wasteful).
        try:
            return obj.answer_key.status
        except Exception:
            return 'none'

    class Meta:
        model = QuestionPaper
        fields = [
            'id', 'class_name', 'subject', 'pattern', 'pattern_id',
            'chapters', 'difficulty', 'creative_ratio', 'file', 'status', 'status_detail', 'task_id',
            'edited_content', 'cost', 'created_by', 'created_at', 'updated_at',
            'answer_key_status'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'status', 'status_detail', 'task_id']


class QuestionPaperListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing question papers"""
    pattern_name = serializers.CharField(source='pattern.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    has_paper_data = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    answer_key_status = serializers.SerializerMethodField()

    def get_has_paper_data(self, obj):
        return obj.paper_data is not None

    def get_file(self, obj):
        return signed_file_url(self.context.get('request'), obj.file)

    def get_answer_key_status(self, obj):
        # Raw stored status — see QuestionPaperSerializer.get_answer_key_status.
        try:
            return obj.answer_key.status
        except Exception:
            return 'none'

    class Meta:
        model = QuestionPaper
        fields = [
            'id', 'class_name', 'subject', 'pattern_name', 'difficulty',
            'status', 'status_detail', 'cost', 'created_by_name', 'created_at',
            'updated_at', 'file', 'has_paper_data', 'answer_key_status'
        ]
        read_only_fields = [
            'id', 'class_name', 'subject', 'pattern_name', 'difficulty',
            'status', 'status_detail', 'cost', 'created_by_name', 'created_at',
            'updated_at', 'has_paper_data', 'answer_key_status',
        ]


class MaterialSerializer(serializers.ModelSerializer):
    """Serializer for Material model"""
    uploaded_by = UserSerializer(read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    file = serializers.SerializerMethodField()

    def get_file(self, obj):
        return signed_file_url(self.context.get('request'), obj.file)

    class Meta:
        model = Material
        fields = [
            'id', 'class_name', 'subject', 'unit', 'title', 'type', 'type_display',
            'visibility', 'file', 'metadata', 'school', 'uploaded_by', 'uploaded_at'
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

    # A blueprint plans the units for ONE pattern. Writable by id; read back with enough of the
    # pattern to render a list without a second request per row.
    pattern_id = serializers.PrimaryKeyRelatedField(
        queryset=ExamPattern.objects.all(),
        source='pattern',
        required=False,
        allow_null=True,
    )
    pattern_name = serializers.CharField(source='pattern.name', read_only=True)
    pattern_total_marks = serializers.IntegerField(source='pattern.total_marks', read_only=True)
    mapped_questions = serializers.SerializerMethodField()
    units_used = serializers.SerializerMethodField()

    def get_mapped_questions(self, obj):
        """How many printed questions this blueprint actually pins — the one number that says
        whether a blueprint is filled in or an empty shell."""
        return sum(len(per_q) for per_q in obj.question_units().values())

    def get_units_used(self, obj):
        return obj.all_units()

    def validate(self, attrs):
        """A unit map is addressed by the PATTERN's question numbers, so it is meaningless
        without one. Reject early with a clear message instead of saving a blueprint that
        generation will silently ignore."""
        unit_map = attrs.get('unit_map', getattr(self.instance, 'unit_map', None))
        pattern = attrs.get('pattern', getattr(self.instance, 'pattern', None))
        if unit_map and not pattern:
            raise serializers.ValidationError(
                {'pattern_id': 'A unit map needs a pattern — its question numbers refer to that '
                               "pattern's printed questions."})
        return attrs

    class Meta:
        model = ExamBlueprint
        fields = [
            'id', 'name', 'class_name', 'subject', 'code',
            'pattern_id', 'pattern_name', 'pattern_total_marks',
            'unit_map', 'mapped_questions', 'units_used',
            'blueprint', 'template', 'template_id', 'is_active',
            'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

