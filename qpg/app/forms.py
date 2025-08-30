from django import forms
from .models import QuestionPaper

class GeneratePaperForm(forms.Form):
    class_name = forms.ChoiceField(choices=QuestionPaper.CLASS_CHOICES)
    subject = forms.CharField(max_length=100)
    unit = forms.CharField(max_length=50)
    difficulty = forms.ChoiceField(choices=QuestionPaper.DIFFICULTY_CHOICES)
