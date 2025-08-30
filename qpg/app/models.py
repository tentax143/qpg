from django.db import models
from django.contrib.auth.models import User

class QuestionPaper(models.Model):
    CLASS_CHOICES = [(str(i), f"Class {i}") for i in range(8, 13)]
    DIFFICULTY_CHOICES = [
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
    ]

    teacher = models.ForeignKey(User, on_delete=models.CASCADE)
    class_name = models.CharField(max_length=10, choices=CLASS_CHOICES)
    subject = models.CharField(max_length=100)
    unit = models.CharField(max_length=50)
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES)
    pdf_file = models.FileField(upload_to="question_papers/")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.class_name} - {self.subject} ({self.unit})"
