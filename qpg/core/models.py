from django.db import models
from django.contrib.auth.models import User

class ExamPattern(models.Model):
    name = models.CharField(max_length=100)   # e.g. "Half-Yearly"
    description = models.TextField(blank=True)
    sections = models.JSONField()             # [{"name":"A","questions":10,"marks":1}, ...]
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class QuestionPaper(models.Model):
    class_name = models.CharField(max_length=10)   # "11-A"
    subject = models.CharField(max_length=50)      # "Biology"
    pattern = models.ForeignKey(ExamPattern, on_delete=models.CASCADE)
    chapters = models.JSONField()                  # ["4","5","6"]
    difficulty = models.CharField(max_length=20, default="Medium")
    file = models.FileField(upload_to="question_papers/", blank=True, null=True)
    status = models.CharField(max_length=20, default="queued")  # queued/generating/done/cancelled
    task_id = models.CharField(max_length=255, blank=True, null=True)  # Celery task ID
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.class_name} - {self.subject} ({self.pattern})"

class Material(models.Model):
    MATERIAL_TYPES = [
        ("textbook", "Textbook"),
        ("notes", "Notes"),
        ("bank", "Question Bank"),
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
    class_name = models.CharField(max_length=10)   # e.g. "11", "12"
    section = models.CharField(max_length=5, blank=True, null=True)  # e.g. "A", "B"
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
        ordering = ['class_name', 'subject', 'section']

    def __str__(self):
        sec = f"-{self.section}" if self.section else ""
        return f"{self.class_name}{sec} {self.subject} ({self.code})"
