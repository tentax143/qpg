"""
Views for detailed blueprint builder
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

from .models import BlueprintTemplate, ExamBlueprint
from .models_extended import (
    DetailedBlueprintTemplate,
    QuestionSource,
    QuestionTypeConfig,
    initialize_defaults
)
from .blueprint_detail_builder import DetailedBlueprintBuilder


@login_required
def detailed_blueprint_builder(request):
    """Main page for detailed blueprint builder"""

    # Initialize defaults if not already done
    initialize_defaults()

    # Get available options
    question_sources = QuestionSource.objects.filter(is_active=True)
    question_types = QuestionTypeConfig.objects.filter(is_active=True)

    # Get classes and subjects
    classes = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12']
    subjects = ['English', 'Mathematics', 'Science', 'Physics', 'Chemistry', 'Biology', 'History', 'Geography']

    context = {
        'classes': classes,
        'subjects': subjects,
        'question_sources': question_sources,
        'question_types': question_types,
        'passage_types': ['narrative', 'descriptive', 'factual', 'discursive', 'persuasive'],
        'difficulty_levels': ['easy', 'medium', 'hard', 'mixed']
    }

    return render(request, 'blueprint_detail_builder.html', context)


@csrf_exempt
@login_required
def save_detailed_blueprint(request):
    """Save detailed blueprint via AJAX"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            # Extract blueprint data
            blueprint_name = data.get('name', '')
            class_name = data.get('class_name', '')
            subject = data.get('subject', '')
            blueprint_structure = data.get('blueprint_structure', {})

            if not all([blueprint_name, class_name, subject, blueprint_structure]):
                return JsonResponse({
                    'success': False,
                    'error': 'Missing required fields'
                }, status=400)

            # Create builder and validate
            builder = DetailedBlueprintBuilder.from_dict(blueprint_structure)
            validation = builder.validate()

            if not validation['valid']:
                return JsonResponse({
                    'success': False,
                    'errors': validation['errors'],
                    'warnings': validation['warnings']
                }, status=400)

            # Save to database
            detailed_blueprint, created = DetailedBlueprintTemplate.objects.update_or_create(
                name=blueprint_name,
                class_name=class_name,
                subject=subject,
                defaults={
                    'blueprint_structure': blueprint_structure,
                    'created_by': request.user
                }
            )

            # Also create a regular blueprint for compatibility
            regular_blueprint = convert_to_regular_blueprint(blueprint_structure)
            BlueprintTemplate.objects.update_or_create(
                name=f"{blueprint_name} (Detailed)",
                class_name=class_name,
                subject=subject,
                defaults={
                    'blueprint': regular_blueprint,
                    'is_active': True
                }
            )

            return JsonResponse({
                'success': True,
                'blueprint_id': detailed_blueprint.id,
                'created': created,
                'message': f"Blueprint {'created' if created else 'updated'} successfully",
                'validation': validation
            })

        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)

    return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)


@csrf_exempt
@login_required
def validate_blueprint_structure(request):
    """Validate blueprint structure via AJAX"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            blueprint_structure = data.get('blueprint_structure', {})

            builder = DetailedBlueprintBuilder.from_dict(blueprint_structure)
            validation = builder.validate()

            return JsonResponse(validation)

        except Exception as e:
            return JsonResponse({
                'valid': False,
                'errors': [str(e)],
                'warnings': []
            })

    return JsonResponse({'valid': False, 'errors': ['Method not allowed']}, status=405)


@login_required
def load_detailed_blueprint(request, blueprint_id):
    """Load existing detailed blueprint for editing"""
    blueprint = get_object_or_404(DetailedBlueprintTemplate, id=blueprint_id)

    return JsonResponse({
        'success': True,
        'blueprint': {
            'name': blueprint.name,
            'class_name': blueprint.class_name,
            'subject': blueprint.subject,
            'blueprint_structure': blueprint.blueprint_structure
        }
    })


@login_required
def parse_text_to_structure(request):
    """Parse teacher's text input into blueprint structure"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            text_input = data.get('text', '')
            class_name = data.get('class_name', '')
            subject = data.get('subject', '')

            if not text_input:
                return JsonResponse({
                    'success': False,
                    'error': 'No text provided'
                }, status=400)

            # Parse text using builder
            builder = DetailedBlueprintBuilder.from_simple_text(text_input, class_name, subject)
            blueprint_structure = builder.build()

            return JsonResponse({
                'success': True,
                'blueprint_structure': blueprint_structure
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)

    return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)


@login_required
def get_question_type_config(request, qtype_id):
    """Get configuration for a specific question type"""
    try:
        qtype = QuestionTypeConfig.objects.get(id=qtype_id)
        return JsonResponse({
            'success': True,
            'config': {
                'name': qtype.name,
                'display_name': qtype.display_name,
                'typical_marks': qtype.typical_marks,
                'min_marks': qtype.min_marks,
                'max_marks': qtype.max_marks,
                'requires_passage': qtype.requires_passage,
                'requires_extract': qtype.requires_extract,
                'answer_word_min': qtype.answer_word_min,
                'answer_word_max': qtype.answer_word_max
            }
        })
    except QuestionTypeConfig.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Question type not found'}, status=404)


def convert_to_regular_blueprint(detailed_structure):
    """Convert detailed blueprint to regular blueprint format"""
    regular_blueprint = {"sections": []}

    for section in detailed_structure.get('sections', []):
        regular_section = {
            "name": section['name'],
            "title": section['title'],
            "marks": section['marks'],
            "question_types": []
        }

        # Extract unique question types
        question_types = set()
        for q_spec in section.get('question_distribution', []):
            question_types.add(q_spec['type'])

        regular_section['question_types'] = list(question_types)
        regular_blueprint['sections'].append(regular_section)

    return regular_blueprint


@login_required
def list_detailed_blueprints(request):
    """List all detailed blueprints"""
    blueprints = DetailedBlueprintTemplate.objects.filter(is_active=True)

    if request.GET.get('class'):
        blueprints = blueprints.filter(class_name=request.GET['class'])
    if request.GET.get('subject'):
        blueprints = blueprints.filter(subject=request.GET['subject'])

    context = {
        'blueprints': blueprints,
        'classes': ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'],
        'subjects': ['English', 'Mathematics', 'Science', 'Physics', 'Chemistry', 'Biology']
    }

    return render(request, 'detailed_blueprint_list.html', context)


@login_required
def delete_detailed_blueprint(request, blueprint_id):
    """Delete a detailed blueprint"""
    if request.method == 'POST':
        blueprint = get_object_or_404(DetailedBlueprintTemplate, id=blueprint_id)

        # Check permission
        if blueprint.created_by != request.user and not request.user.is_staff:
            messages.error(request, 'You do not have permission to delete this blueprint')
            return redirect('list_detailed_blueprints')

        blueprint.delete()
        messages.success(request, 'Blueprint deleted successfully')

    return redirect('list_detailed_blueprints')