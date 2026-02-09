from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class ExamPattern(models.Model):
    """
    Unified exam pattern model that combines blueprint and pattern functionality.
    Stores complete exam structure with sections, instructions, and constraints.
    """
    # Basic info
    name = models.CharField(max_length=100)   # e.g. "PT-2", "Half-Yearly"
    description = models.TextField(blank=True)
    subject = models.CharField(max_length=100, default="")
    class_name = models.CharField(max_length=10, default="")

    # Comprehensive pattern structure
    sections = models.JSONField()  # Enhanced structure with instructions and constraints

    # Metadata
    total_marks = models.IntegerField(default=0)
    total_questions = models.IntegerField(default=0)

    # Track source
    PATTERN_SOURCE_CHOICES = [
        ('manual', 'Manual Creation'),
        ('ai_generated', 'AI Generated'),
        ('imported', 'Imported'),
    ]
    pattern_source = models.CharField(max_length=20, choices=PATTERN_SOURCE_CHOICES, default='manual')
    ai_prompt = models.TextField(blank=True)  # Store original teacher input for reference

    # Timestamps
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Exam Pattern"
        verbose_name_plural = "Exam Patterns"

    def __str__(self):
        return f"{self.name} - {self.class_name} {self.subject}"

    def get_total_marks(self):
        """Calculate total marks from sections"""
        total = 0
        for section in self.sections:
            total += section.get('marks', 0)
            # Handle subsections
            for subsec in section.get('subsections', []):
                total += subsec.get('marks', 0)
        return total

    def get_total_questions(self):
        """Calculate total questions from sections"""
        total = 0
        for section in self.sections:
            total += section.get('questions_count', 0)
            # Handle subsections
            for subsec in section.get('subsections', []):
                total += subsec.get('questions_count', 0)
        return total

class QuestionPaper(models.Model):
    class_name = models.CharField(max_length=10)   # "11-A"
    subject = models.CharField(max_length=50)      # "Biology"
    pattern = models.ForeignKey(ExamPattern, on_delete=models.CASCADE)
    chapters = models.JSONField()                  # ["4","5","6"]
    difficulty = models.CharField(max_length=20, default="Medium")
    file = models.FileField(upload_to="question_papers/", blank=True, null=True)
    status = models.CharField(max_length=20, default="queued")  # queued/generating/done/cancelled
    task_id = models.CharField(max_length=255, blank=True, null=True)  # Celery task ID
    edited_content = models.TextField(blank=True, null=True)  # Store edited content from the editor
    cost = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True) # Cost of generation
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # Track when the paper was last edited

    def __str__(self):
        return f"{self.class_name} - {self.subject} ({self.pattern})"

class Material(models.Model):
    MATERIAL_TYPES = [
        ("textbook", "Textbook"),
        ("notes", "Notes"),
        ("bank", "Question Bank"),
        ("syllabus", "Syllabus"),
        ("reference", "Reference Book"),
    ]

    class_name = models.CharField(max_length=10)
    subject = models.CharField(max_length=50)
    unit = models.CharField(max_length=50, blank=True, null=True)
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="materials/")
    type = models.CharField(max_length=50, choices=MATERIAL_TYPES)
    metadata = models.JSONField(default=dict)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.class_name} {self.subject} - {self.title}"
from django.db import models

class BlueprintTemplate(models.Model):
    """Template for creating blueprints with predefined question types and structures"""
    name = models.CharField(max_length=100, unique=True)  # e.g. "CBSE English Core", "CBSE Biology"
    subject = models.CharField(max_length=100)
    class_name = models.CharField(max_length=10)
    description = models.TextField(blank=True)
    
    # Enhanced blueprint structure with question types
    blueprint = models.JSONField(default=dict)  # Enhanced structure with question types
    
    # Metadata
    is_default = models.BooleanField(default=False)  # Mark as default template
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['subject', 'class_name', 'is_default']
        ordering = ['subject', 'class_name', 'name']

    def __str__(self):
        return f"{self.name} - {self.class_name} {self.subject}"

class ExamBlueprint(models.Model):
    """Enhanced blueprint model for specific exam configurations"""
    class_name = models.CharField(max_length=10)   # e.g. "11-A", "12-B"
    subject = models.CharField(max_length=100)
    code = models.CharField(max_length=20, blank=True, null=True)  # e.g. "301" for English Core
    
    # Enhanced blueprint structure
    blueprint = models.JSONField(default=dict)
    
    # Template reference
    template = models.ForeignKey(BlueprintTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Metadata
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['class_name', 'subject']

    def __str__(self):
        return f"{self.class_name} {self.subject} ({self.code})"


# ==============================
# User profile for auth features
# ==============================
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    require_password_change = models.BooleanField(default=True)

    def __str__(self):
        return f"Profile({self.user.username})"


class GeneratedQuestion(models.Model):
    """
    Track generated questions to avoid duplicates across multiple paper generations.
    Stores question text, embedding, and metadata for similarity checking.
    """
    class_name = models.CharField(max_length=10)
    subject = models.CharField(max_length=50)
    chapter = models.CharField(max_length=50, blank=True, null=True)
    question_text = models.TextField()
    question_hash = models.CharField(max_length=64, db_index=True)  # SHA256 hash for quick lookup
    embedding = models.JSONField(null=True, blank=True)  # Store embedding vector for similarity
    question_type = models.CharField(max_length=50, blank=True)
    marks = models.IntegerField(default=1)
    paper_id = models.ForeignKey(QuestionPaper, on_delete=models.CASCADE, related_name='generated_questions', null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['class_name', 'subject', 'chapter']),
            models.Index(fields=['question_hash']),
        ]

    def __str__(self):
        return f"{self.class_name} {self.subject} - {self.question_text[:50]}..."


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    # Create profile on first save
    if created:
        UserProfile.objects.create(user=instance)
    else:
        # Ensure profile exists for older users
        UserProfile.objects.get_or_create(user=instance)
