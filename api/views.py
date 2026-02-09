from rest_framework import viewsets, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.utils import timezone
from core.models import ExamPattern, QuestionPaper, Material, BlueprintTemplate, ExamBlueprint
from core import embeddings
from core.tasks import generate_paper_task
from core.views import extract_text_from_pdf, extract_text_from_docx
import os
import json
import tempfile
from .serializers import (
    ExamPatternSerializer,
    QuestionPaperSerializer,
    QuestionPaperListSerializer,
    MaterialSerializer,
    BlueprintTemplateSerializer,
    ExamBlueprintSerializer,
)

class LargeResultsSetPagination(PageNumberPagination):
    page_size = 1000
    page_size_query_param = 'page_size'
    max_page_size = 2000

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

class ExamPatternViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ExamPattern model.
    Provides CRUD operations for exam patterns (formerly called blueprints).
    """
    queryset = ExamPattern.objects.all().order_by('-created_at')
    serializer_class = ExamPatternSerializer
    pagination_class = LargeResultsSetPagination
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['class_name', 'subject', 'pattern_source']
    search_fields = ['name', 'subject', 'class_name']

    def perform_create(self, serializer):
        """Set the created_by field to the current user"""
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['post'])
    def generate_from_ai(self, request):
        """Generate a pattern structure from teacher input using AI"""
        # Use the API-layer service (ai_service) instead of core to ensure connectivity
        from .ai_service import generate_pattern_via_api
        
        class_name = request.data.get("class_name")
        subject = request.data.get("subject")
        pattern_name = request.data.get("name")
        teacher_input = request.data.get("teacher_input")
        
        if not teacher_input:
            return Response({"error": "Teacher input is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            # We use the API service which doesn't suppress errors, allowing us to see connection issues
            pattern_data = generate_pattern_via_api(
                teacher_input=teacher_input,
                class_name=class_name,
                subject=subject,
                exam_name=pattern_name
            )
            
            # Create the pattern
            pattern = ExamPattern.objects.create(
                name=pattern_name,
                description=f"AI-generated pattern for {class_name} {subject}",
                subject=subject,
                class_name=class_name,
                sections=pattern_data.get('sections', []),
                total_marks=pattern_data.get('total_marks', 0),
                total_questions=pattern_data.get('total_questions', 0),
                pattern_source='ai_generated',
                ai_prompt=teacher_input,
                created_by=request.user
            )
            
            serializer = self.get_serializer(pattern)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            # If AI fails, return the error to the frontend so the user knows backend failed
            return Response(
                {"error": f"AI Generation Failed: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def by_subject_and_class(self, request):
        """Get patterns filtered by subject and class"""
        subject = request.query_params.get('subject')
        class_name = request.query_params.get('class')
        
        queryset = self.queryset
        if subject:
            queryset = queryset.filter(subject=subject)
        if class_name:
            queryset = queryset.filter(class_name=class_name)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def regenerate(self, request, pk=None):
        """Regenerate an AI pattern structure from updated prompt"""
        pattern = self.get_object()
        
        if pattern.pattern_source != 'ai_generated':
            return Response({"error": "Only AI-generated patterns can be regenerated"}, status=status.HTTP_400_BAD_REQUEST)
            
        new_prompt = request.data.get("ai_prompt")
        if not new_prompt:
            return Response({"error": "Prompt is required for regeneration"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            from core.pattern_ai_generator import generate_pattern_from_text
            
            pattern_data = generate_pattern_from_text(
                teacher_input=new_prompt,
                class_name=pattern.class_name,
                subject=pattern.subject,
                exam_name=pattern.name
            )
            
            # Update the pattern
            pattern.sections = pattern_data['sections']
            pattern.total_marks = pattern_data['total_marks']
            pattern.total_questions = pattern_data['total_questions']
            pattern.ai_prompt = new_prompt
            pattern.save()
            
            serializer = self.get_serializer(pattern)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class QuestionPaperViewSet(viewsets.ModelViewSet):
    """
    ViewSet for QuestionPaper model.
    Provides CRUD operations for generated question papers.
    """
    serializer_class = QuestionPaperSerializer
    pagination_class = LargeResultsSetPagination
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['class_name', 'subject', 'status', 'difficulty']
    search_fields = ['subject', 'class_name']

    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        """Get summary statistics for the dashboard"""
        user = request.user
        if user.is_staff or user.is_superuser:
            queryset = QuestionPaper.objects.all()
        else:
            queryset = QuestionPaper.objects.filter(created_by=user)
            
        total_papers = queryset.count()
        
        # Calculate monthly papers
        first_day_of_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        this_month_count = queryset.filter(created_at__gte=first_day_of_month).count()
        
        # Calculate success rate
        done_count = queryset.filter(status='done').count()
        success_rate = 0
        if total_papers > 0:
            success_rate = (done_count / total_papers) * 100
            
        return Response({
            'total_papers': total_papers,
            'this_month': this_month_count,
            'success_rate': f"{int(success_rate)}%",
        })

    def get_queryset(self):
        """Return question papers, optionally filtered by current user"""
        queryset = QuestionPaper.objects.all().order_by('-created_at')
        created_by = self.request.query_params.get('created_by')
        
        if created_by == 'me' and self.request.user.is_authenticated:
            queryset = queryset.filter(created_by=self.request.user)
        
        return queryset

    def get_serializer_class(self):
        """Use simplified serializer for list view"""
        if self.action == 'list':
            return QuestionPaperListSerializer
        return QuestionPaperSerializer

    def create(self, request, *args, **kwargs):
        """
        Create a new question paper and trigger the generation task.
        Handles both logic and legacy core processing flow via API.
        """
        try:
            # Extract data from request
            data = request.data
            
            # Handle chapters (comma-separated string -> list)
            chapters_str = data.get("chapters", "")
            chapters_list = [ch.strip() for ch in chapters_str.split(",") if ch.strip()]
            
            # Get blueprint ID if provided
            blueprint_id = data.get("blueprint", "")
            class_name = data.get("class_name")
            subject = data.get("subject")
            pattern_id = data.get("pattern")
            
            # Additional Documents Handling
            additional_context_text = ""
            additional_docs = request.FILES.getlist('additional_docs')
            
            for doc_file in additional_docs:
                file_extension = os.path.splitext(doc_file.name)[1].lower()
                if file_extension == '.pdf':
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_pdf:
                        for chunk in doc_file.chunks():
                            temp_pdf.write(chunk)
                        temp_pdf_path = temp_pdf.name
                    additional_context_text += extract_text_from_pdf(temp_pdf_path) + "\n"
                    os.unlink(temp_pdf_path)
                elif file_extension == '.docx':
                    additional_context_text += extract_text_from_docx(doc_file) + "\n"
            
            # Validate Blueprint
            if blueprint_id:
                if blueprint_id.startswith("exam_"):
                    bp_id = blueprint_id.replace("exam_", "")
                    blueprint = get_object_or_404(ExamBlueprint, id=bp_id, is_active=True)
                    if blueprint.class_name != class_name.split("-")[0] or blueprint.subject.lower() != subject.lower():
                        return Response({"error": "Selected blueprint doesn't match the class and subject."}, status=status.HTTP_400_BAD_REQUEST)
                elif blueprint_id.startswith("template_"):
                    tp_id = blueprint_id.replace("template_", "")
                    template = get_object_or_404(BlueprintTemplate, id=tp_id, is_active=True)
                    if template.class_name != class_name.split("-")[0] or template.subject.lower() != subject.lower():
                        return Response({"error": "Selected blueprint template doesn't match class/subject."}, status=status.HTTP_400_BAD_REQUEST)
                        
            # Create Paper Object
            paper = QuestionPaper.objects.create(
                class_name=class_name,
                subject=subject,
                pattern_id=pattern_id,
                chapters=chapters_list,
                difficulty=data.get("difficulty", "Medium"),
                created_by=request.user,
                status="queued"
            )

            # Metadata for Task
            try:
                selected_pattern = ExamPattern.objects.get(id=pattern_id)
            except ExamPattern.DoesNotExist:
                selected_pattern = None

            model_source = request.session.get('model_choice', 'aws')
            
            meta_payload = {
                "class_name": class_name,
                "duration": data.get("duration", "").strip(),
                "marks": data.get("total_marks", "").strip(),
                "test_type": (selected_pattern.name if selected_pattern else ""),
                "extra_context": additional_context_text,
            }
            additional_context_json = json.dumps(meta_payload)

            # Trigger Celery Task
            task = generate_paper_task.delay(
                paper.id, 
                blueprint_id=blueprint_id, 
                model_source=model_source, 
                additional_context=additional_context_json
            )
            
            paper.task_id = task.id
            paper.save()

            serializer = self.get_serializer(paper)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_create(self, serializer):
        """Set the created_by field to the current user"""
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['get'])
    def status(self, request, pk=None):
        """Get the current status of a question paper generation task"""
        paper = self.get_object()
        return Response({
            'id': paper.id,
            'status': paper.status,
            'task_id': paper.task_id,
            'cost': str(paper.cost) if paper.cost else None,
        })

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a question paper generation task"""
        paper = self.get_object()
        if paper.status in ['queued', 'generating']:
            # TODO: Implement Celery task cancellation
            paper.status = 'cancelled'
            paper.save()
            return Response({'status': 'Task cancelled'})
        return Response(
            {'error': 'Cannot cancel task with status: ' + paper.status},
            status=status.HTTP_400_BAD_REQUEST
        )

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """Retry a failed question paper generation task"""
        try:
            paper = self.get_object()
            
            # Using the exact logic from core.views.retry_paper_view
            if paper.status == "failed" or paper.status == "cancelled":
                paper.status = "queued"
                paper.save()
                
                # Trigger the celery task
                task = generate_paper_task.delay(paper.id)
                paper.task_id = task.id
                paper.save()
                
                return Response({'status': 'Retry initiated', 'task_id': task.id})
            
            return Response({'error': 'Paper must be in failed or cancelled state to retry'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        """Delete multiple question papers"""
        ids = request.data.get('ids', [])
        if not ids:
            return Response({'error': 'No IDs provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        papers = QuestionPaper.objects.filter(id__in=ids)
        count = papers.count()
        papers.delete()
        
        return Response({'message': f'Successfully deleted {count} papers'})

    @action(detail=True, methods=['get'])
    def get_content(self, request, pk=None):
        """Get the text content of the paper for editing"""
        paper = self.get_object()
        
        # If we have edited content, return it
        if paper.edited_content:
            return Response({'content': paper.edited_content})
            
        # Otherwise, try to extract from PDF
        if paper.file:
            try:
                content = extract_text_from_pdf(paper.file.path)
                return Response({'content': content})
            except Exception as e:
                return Response({'error': f"Failed to extract text: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({'content': ''})

    @action(detail=True, methods=['post'])
    def save_content(self, request, pk=None):
        """Save edited content"""
        paper = self.get_object()
        content = request.data.get('content', '')
        
        paper.edited_content = content
        paper.save()
        
        return Response({'status': 'Content saved'})

    @action(detail=True, methods=['post'])
    def regenerate_pdf(self, request, pk=None):
        """Regenerate PDF from edited content"""
        paper = self.get_object()
        content = request.data.get('content', '') or paper.edited_content
        
        if not content:
            return Response({'error': 'No content to generate PDF from'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            # Save content first
            paper.edited_content = content
            paper.save()
            
            # Generate PDF logic (ReportLab)
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.utils import simpleSplit
            from io import BytesIO
            import os
            from django.conf import settings
            from django.core.files import File

            packet = BytesIO()
            can = canvas.Canvas(packet, pagesize=A4)
            y = 750

            can.setFont("Helvetica", 11)
            lines = content.split('\n')

            for line in lines:
                if y < 50:
                    can.showPage()
                    y = 750
                    can.setFont("Helvetica", 11)

                if line.strip():
                    wrapped_lines = simpleSplit(line, "Helvetica", 11, 500)
                    for wrapped_line in wrapped_lines:
                        if y < 50:
                            can.showPage()
                            y = 750
                        can.drawString(50, y, wrapped_line)
                        y -= 14
                else:
                    y -= 10

            can.save()
            packet.seek(0)

            # Save the PDF
            from django.core.files.base import ContentFile
            
            filename = f"edited_{paper.subject}_{paper.id}.pdf"
            
            # Save directly to the model field
            # This handles storage and naming
            paper.file.save(filename, ContentFile(packet.getvalue()))
            paper.save()
            
            return Response({'status': 'PDF regenerated successfully', 'file_url': paper.file.url})
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MaterialViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Material model.
    Provides CRUD operations for educational materials (textbooks, notes, etc.).
    """
    queryset = Material.objects.all().select_related('uploaded_by').order_by('-uploaded_at')
    serializer_class = MaterialSerializer
    pagination_class = LargeResultsSetPagination
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['class_name', 'subject', 'type', 'unit']
    search_fields = ['title', 'subject', 'class_name']

    def perform_create(self, serializer):
        """Set the uploaded_by field to the current user"""
        serializer.save(uploaded_by=self.request.user)

    def create(self, request, *args, **kwargs):
        """Custom create to handle bulk and multi-chapter uploads with embeddings"""
        # Handle standard single file upload via DRF (no bulk/multi-chapter fields)
        if "bulk_upload" not in request.data and "chapter_count" not in request.data:
            return super().create(request, *args, **kwargs)

        class_name = request.data.get("class_name")
        subject = request.data.get("subject")
        material_type = request.data.get("type", "textbook")
        bulk_upload = str(request.data.get("bulk_upload")).lower() == "true"
        
        if not all([class_name, subject, material_type]):
            return Response({"error": "Missing required fields: class_name, subject, type"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        materials_to_ingest = []
        user = request.user if request.user.is_authenticated else None

        try:
            # Handle bulk upload
            if bulk_upload:
                files = request.FILES.getlist("bulk_files")
                if not files:
                    return Response({"error": "No files provided for bulk upload"}, status=status.HTTP_400_BAD_REQUEST)
                
                for file in files:
                    if not file: continue
                    filename = file.name
                    base_name = os.path.splitext(filename)[0]
                    
                    material = Material.objects.create(
                        class_name=class_name,
                        subject=subject,
                        unit=base_name if material_type == 'textbook' else None,
                        title=base_name,
                        type=material_type,
                        file=file,
                        uploaded_by=user,
                    )
                    materials_to_ingest.append({
                        "unit": material.unit,
                        "title": material.title,
                        "file_path": material.file.path,
                    })
            
            else:
                chapter_count = int(request.data.get("chapter_count", 0))
                if chapter_count == 0:
                   # Try fallback to standard creation if no chapters
                   return super().create(request, *args, **kwargs)

                for i in range(chapter_count):
                    unit = request.data.get(f"unit_{i}")
                    title = request.data.get(f"title_{i}")
                    file = request.FILES.get(f"file_{i}")

                    if not file: continue

                    material = Material.objects.create(
                        class_name=class_name,
                        subject=subject,
                        unit=unit,
                        title=title,
                        type=material_type,
                        file=file,
                        uploaded_by=user,
                    )
                    materials_to_ingest.append({
                        "unit": unit,
                        "title": title,
                        "file_path": material.file.path,
                    })

            # Ingest embeddings if materials were created
            if materials_to_ingest:
                chunks_added = embeddings.ingest_bulk(class_name, subject, materials_to_ingest, material_type=material_type)
                return Response({
                    "message": f"Successfully uploaded {len(materials_to_ingest)} materials and generated embeddings.",
                    "count": len(materials_to_ingest),
                    "chunks": chunks_added
                }, status=status.HTTP_201_CREATED)

            return Response({"error": "No files were successfully processed"}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({"error": f"Upload failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BlueprintTemplateViewSet(viewsets.ModelViewSet):
    """
    ViewSet for BlueprintTemplate model.
    Provides CRUD operations for blueprint templates.
    """
    queryset = BlueprintTemplate.objects.filter(is_active=True).order_by('subject', 'class_name')
    serializer_class = BlueprintTemplateSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filterset_fields = ['subject', 'class_name', 'is_default']
    search_fields = ['name', 'subject']

    def perform_create(self, serializer):
        """Set the created_by field to the current user"""
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def defaults(self, request):
        """Get default templates for each subject/class combination"""
        defaults = self.queryset.filter(is_default=True)
        serializer = self.get_serializer(defaults, many=True)
        return Response(serializer.data)


class ExamBlueprintViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ExamBlueprint model.
    Provides CRUD operations for exam blueprints.
    """
    queryset = ExamBlueprint.objects.filter(is_active=True).order_by('class_name', 'subject')
    serializer_class = ExamBlueprintSerializer
    pagination_class = LargeResultsSetPagination
    permission_classes = [IsAuthenticatedOrReadOnly]
    filterset_fields = ['class_name', 'subject']
    search_fields = ['subject', 'class_name', 'code']

    def perform_create(self, serializer):
        """Set the created_by field to the current user"""
        serializer.save(created_by=self.request.user)

@api_view(['GET'])
@permission_classes([IsAuthenticatedOrReadOnly])
def get_subjects_for_class(request):
    """API version of subjects lookup"""
    class_name = request.GET.get("class_name", "").strip()
    if not class_name:
        return Response({"subjects": []})
    
    class_num = class_name.split("-")[0]
    subjects = Material.objects.filter(
        class_name__istartswith=class_num
    ).values_list("subject", flat=True).distinct().order_by("subject")
    
    return Response({"subjects": list(subjects)})

@api_view(['GET'])
@permission_classes([IsAuthenticatedOrReadOnly])
def get_chapters(request):
    """API version of chapters lookup"""
    class_name = request.GET.get("class_name", "").strip()
    subject = request.GET.get("subject", "").strip()
    
    if not class_name or not subject:
        return Response({"chapters": []})

    # Exact logic from core.views.get_chapters
    class_num = class_name.split("-")[0]
    chapters = Material.objects.filter(
        class_name__istartswith=class_num,
        subject__iexact=subject
    ).values_list("unit", flat=True).distinct().order_by("unit")

    return Response({"chapters": list(chapters)})

@api_view(['GET'])
@permission_classes([IsAuthenticatedOrReadOnly])
def get_blueprints(request):
    """API version of blueprint lookup"""
    try:
        class_name = request.GET.get("class_name", "").strip()
        subject = request.GET.get("subject", "").strip()
        
        if not class_name or not subject:
            return Response({"blueprints": []})
            
        class_num = class_name.split("-")[0]
        
        # 1. Standard Blueprint Templates
        templates = BlueprintTemplate.objects.filter(
            class_name=class_num,
            subject__iexact=subject,
            is_active=True
        ).values('id', 'name', 'created_at')
        
        template_list = []
        for t in templates:
            template_list.append({
                'id': f"template_{t['id']}",
                'name': f"[Template] {t['name']}",
                'source': 'template',
                'created_at': t['created_at']
            })

        # 2. AI-generated Blueprints (iterate objects to avoid field errors)
        blueprints = ExamBlueprint.objects.filter(
            class_name=class_num,
            subject__iexact=subject,
            is_active=True
        )

        blueprint_list = []
        for b in blueprints:
             blueprint_list.append({
                'id': f"exam_{b.id}",
                'name': f"Blueprint - {b.subject}" + (f" ({b.code})" if b.code else ""),
                'source': 'generated',
                'created_at': b.created_at
            })
        
        # Helper to ensure datetime for sorting
        def get_sort_key(item):
            val = item.get('created_at')
            if val is None:
                return timezone.now()
            if isinstance(val, str):
                from django.utils.dateparse import parse_datetime
                val = parse_datetime(val) or timezone.now()
            return val

        # Combine and sort (newest first)
        combined = sorted(
            template_list + blueprint_list, 
            key=get_sort_key, 
            reverse=True
        )
        
        return Response({"blueprints": combined})
    except Exception as e:
        import traceback
        return Response({"error": str(e), "trace": traceback.format_exc()}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticatedOrReadOnly])
def get_blueprint_details(request, blueprint_id):
    """API version of blueprint details lookup"""
    try:
        if blueprint_id.startswith("exam_"):
            bp_id = blueprint_id.replace("exam_", "")
            blueprint = ExamBlueprint.objects.get(id=bp_id)
            # Safe data extraction
            bp_json = blueprint.blueprint or {}
            
            # Calculate total marks from sections if not present
            total_marks = bp_json.get('total_marks', 0)
            if not total_marks and 'sections' in bp_json:
                try:
                    total_marks = sum(int(s.get('marks', 0)) for s in bp_json['sections'])
                except:
                    total_marks = 0

            return Response({
                "success": True,
                "blueprint": {
                    "id": blueprint.id,
                    "title": f"Blueprint - {blueprint.subject}",
                    "sections": bp_json.get('sections', []),
                    "total_marks": total_marks
                }
            })
        elif blueprint_id.startswith("template_"):
            tp_id = blueprint_id.replace("template_", "")
            template = BlueprintTemplate.objects.get(id=tp_id)
            tp_json = template.blueprint or {}
            
            # Calculate total marks if missing
            total_marks = tp_json.get('total_marks', 0)
            if not total_marks and 'sections' in tp_json:
                try:
                    total_marks = sum(int(s.get('marks', 0)) for s in tp_json['sections'])
                except:
                    total_marks = 0

            return Response({
                "success": True,
                "blueprint": {
                    "id": template.id,
                    "title": template.name,
                    "sections": tp_json.get('sections', []),
                    "total_marks": total_marks
                }
            })
        else:
            return Response({"success": False, "error": "Invalid ID format"}, status=400)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=404)

@api_view(['POST', 'GET'])
@permission_classes([IsAuthenticated])
def model_choice(request):
    """
    API endpoint to toggle AI Model (Ollama/AWS)
    Affects session state which is used by the generation task.
    """
    if request.method == 'POST':
        choice = request.data.get('model_choice')
        if choice in ['aws', 'local']:
            request.session['model_choice'] = choice
            return Response({"model_choice": choice, "message": f"Switched to {choice.upper()}"})
        return Response({"error": "Invalid choice. Use 'aws' or 'local'."}, status=400)
    
    # GET request
    return Response({
        "model_choice": request.session.get('model_choice', 'aws')
    })
