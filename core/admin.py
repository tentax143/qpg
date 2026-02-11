from django.contrib import admin
from .models import ExamPattern, QuestionPaper, Material, BlueprintTemplate, ExamBlueprint

@admin.register(ExamPattern)
class ExamPatternAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    search_fields = ("name",)

@admin.register(QuestionPaper)
class QuestionPaperAdmin(admin.ModelAdmin):
    list_display = ("class_name", "subject", "pattern", "status", "created_at")
    list_filter = ("status", "subject")
    search_fields = ("class_name", "subject")

@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "class_name", "subject", "type", "uploaded_at")
    list_filter = ("type", "subject")
    search_fields = ("title", "class_name", "subject")

@admin.register(BlueprintTemplate)
class BlueprintTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "class_name", "is_default", "is_active", "created_at")
    list_filter = ("subject", "class_name", "is_default", "is_active")
    search_fields = ("name", "subject", "class_name")
    list_editable = ("is_default", "is_active")

@admin.register(ExamBlueprint)
class ExamBlueprintAdmin(admin.ModelAdmin):
    list_display = ("class_name", "subject", "code", "is_active", "created_at")
    list_filter = ("class_name", "subject", "is_active")
    search_fields = ("class_name", "subject", "code")
    list_editable = ("is_active",)
