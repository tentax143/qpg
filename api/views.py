from rest_framework import viewsets, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.utils import timezone
from core.models import ExamPattern, QuestionPaper, Material, BlueprintTemplate, ExamBlueprint, Subject
from core import embeddings
from core.tasks import generate_paper_task, ingest_material_task
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

def _get_school(user):
    """Return the school for a user, or None."""
    try:
        return user.profile.school
    except Exception:
        return None


def _user_role(user):
    try:
        return user.profile.role
    except Exception:
        return None


def _allowed_subject(user):
    try:
        return user.profile.allowed_subject or None
    except Exception:
        return None


class ExamPatternViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ExamPattern model.
    Provides CRUD operations for exam patterns (formerly called blueprints).
    """
    serializer_class = ExamPatternSerializer
    pagination_class = LargeResultsSetPagination
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['class_name', 'subject', 'pattern_source']
    search_fields = ['name', 'subject', 'class_name']

    def get_queryset(self):
        from django.db.models import Q
        user = self.request.user
        if not user.is_authenticated:
            return ExamPattern.objects.all().order_by('-created_at')
        role = _user_role(user)
        if role == 'superadmin' or user.is_superuser:
            return ExamPattern.objects.all().order_by('-created_at')
        # Global patterns (One Mark Test, CBSE official) are always visible
        global_q = Q(pattern_source__in=['one_mark_test', 'cbse_official'])
        school = _get_school(user)
        if school:
            return ExamPattern.objects.filter(
                global_q | Q(created_by__profile__school=school)
            ).order_by('-created_at')
        return ExamPattern.objects.filter(
            global_q | Q(created_by=user)
        ).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['post'])
    def generate_from_ai(self, request):
        """Queue AI pattern generation as a Celery task. Returns 202 immediately."""
        from core.tasks import generate_pattern_task

        class_name    = request.data.get("class_name", "")
        subject       = request.data.get("subject", "")
        pattern_name  = request.data.get("name", "")
        teacher_input = request.data.get("teacher_input", "")

        if not teacher_input:
            return Response({"error": "Teacher input is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Create placeholder so the frontend gets an id to poll immediately
        pattern = ExamPattern.objects.create(
            name=pattern_name or f"AI Pattern — {subject} {class_name}",
            description=f"AI-generated pattern for {class_name} {subject}",
            subject=subject,
            class_name=class_name,
            sections=[],
            total_marks=0,
            total_questions=0,
            pattern_source='ai_generated',
            ai_prompt=teacher_input,
            status='queued',
            created_by=request.user,
        )

        task = generate_pattern_task.delay(pattern.id)
        pattern.task_id = task.id
        pattern.save(update_fields=['task_id'])

        return Response(
            {'id': pattern.id, 'task_id': task.id, 'status': 'queued'},
            status=status.HTTP_202_ACCEPTED,
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
        """Re-queue AI generation from an updated prompt. Returns 202."""
        from core.tasks import generate_pattern_task

        pattern = self.get_object()
        if pattern.pattern_source != 'ai_generated':
            return Response({"error": "Only AI-generated patterns can be regenerated"}, status=status.HTTP_400_BAD_REQUEST)

        new_prompt = request.data.get("ai_prompt")
        if not new_prompt:
            return Response({"error": "Prompt is required for regeneration"}, status=status.HTTP_400_BAD_REQUEST)

        pattern.ai_prompt = new_prompt
        pattern.status    = 'queued'
        pattern.sections  = []
        pattern.save(update_fields=['ai_prompt', 'status', 'sections'])

        task = generate_pattern_task.delay(pattern.id)
        pattern.task_id = task.id
        pattern.save(update_fields=['task_id'])

        return Response(
            {'id': pattern.id, 'task_id': task.id, 'status': 'queued'},
            status=status.HTTP_202_ACCEPTED,
        )


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
        user = self.request.user
        base = QuestionPaper.objects.all().order_by('-created_at')
        if not user.is_authenticated:
            return base
        role = _user_role(user)
        if role == 'superadmin' or user.is_superuser:
            queryset = base
        else:
            school = _get_school(user)
            if school:
                queryset = base.filter(created_by__profile__school=school)
            else:
                queryset = base.filter(created_by=user)

        created_by = self.request.query_params.get('created_by')
        if created_by == 'me':
            queryset = queryset.filter(created_by=user)
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

            allowed = _allowed_subject(request.user)
            if allowed and subject and subject.lower() != allowed.lower():
                return Response({"error": f"You can only generate papers for: {allowed}"}, status=status.HTTP_403_FORBIDDEN)

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
            
            # One Mark Test: read question count (default 20)
            num_one_mark = None
            if selected_pattern and selected_pattern.pattern_source == 'one_mark_test':
                try:
                    num_one_mark = max(1, min(200, int(data.get('num_one_mark_questions', 20))))
                except (ValueError, TypeError):
                    num_one_mark = 20

            school_name = ""
            try:
                school = request.user.profile.school
                if school:
                    school_name = school.name or ""
            except Exception:
                pass

            meta_payload = {
                "class_name": class_name,
                "duration": data.get("duration", "").strip(),
                "marks": data.get("total_marks", "").strip(),
                "test_type": (selected_pattern.name if selected_pattern else ""),
                "extra_context": additional_context_text,
                "num_one_mark_questions": num_one_mark,
                "school_name": school_name,
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
    def rerender(self, request, pk=None):
        """Re-render the DOCX from the stored paper_data JSON without calling the LLM."""
        paper = self.get_object()
        if not paper.paper_data:
            return Response(
                {'error': 'No stored paper_data for this paper. Only papers generated after this feature was added can be re-rendered.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from core.generator import _render_paper_from_data, pattern_sections_to_blueprint_dict
            from django.core.files import File as DjangoFile

            class_name = paper.class_name
            if '-' in class_name:
                class_name = class_name.split('-', 1)[0]

            school_name = ""
            try:
                school = paper.created_by.profile.school
                if school:
                    school_name = school.name or ""
            except Exception:
                pass

            import json as _rerender_json
            rerender_ctx = _rerender_json.dumps({
                "class_name": class_name,
                "school_name": school_name,
                "marks": str(paper.pattern.total_marks) if paper.pattern else "",
                "test_type": paper.pattern.name if paper.pattern else "",
            })

            blueprint = pattern_sections_to_blueprint_dict(paper.pattern)
            file_path, summary, _, _, _ = _render_paper_from_data(
                paper_data=paper.paper_data,
                blueprint=blueprint,
                class_name=class_name,
                subject=paper.subject,
                chapters=paper.chapters,
                additional_context=rerender_ctx,
                pattern=paper.pattern,
            )

            import os
            from django.conf import settings as django_settings
            full_path = os.path.join(django_settings.MEDIA_ROOT, file_path)
            if os.path.exists(full_path):
                with open(full_path, 'rb') as f:
                    filename = os.path.basename(file_path)
                    paper.file.save(filename, DjangoFile(f), save=False)
            paper.save(update_fields=['file', 'updated_at'])

            return Response({'status': 'Re-rendered', 'file': paper.file.url if paper.file else None})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
    serializer_class = MaterialSerializer
    pagination_class = LargeResultsSetPagination
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['class_name', 'subject', 'type', 'unit']
    search_fields = ['title', 'subject', 'class_name']

    def get_queryset(self):
        user = self.request.user
        base = Material.objects.all().select_related('uploaded_by', 'school').order_by('-uploaded_at')
        if not user.is_authenticated:
            return base
        role = _user_role(user)
        if role == 'superadmin' or user.is_superuser:
            return base
        school = _get_school(user)
        if school:
            return base.filter(school=school)
        return base.filter(uploaded_by=user)

    def perform_create(self, serializer):
        school = _get_school(self.request.user)
        serializer.save(uploaded_by=self.request.user, school=school)

    def perform_destroy(self, instance):
        school_id = instance.school_id
        if instance.type == 'textbook':
            embeddings.delete_unit_embeddings(instance.class_name, instance.subject, instance.unit, school_id=None)
            if school_id:
                embeddings.delete_unit_embeddings(instance.class_name, instance.subject, instance.unit, school_id=school_id)
        else:
            embeddings.delete_unit_embeddings(instance.class_name, instance.subject, instance.unit, school_id=school_id)
        instance.delete()

    def create(self, request, *args, **kwargs):
        """Custom create to handle bulk and multi-chapter uploads with embeddings"""
        # Handle standard single file upload via DRF (no bulk/multi-chapter fields)
        if "bulk_upload" not in request.data and "chapter_count" not in request.data:
            return super().create(request, *args, **kwargs)

        class_name = request.data.get("class_name")
        subject = request.data.get("subject")
        material_type = request.data.get("type", "textbook")
        bulk_upload = str(request.data.get("bulk_upload")).lower() == "true"

        allowed = _allowed_subject(request.user)
        if allowed and subject and subject.lower() != allowed.lower():
            return Response({"error": f"You can only upload materials for: {allowed}"}, status=status.HTTP_403_FORBIDDEN)

        embedding_provider = request.data.get("embedding_provider", "local")
        if embedding_provider not in ("local", "openrouter"):
            embedding_provider = "local"
        
        if not all([class_name, subject, material_type]):
            return Response({"error": "Missing required fields: class_name, subject, type"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        materials_to_ingest = []
        user = request.user if request.user.is_authenticated else None
        school = _get_school(user) if user else None
        school_id = school.id if school else None

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
                        school=school,
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
                        school=school,
                        uploaded_by=user,
                    )
                    materials_to_ingest.append({
                        "unit": unit,
                        "title": title,
                        "file_path": material.file.path,
                    })

            # Queue embedding ingestion via Celery
            if materials_to_ingest:
                task = ingest_material_task.apply_async(args=[class_name, subject, materials_to_ingest, material_type], kwargs={'provider': embedding_provider, 'school_id': school_id})
                return Response({
                    "message": f"Uploaded {len(materials_to_ingest)} material(s). Embedding ingestion queued ({embedding_provider}).",
                    "count": len(materials_to_ingest),
                    "task_id": task.id,
                    "provider": embedding_provider,
                }, status=status.HTTP_202_ACCEPTED)

            return Response({"error": "No files were successfully processed"}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({"error": f"Upload failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        ids = request.data.get('ids', [])
        if not ids:
            return Response({'error': 'No IDs provided'}, status=status.HTTP_400_BAD_REQUEST)
        qs = self.get_queryset().filter(id__in=ids)
        count = qs.count()
        if count == 0:
            return Response({'error': 'No matching materials found'}, status=status.HTTP_404_NOT_FOUND)

        # Delete embeddings per material, respecting school-scoped namespaces
        for m in qs.select_related('school'):
            school_id = m.school_id
            if m.type == 'textbook':
                embeddings.delete_unit_embeddings(m.class_name, m.subject, m.unit, school_id=None)
                if school_id:
                    embeddings.delete_unit_embeddings(m.class_name, m.subject, m.unit, school_id=school_id)
            else:
                embeddings.delete_unit_embeddings(m.class_name, m.subject, m.unit, school_id=school_id)

        qs.delete()
        return Response({'message': f'Deleted {count} material(s)'})


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
@permission_classes([AllowAny])
def subjects_list(request):
    """Return all seeded CBSE subjects."""
    names = list(Subject.objects.values_list('name', flat=True))
    return Response({'subjects': names})


@api_view(['GET'])
@permission_classes([AllowAny])
def cbse_exam_types(request):
    """Return CBSE exam types metadata (PT1/PT2/PT3/HY/Board etc.)."""
    from core.data.cbse_patterns import EXAM_TYPES
    active = {
        k: v for k, v in EXAM_TYPES.items()
        if v.get('status') not in ('discontinued_2017',)
    }
    return Response({'exam_types': active})


@api_view(['GET'])
@permission_classes([AllowAny])
def cbse_subject_pattern(request):
    """
    Return CBSE official paper pattern for a subject+class combo.
    Query params: ?subject=Physics&class=12
    """
    from core.data.cbse_patterns import get_pattern
    subject = request.query_params.get('subject', '').strip()
    class_name = request.query_params.get('class', '').strip()
    if not subject:
        return Response({'error': 'subject param required'}, status=400)
    pattern = get_pattern(subject)
    if pattern is None:
        return Response({'error': f'No official CBSE pattern found for subject: {subject}'}, status=404)
    # Filter to the requested class if provided
    if class_name and class_name not in pattern.get('classes', []):
        return Response(
            {'error': f'{subject} pattern is only defined for classes {pattern.get("classes")}'},
            status=404,
        )
    return Response({'subject': subject, 'class': class_name or None, 'pattern': pattern})


@api_view(['GET'])
@permission_classes([IsAuthenticatedOrReadOnly])
def get_subjects_for_class(request):
    """Return subjects available to the requesting user's school."""
    class_name = request.GET.get("class_name", "").strip()
    if not class_name:
        return Response({"subjects": []})

    class_num = class_name.split("-")[0]
    base_qs = Material.objects.filter(class_name__istartswith=class_num)

    school = _get_school(request.user) if request.user.is_authenticated else None
    if school:
        # Own materials + shared textbooks (if school opted in)
        from django.db.models import Q
        school_filter = Q(school=school)
        if school.access_shared_vector_store:
            school_filter |= Q(type='textbook', school__isnull=True)
        qs = base_qs.filter(school_filter)
    else:
        qs = base_qs

    subjects = qs.values_list("subject", flat=True).distinct().order_by("subject")

    allowed = _allowed_subject(request.user) if request.user.is_authenticated else None
    if allowed:
        subjects = [s for s in list(subjects) if s.lower() == allowed.lower()]
        return Response({"subjects": subjects})

    return Response({"subjects": list(subjects)})


@api_view(['GET'])
@permission_classes([IsAuthenticatedOrReadOnly])
def get_chapters(request):
    """Return chapters available to the requesting user's school."""
    class_name = request.GET.get("class_name", "").strip()
    subject = request.GET.get("subject", "").strip()

    if not class_name or not subject:
        return Response({"chapters": []})

    class_num = class_name.split("-")[0]
    base_qs = Material.objects.filter(class_name__istartswith=class_num, subject__iexact=subject)

    school = _get_school(request.user) if request.user.is_authenticated else None
    if school:
        from django.db.models import Q
        school_filter = Q(school=school)
        if school.access_shared_vector_store:
            school_filter |= Q(type='textbook', school__isnull=True)
        qs = base_qs.filter(school_filter)
    else:
        qs = base_qs

    chapters = qs.values_list("unit", flat=True).distinct().order_by("unit")
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
