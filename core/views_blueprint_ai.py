"""
Views for AI-powered blueprint generation from text
"""
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
import json
from .models import BlueprintTemplate, ExamBlueprint
from .blueprint_ai_generator import generate_blueprint_from_text


@login_required
def create_blueprint_from_text(request):
    """
    Page where teachers can paste text pattern and generate blueprint
    """
    if request.method == 'GET':
        return render(request, 'create_blueprint_ai.html', {
            'classes': ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'],
            'subjects': ['English', 'Mathematics', 'Science', 'Physics', 'Chemistry', 'Biology']
        })

    elif request.method == 'POST':
        # Get form data
        text_pattern = request.POST.get('text_pattern', '')
        class_name = request.POST.get('class_name', '')
        subject = request.POST.get('subject', '')
        blueprint_name = request.POST.get('blueprint_name', f'Class {class_name} {subject} Blueprint')
        blueprint_type = request.POST.get('blueprint_type', 'template')  # 'template' or 'exam'

        if not text_pattern or not class_name or not subject:
            messages.error(request, 'Please provide all required fields')
            return redirect('create_blueprint_from_text')

        try:
            # Generate blueprint using AI
            messages.info(request, 'Generating blueprint using AI... This may take a moment.')
            blueprint_json = generate_blueprint_from_text(text_pattern, class_name, subject)

            # Save to database based on type
            if blueprint_type == 'template':
                blueprint_obj, created = BlueprintTemplate.objects.update_or_create(
                    name=blueprint_name,
                    class_name=class_name,
                    subject=subject,
                    defaults={
                        'blueprint': blueprint_json,
                        'is_active': True,
                        'is_default': False
                    }
                )
                model_name = "Blueprint Template"
            else:
                blueprint_obj, created = ExamBlueprint.objects.update_or_create(
                    class_name=class_name,
                    subject=subject,
                    defaults={
                        'blueprint': blueprint_json,
                        'is_active': True
                    }
                )
                model_name = "Exam Blueprint"

            if created:
                messages.success(request, f'{model_name} created successfully!')
            else:
                messages.success(request, f'{model_name} updated successfully!')

            # Show the generated blueprint
            return render(request, 'blueprint_result.html', {
                'blueprint': blueprint_json,
                'blueprint_obj': blueprint_obj,
                'class_name': class_name,
                'subject': subject,
                'original_text': text_pattern
            })

        except Exception as e:
            messages.error(request, f'Error generating blueprint: {str(e)}')
            return redirect('create_blueprint_from_text')


@csrf_exempt
@login_required
def generate_blueprint_api(request):
    """
    API endpoint to generate blueprint from text
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            text_pattern = data.get('text_pattern', '')
            class_name = data.get('class_name', '')
            subject = data.get('subject', '')

            if not text_pattern or not class_name or not subject:
                return JsonResponse({
                    'success': False,
                    'error': 'Missing required fields'
                }, status=400)

            # Generate blueprint
            blueprint = generate_blueprint_from_text(text_pattern, class_name, subject)

            return JsonResponse({
                'success': True,
                'blueprint': blueprint
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)

    return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)


@login_required
def preview_blueprint(request):
    """
    Preview blueprint before saving
    """
    if request.method == 'POST':
        try:
            blueprint_json = json.loads(request.POST.get('blueprint_json', '{}'))
            return render(request, 'blueprint_preview.html', {
                'blueprint': blueprint_json
            })
        except:
            messages.error(request, 'Invalid blueprint format')
            return redirect('create_blueprint_from_text')