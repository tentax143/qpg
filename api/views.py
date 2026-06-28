from rest_framework import viewsets, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.utils import timezone
from core.models import ExamPattern, QuestionPaper, Material, BlueprintTemplate, ExamBlueprint, Subject, Plan
from core import embeddings
from core.tasks import generate_paper_task, ingest_material_task, split_book_task, ingest_url_task
from core.views import extract_text_from_pdf, extract_text_from_docx, extract_docx_text_with_images
from core.media_access import signed_file_url
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


ALLOWED_MATERIAL_EXTENSIONS = {'.pdf', '.docx', '.doc', '.txt'}


def _can_modify_paper(user, paper):
    """True if the user owns the paper or has school_admin/superadmin role."""
    if paper.created_by == user:
        return True
    role = _user_role(user)
    return role in ('superadmin', 'school_admin') or user.is_superuser


def _owner_scope(qs, user, owner_field='created_by'):
    """Visibility scoping: superadmin → everything; school_admin → their whole school;
    a normal teacher → ONLY their own creations (not the admin's or other teachers')."""
    role = _user_role(user)
    if role == 'superadmin' or user.is_superuser:
        return qs
    if role == 'school_admin':
        school = _get_school(user)
        if school:
            return qs.filter(**{f"{owner_field}__profile__school": school})
        return qs.filter(**{owner_field: user})
    # teacher / unknown role → own only
    return qs.filter(**{owner_field: user})


def _generation_blocked(user, exclude_id=None):
    """Guard before queuing a paper-generation task. Returns an error string if generation
    should be refused (concurrency / budget / plan limit), else None."""
    # One active generation per user — a paper is expensive; don't let a user queue several.
    active = QuestionPaper.objects.filter(created_by=user, status__in=['queued', 'generating'])
    if exclude_id is not None:
        active = active.exclude(id=exclude_id)
    if active.exists():
        return ("You already have a paper generating. Please wait for it to finish before "
                "starting another.")

    school = _get_school(user)

    # Plan-based monthly paper limit.
    if school:
        plan = school.effective_plan()
        if plan and not plan.is_unlimited_papers:
            used = school.papers_this_month()
            if used >= plan.monthly_paper_limit:
                return (
                    f"Your school has reached its monthly paper limit "
                    f"({used}/{plan.monthly_paper_limit} papers on the {plan.display_name} plan). "
                    "Upgrade your plan to generate more papers."
                )

    # Legacy school token budget (0 = unlimited).
    if school and school.monthly_token_budget and school.total_tokens_used >= school.monthly_token_budget:
        return (f"Your school has reached its token budget "
                f"({school.total_tokens_used:,}/{school.monthly_token_budget:,} tokens). "
                "Contact your administrator to raise it.")
    return None


def _scoped_blueprints(user):
    """ExamBlueprint visible to this user — shared school-wide (any member sees the school's
    blueprints), all for superadmin. Blueprints are reusable structures, not private content."""
    base = ExamBlueprint.objects.filter(is_active=True)
    if _user_role(user) == 'superadmin' or user.is_superuser:
        return base
    school = _get_school(user)
    return base.filter(created_by__profile__school=school) if school else base.filter(created_by=user)


def _scoped_blueprint_templates(user):
    """BlueprintTemplate visible to this user — shared (default/superadmin) templates plus the
    whole school's (reusable structures), never another school's."""
    from django.db.models import Q
    base = BlueprintTemplate.objects.filter(is_active=True)
    if _user_role(user) == 'superadmin' or user.is_superuser:
        return base
    shared = (Q(is_default=True) | Q(created_by__isnull=True)
              | Q(created_by__is_superuser=True) | Q(created_by__profile__role='superadmin'))
    school = _get_school(user)
    return base.filter(shared | Q(created_by__profile__school=school)) if school else base.filter(shared | Q(created_by=user))


def _render_paper_from_stored_data(paper, request=None):
    """Re-render paper.file from paper.paper_data (preserves images, marks, grouping).
    Returns a signed file URL. Shared by rerender / ai_edit / restore_data."""
    import os, json as _json
    from django.conf import settings as _dj
    from core.generator import _render_paper_from_data, pattern_sections_to_blueprint_dict

    class_name = paper.class_name.split('-', 1)[0] if '-' in (paper.class_name or '') else paper.class_name
    school_name = ''
    try:
        s = paper.created_by.profile.school
        school_name = (s.name or '') if s else ''
    except Exception:
        pass
    ctx = _json.dumps({
        "class_name": class_name,
        "school_name": school_name,
        "marks": str(paper.pattern.total_marks) if paper.pattern else "",
        "test_type": paper.pattern.name if paper.pattern else "",
    })
    blueprint = pattern_sections_to_blueprint_dict(paper.pattern)
    file_path, *_rest = _render_paper_from_data(
        paper_data=paper.paper_data, blueprint=blueprint, class_name=class_name,
        subject=paper.subject, chapters=paper.chapters, additional_context=ctx, pattern=paper.pattern,
        cache_only=True,   # web request: reuse cached images, never call the slow image APIs
    )
    if os.path.exists(os.path.join(_dj.MEDIA_ROOT, file_path)):
        paper.file.name = file_path        # assign directly — file.save() renames on collision → 404
    paper.save(update_fields=['file', 'updated_at'])
    return signed_file_url(request, paper.file)


def _paper_section_iter(paper_data):
    """Yield (section_name, section_dict) for each section that has a questions list.
    Handles paper_data shaped as {Section:{...}}, {sections:{...}}, or {sections:[...]}."""
    secs = paper_data.get('sections', paper_data) if isinstance(paper_data, dict) else paper_data
    if isinstance(secs, dict):
        for sname, sec in secs.items():
            if isinstance(sec, dict) and isinstance(sec.get('questions'), list):
                yield (sec.get('section_name') or sname), sec
    elif isinstance(secs, list):
        for sec in secs:
            if isinstance(sec, dict) and isinstance(sec.get('questions'), list):
                yield (sec.get('section_name') or sec.get('name') or ''), sec


def _extract_json_blob(s):
    """Pull the first balanced JSON object/array out of an LLM reply (tolerates fences/prose)."""
    import json as _json, re as _re
    if not s:
        return None
    s = _re.sub(r'```(?:json)?', '', s).strip()
    for opener, closer in (('{', '}'), ('[', ']')):
        start = s.find(opener)
        if start < 0:
            continue
        depth = 0
        for i in range(start, len(s)):
            if s[i] == opener:
                depth += 1
            elif s[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return _json.loads(s[start:i + 1])
                    except Exception:
                        break
    return None


class ExamPatternViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ExamPattern model.
    Provides CRUD operations for exam patterns (formerly called blueprints).
    """
    serializer_class = ExamPatternSerializer
    pagination_class = LargeResultsSetPagination
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['class_name', 'subject', 'pattern_source']
    search_fields = ['name', 'subject', 'class_name']

    def get_queryset(self):
        user = self.request.user
        role = _user_role(user)
        if role == 'superadmin' or user.is_superuser:
            return ExamPattern.objects.all().order_by('-created_at')
        # Patterns are a SHARED school resource — every member of the school sees ALL of the
        # school's patterns (any subject, any creator), so they can reuse each other's. (Papers,
        # by contrast, stay private to their creator.) Premade superadmin templates remain hidden
        # — reachable only via the `templates` action (clone-only).
        school = _get_school(user)
        if school:
            return ExamPattern.objects.filter(created_by__profile__school=school).order_by('-created_at')
        return ExamPattern.objects.filter(created_by=user).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @staticmethod
    def _template_queryset():
        """Premade patterns owned by the superadmin / seeded — the clone source."""
        from django.db.models import Q
        return ExamPattern.objects.filter(
            Q(pattern_source__in=['cbse_official', 'one_mark_test'])
            | Q(created_by__isnull=True)
            | Q(created_by__is_superuser=True)
            | Q(created_by__profile__role='superadmin')
        )

    @action(detail=False, methods=['get'])
    def templates(self, request):
        """
        Premade superadmin patterns available to clone, filtered by class / subject /
        exam_type. This is the ONLY way non-superadmins reach premade patterns (they're
        hidden from the normal list). Returns a list; the frontend previews + clones one.
        """
        qs = self._template_queryset()
        class_name = request.query_params.get('class') or request.query_params.get('class_name')
        subject    = request.query_params.get('subject')
        exam_type  = request.query_params.get('exam_type')

        if class_name:
            qs = qs.filter(class_name__iexact=class_name)
        if subject:
            narrowed = qs.filter(subject__iexact=subject)
            qs = narrowed if narrowed.exists() else qs.filter(subject__icontains=subject)

        results = list(qs.order_by('-created_at'))
        # Soft exam_type narrowing by name; keep the broader set if nothing name-matches.
        if exam_type:
            et = exam_type.strip().lower()
            hit = [p for p in results if et in (p.name or '').lower()]
            if hit:
                results = hit

        return Response(ExamPatternSerializer(results, many=True).data)

    @action(detail=False, methods=['post'], url_path='clone-template')
    def clone_template(self, request):
        """
        Clone a premade superadmin pattern into a NEW pattern owned by the caller
        (school-scoped). Copies the template's sections verbatim so the full compound
        structure is preserved (the section editor would flatten it).
        """
        template_id = request.data.get('template_id')
        if not template_id:
            return Response({"error": "template_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            template = self._template_queryset().get(id=int(template_id))
        except (ExamPattern.DoesNotExist, TypeError, ValueError):
            return Response({"error": "Template pattern not found"}, status=status.HTTP_404_NOT_FOUND)

        new_pattern = ExamPattern.objects.create(
            name=(request.data.get('name') or template.name or 'Untitled Pattern'),
            description=request.data.get('description', template.description or ''),
            subject=request.data.get('subject', template.subject),
            class_name=request.data.get('class_name', template.class_name),
            sections=template.sections,          # verbatim — preserves question_types/sub_questions
            total_marks=template.total_marks,
            total_questions=template.total_questions,
            sqp_year=template.sqp_year,
            pattern_source='manual',             # now a user-owned pattern, not a premade template
            status='done',
            created_by=request.user,
        )
        return Response(ExamPatternSerializer(new_pattern).data, status=status.HTTP_201_CREATED)

    # Global/system templates shared across all schools — only a superadmin may delete these.
    _GLOBAL_SOURCES = ('cbse_official', 'one_mark_test')

    def _is_superadmin(self, user):
        return _user_role(user) == 'superadmin' or user.is_superuser

    def destroy(self, request, *args, **kwargs):
        """Block non-superadmins from deleting shared global templates (cbse_official / one_mark_test)."""
        instance = self.get_object()
        if instance.pattern_source in self._GLOBAL_SOURCES and not self._is_superadmin(request.user):
            return Response(
                {"error": "Shared official patterns can only be deleted by a superadmin."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        """
        Delete multiple patterns by id. Scoped to what the caller may see (enforces
        school-wise isolation) and may delete (non-superadmins cannot remove shared
        global templates). Returns counts of deleted / skipped / not-found.
        """
        ids = request.data.get('ids', [])
        if not isinstance(ids, list) or not ids:
            return Response({"error": "Provide a non-empty 'ids' list."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            return Response({"error": "'ids' must be a list of integers."}, status=status.HTTP_400_BAD_REQUEST)

        # get_queryset() already restricts to the caller's school / own + global templates,
        # so ids belonging to other schools are silently excluded here.
        visible = self.get_queryset().filter(id__in=ids)

        protected_skipped = []
        deletable = visible
        if not self._is_superadmin(request.user):
            protected_skipped = list(
                visible.filter(pattern_source__in=self._GLOBAL_SOURCES).values_list('id', flat=True)
            )
            deletable = visible.exclude(pattern_source__in=self._GLOBAL_SOURCES)

        deletable_ids = list(deletable.values_list('id', flat=True))
        deletable.delete()

        not_found = sorted(set(ids) - set(deletable_ids) - set(protected_skipped))
        return Response({
            'deleted': len(deletable_ids),
            'deleted_ids': deletable_ids,
            'protected_skipped': protected_skipped,        # shared templates (need superadmin)
            'not_found_or_forbidden': not_found,           # not in caller's scope (e.g. other school)
        })

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
        
        queryset = self.get_queryset()
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
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['class_name', 'subject', 'status', 'difficulty']
    search_fields = ['subject', 'class_name']

    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        """Get summary statistics for the dashboard"""
        user = request.user
        # Same visibility as the list: admin → school-wide, teacher → own only.
        queryset = _owner_scope(QuestionPaper.objects.all(), user)

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
        # Hierarchical visibility: superadmin → all, school_admin → whole school,
        # teacher → only their own papers (can't see the admin's or other teachers').
        queryset = _owner_scope(QuestionPaper.objects.all().order_by('-created_at'), user)
        if self.request.query_params.get('created_by') == 'me':
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
            # Budget / concurrency guard — refuse before creating the paper or queuing work.
            blocked = _generation_blocked(request.user)
            if blocked:
                return Response({'error': blocked}, status=status.HTTP_429_TOO_MANY_REQUESTS)

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
                    blueprint = get_object_or_404(_scoped_blueprints(request.user), id=bp_id)
                    if blueprint.class_name != class_name.split("-")[0] or blueprint.subject.lower() != subject.lower():
                        return Response({"error": "Selected blueprint doesn't match the class and subject."}, status=status.HTTP_400_BAD_REQUEST)
                elif blueprint_id.startswith("template_"):
                    tp_id = blueprint_id.replace("template_", "")
                    template = get_object_or_404(_scoped_blueprint_templates(request.user), id=tp_id)
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
        if not _can_modify_paper(request.user, paper):
            return Response({'error': 'Not authorized to cancel this paper'}, status=status.HTTP_403_FORBIDDEN)
        if paper.status in ['queued', 'generating']:
            # Actually revoke the Celery task (terminate if already running) so it stops
            # consuming a worker, then mark cancelled.
            if paper.task_id:
                try:
                    from celery import current_app
                    current_app.control.revoke(paper.task_id, terminate=True, signal='SIGTERM')
                except Exception as _e:
                    print(f"[Cancel] revoke failed for task {paper.task_id}: {_e}")
            paper.status = 'cancelled'
            paper.status_detail = 'Cancelled by user.'
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
            if not _can_modify_paper(request.user, paper):
                return Response({'error': 'Not authorized to retry this paper'}, status=status.HTTP_403_FORBIDDEN)

            # Allow retry for failed/cancelled papers, and for ones stuck 'queued'/'generating'
            # (e.g. a dead worker) — revoking the stale task first so it can't double-run.
            if paper.status in ("failed", "cancelled", "queued", "generating"):
                if paper.status in ("queued", "generating") and paper.task_id:
                    try:
                        from celery import current_app
                        current_app.control.revoke(paper.task_id, terminate=True, signal='SIGTERM')
                    except Exception as _e:
                        print(f"[Retry] revoke of stale task {paper.task_id} failed: {_e}")
                blocked = _generation_blocked(request.user, exclude_id=paper.id)
                if blocked:
                    return Response({'error': blocked}, status=status.HTTP_429_TOO_MANY_REQUESTS)
                paper.status = "queued"
                paper.status_detail = ""
                paper.save()

                # Trigger the celery task
                task = generate_paper_task.delay(paper.id)
                paper.task_id = task.id
                paper.save()

                return Response({'status': 'Retry initiated', 'task_id': task.id})

            return Response({'error': 'Paper cannot be retried from its current state'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def regenerate(self, request, pk=None):
        """Regenerate the paper from scratch using its EXISTING config (class, subject, pattern,
        chapters, difficulty) — produces fresh questions in place. Works on a completed paper
        (unlike retry, which is only for failed/cancelled)."""
        paper = self.get_object()
        if not _can_modify_paper(request.user, paper):
            return Response({'error': 'Not authorized to regenerate this paper'}, status=status.HTTP_403_FORBIDDEN)
        if paper.status == 'generating':
            return Response({'error': 'Generation already in progress for this paper'}, status=status.HTTP_400_BAD_REQUEST)
        if not paper.pattern:
            return Response({'error': 'This paper has no pattern to regenerate from'}, status=status.HTTP_400_BAD_REQUEST)

        import json as _json
        school_name = ""
        try:
            school = paper.created_by.profile.school
            school_name = (school.name or "") if school else ""
        except Exception:
            pass

        num_one_mark = None
        if paper.pattern.pattern_source == 'one_mark_test':
            try:
                num_one_mark = max(1, min(200, int(request.data.get('num_one_mark_questions',
                                                                     paper.pattern.total_questions or 20))))
            except (ValueError, TypeError):
                num_one_mark = 20

        meta_payload = {
            "class_name": paper.class_name,
            "duration": str(request.data.get('duration', '') or '').strip(),
            "marks": str(paper.pattern.total_marks or ''),
            "test_type": paper.pattern.name or '',
            "extra_context": '',
            "num_one_mark_questions": num_one_mark,
            "school_name": school_name,
        }

        blocked = _generation_blocked(request.user, exclude_id=paper.id)
        if blocked:
            return Response({'error': blocked}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Re-queue. Keep the current file/paper_data until the new one is ready (so the paper
        # stays viewable if generation fails); drop any AI-edited text overlay.
        paper.status = 'queued'
        paper.edited_content = None
        paper.save(update_fields=['status', 'edited_content', 'updated_at'])

        task = generate_paper_task.delay(
            paper.id,
            model_source=request.session.get('model_choice', 'aws'),
            additional_context=_json.dumps(meta_payload),
        )
        paper.task_id = task.id
        paper.save(update_fields=['task_id'])
        return Response({'status': 'Regeneration started', 'task_id': task.id})

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        """Delete multiple question papers"""
        ids = request.data.get('ids', [])
        if not ids:
            return Response({'error': 'No IDs provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        papers = self.get_queryset().filter(id__in=ids)
        count = papers.count()
        papers.delete()
        
        return Response({'message': f'Successfully deleted {count} papers'})

    @action(detail=True, methods=['get'])
    def docx_file(self, request, pk=None):
        """Return the raw DOCX file as a binary download (used by the frontend preview)."""
        from django.http import FileResponse, Http404
        import re as _re
        paper = self.get_object()
        if not paper.file:
            raise Http404("No file for this paper")
        path = paper.file.path
        if not os.path.exists(path):
            stripped = _re.sub(r'_[A-Za-z0-9]{7}(\.[^.]+)$', r'\1', path)
            if os.path.exists(stripped):
                path = stripped
            else:
                raise Http404("File not found on disk")
        filename = os.path.basename(path)
        response = FileResponse(open(path, 'rb'),
                                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        response['Access-Control-Allow-Origin'] = '*'
        return response

    @action(detail=True, methods=['get'])
    def docx_preview(self, request, pk=None):
        """Convert the paper DOCX to HTML for Word-like browser preview."""
        paper = self.get_object()
        if not paper.file:
            return Response({'error': 'No file available'}, status=status.HTTP_404_NOT_FOUND)
        try:
            import mammoth
            path = paper.file.path
            # Resolve renamed-suffix path if needed (same fallback as serve_media)
            if not os.path.exists(path):
                import re as _re
                stripped = _re.sub(r'_[A-Za-z0-9]{7}(\.[^.]+)$', r'\1', path)
                if os.path.exists(stripped):
                    path = stripped
            with open(path, 'rb') as f:
                result = mammoth.convert_to_html(f)
            return Response({'html': result.value, 'messages': [m.message for m in result.messages]})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def get_content(self, request, pk=None):
        """Get the text content of the paper for editing"""
        paper = self.get_object()
        
        # If we have edited content, return it
        if paper.edited_content:
            return Response({'content': paper.edited_content})
            
        # Otherwise extract from the file — dispatch by extension
        if paper.file:
            try:
                path = paper.file.path
                if path.lower().endswith('.docx'):
                    # Image-aware extraction so diagrams survive the AI-edit round-trip.
                    content = extract_docx_text_with_images(path, paper.id)
                else:
                    content = extract_text_from_pdf(path)
                return Response({'content': content})
            except Exception as e:
                return Response({'error': f"Failed to extract text: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({'content': ''})

    @action(detail=True, methods=['post'])
    def rerender(self, request, pk=None):
        """Re-render the DOCX from the stored paper_data JSON without calling the LLM."""
        paper = self.get_object()
        if not _can_modify_paper(request.user, paper):
            return Response({'error': 'Not authorized to re-render this paper'}, status=status.HTTP_403_FORBIDDEN)
        if not paper.paper_data:
            return Response(
                {'error': 'No stored paper_data for this paper. Only papers generated after this feature was added can be re-rendered.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from core.generator import _render_paper_from_data, pattern_sections_to_blueprint_dict

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
                cache_only=True,   # web request: reuse cached images, never call the slow image APIs
            )

            import os
            from django.conf import settings as django_settings
            full_path = os.path.join(django_settings.MEDIA_ROOT, file_path)
            if os.path.exists(full_path):
                # Assign directly — do NOT use file.save() which renames on collision → 404
                paper.file.name = file_path
            paper.save(update_fields=['file', 'updated_at'])

            return Response({'status': 'Re-rendered', 'file': signed_file_url(request, paper.file)})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def ai_correct(self, request, pk=None):
        """Apply an AI correction instruction to the current paper text."""
        paper = self.get_object()
        if not _can_modify_paper(request.user, paper):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

        content     = request.data.get('content', '').strip()
        instruction = request.data.get('instruction', '').strip()
        if not instruction:
            return Response({'error': 'No instruction provided'}, status=status.HTTP_400_BAD_REQUEST)
        if not content:
            return Response({'error': 'No content to correct'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from core import mantle_client
            system = (
                "You are a CBSE exam paper editor. You receive a question paper in plain text and a correction "
                "instruction from the teacher. Apply the correction precisely and return ONLY the corrected paper "
                "text — no explanation, no commentary, no markdown fences.\n"
                "IMPORTANT: The paper may contain image markers like [IMG_FILE: generated_images/...]. These mark "
                "diagrams that belong to a question. Preserve every [IMG_FILE: ...] marker EXACTLY as-is, on its own "
                "line, in the same position relative to its question, unless the instruction explicitly says to "
                "remove that image. Never alter the path inside a marker."
            )
            prompt = f"PAPER:\n{content}\n\nCORRECTION INSTRUCTION:\n{instruction}\n\nCorrected paper:"
            corrected, _, _ = mantle_client.converse(
                model_id=mantle_client.GEN_MODEL,
                prompt=prompt,
                system_prompt=system,
                max_tokens=4000,
                temperature=0.3,
            )
            return Response({'corrected_content': corrected.strip()})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def render_edited_docx(self, request, pk=None):
        """Regenerate a properly-formatted DOCX from AI-corrected plain text."""
        paper = self.get_object()
        if not _can_modify_paper(request.user, paper):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

        content = request.data.get('content', '').strip() or (paper.edited_content or '').strip()
        if not content:
            return Response({'error': 'No content to render'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from core.generator import render_docx, _parse_edited_text

            all_questions = _parse_edited_text(content)

            school_name = ''
            try:
                school = paper.created_by.profile.school
                if school:
                    school_name = school.name or ''
            except Exception:
                pass

            header_meta = {
                'class_name': paper.class_name,
                'subject': paper.subject,
                'pattern_name': paper.pattern.name if paper.pattern else '',
                'marks': paper.pattern.total_marks if paper.pattern else '',
                'school_name': school_name,
            }

            file_path, _ = render_docx(
                class_name=paper.class_name,
                subject=paper.subject,
                chapters=paper.chapters,
                all_questions=all_questions,
                summary={},
                header_meta=header_meta,
            )

            # Persist corrected text and point paper.file at the new DOCX
            paper.edited_content = content
            paper.file.name = file_path
            paper.save(update_fields=['edited_content', 'file'])

            return Response({'file': signed_file_url(request, paper.file), 'status': 'rendered'})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def ai_edit(self, request, pk=None):
        """Operation-based AI edit (two-stage) — full control over the paper.

        1. PLAN — the LLM turns the teacher's natural-language instruction into a list of
           structured operations over a compact index of the paper's questions:
           edit / replace / add / move (across sections) / delete / swap / set / set_section.
        2. APPLY — core.paper_edit applies them deterministically (content ops call the model
           for the new question text), renumbers questions 1..N, and we re-render.

        Operations are honoured AS REQUESTED (e.g. a cross-section move is not blocked); a
        post-edit marks audit reports any resulting pattern mismatch as a warning instead.
        Operating on paper_data (not whole-paper text) preserves images, per-type marks, and
        section grouping. Returns 'no_paper_data' (400) for legacy papers so the client can
        fall back to the text flow.
        """
        import copy, json as _json
        from core import mantle_client
        from core.paper_edit import apply_operations
        from core.section_generator import _regen_question_skeleton

        paper = self.get_object()
        if not _can_modify_paper(request.user, paper):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        instruction = (request.data.get('instruction') or '').strip()
        if not instruction:
            return Response({'error': 'No instruction provided'}, status=status.HTTP_400_BAD_REQUEST)
        pd = paper.paper_data
        if not isinstance(pd, dict) or not pd:
            return Response({'error': 'no_paper_data'}, status=status.HTTP_400_BAD_REQUEST)

        # Compact index + section list for the planner.
        index, sections = [], []
        for sname, sec in _paper_section_iter(pd):
            sections.append(sname)
            for q in sec['questions']:
                if isinstance(q, dict):
                    index.append({'qnum': q.get('qnum'), 'section': sname,
                                  'type': q.get('type'), 'marks': q.get('marks'),
                                  'snippet': str(q.get('text', ''))[:100]})
        if not index:
            return Response({'error': 'no_questions'}, status=status.HTTP_400_BAD_REQUEST)

        # ── Stage 1: plan operations ────────────────────────────────────────
        plan_sys = (
            "You convert a teacher's instruction into edit operations on an exam paper. You receive "
            "the questions (qnum, section, type, marks, snippet) and the list of section names. "
            'Return ONLY JSON {"operations":[...]}. Each operation is exactly one of:\n'
            '  {"action":"edit","qnum":N,"instruction":"what to change"}\n'
            '  {"action":"replace","qnum":N,"instruction":"spec for a brand-new question"}\n'
            '  {"action":"add","section":"<exact section name>","type":"MCQ|VSA|SA|LA|CBQ","marks":M,"instruction":"topic/spec","position":"end"}\n'
            '  {"action":"move","qnum":N,"to_section":"<exact section name>","position":"end"}\n'
            '  {"action":"delete","qnum":N}\n'
            '  {"action":"swap","qnum_a":N,"qnum_b":M}\n'
            '  {"action":"set","qnum":N,"fields":{"marks":5}}\n'
            '  {"action":"set_section","section":"<exact name>","fields":{"instructions":"..."}}\n'
            "Use qnum values and section names EXACTLY as given. For 'change marks/answer/type' use "
            "set; for content rewrites use edit; for a fresh question use replace (in place) or add "
            "(new). For a section-wide instruction emit one op per affected question. If nothing "
            'applies, return {"operations":[]}. JSON only — no prose.'
        )
        plan_prompt = (f"SECTIONS:\n{_json.dumps(sections, ensure_ascii=False)}\n\n"
                       f"QUESTIONS:\n{_json.dumps(index, ensure_ascii=False)}\n\n"
                       f"INSTRUCTION:\n{instruction}\n\nJSON:")
        try:
            raw, _, _ = mantle_client.converse(
                model_id=mantle_client.GEN_MODEL, prompt=plan_prompt, system_prompt=plan_sys,
                max_tokens=1200, temperature=0.1)
            parsed = _extract_json_blob(raw) or {}
        except Exception as e:
            return Response({'error': f'Could not plan the edit: {e}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        operations = (parsed.get('operations') if isinstance(parsed, dict)
                      else parsed if isinstance(parsed, list) else [])
        if not operations:
            return Response({'error': "Couldn't work out what to change — try naming the question or "
                                      "section, e.g. 'move question 5 to Section B', 'add a 2-mark "
                                      "question on fractions to Section A', or 'change Q3 marks to 5'."},
                            status=status.HTTP_400_BAD_REQUEST)

        # ── Stage 2: content generator (only edit / replace / add call the model) ──
        def _gen(kind, ctx):
            try:
                if kind in ('edit', 'replace'):
                    q = ctx['question']
                    if kind == 'edit':
                        gsys = ("You edit ONE CBSE exam question. Apply the instruction and return ONLY the "
                                "corrected question as a JSON object with the SAME keys. Keep qnum/type/subtype/"
                                "marks unless the instruction requires changing them. MCQ/Assertion-Reason keep "
                                "their 4 options a/b/c/d. JSON only — no prose.")
                        gp = (f"QUESTION JSON:\n{_json.dumps(q, ensure_ascii=False)}\n\n"
                              f"INSTRUCTION:\n{ctx.get('instruction', '')}\n\nCorrected question JSON:")
                        mt = 1500
                    else:
                        gsys = ("You write ONE fresh CBSE exam question to replace an existing one, matching its "
                                "type and marks. Return ONLY a question JSON object using the same schema as the "
                                "original. JSON only — no prose.")
                        gp = (f"ORIGINAL (match its type & marks):\n{_json.dumps(q, ensure_ascii=False)}\n\n"
                              f"NEW QUESTION SPEC:\n{ctx.get('instruction', '')}\n\nNew question JSON:")
                        mt = 1200
                    r, _, _ = mantle_client.converse(model_id=mantle_client.GEN_MODEL, prompt=gp,
                                                     system_prompt=gsys, max_tokens=mt, temperature=0.4)
                    return _extract_json_blob(r)
                if kind == 'add':
                    qtype = ctx.get('type') or 'SA'
                    marks = ctx.get('marks') or 1
                    _instr, skel = _regen_question_skeleton({'type': qtype}, 0, marks)
                    gsys = ("You write ONE new CBSE exam question for the named section, matching the requested "
                            "type and marks. Return ONLY a question JSON object. JSON only — no prose.")
                    gp = (f"SECTION: {ctx.get('section')}\nTYPE: {qtype}\nMARKS: {marks}\n"
                          f"SPEC: {ctx.get('instruction', '')}\n\nReturn JSON shaped exactly like:\n{skel}\n\n"
                          f"New question JSON:")
                    r, _, _ = mantle_client.converse(model_id=mantle_client.GEN_MODEL, prompt=gp,
                                                     system_prompt=gsys, max_tokens=1200, temperature=0.6)
                    return _extract_json_blob(r)
            except Exception:
                return None
            return None

        prev_data = copy.deepcopy(pd)
        new_pd, applied, notes = apply_operations(pd, operations, generate_fn=_gen)
        if not applied:
            tail = (' ' + ' '.join(notes[:3])) if notes else ''
            return Response({'error': 'The edit could not be applied — please rephrase.' + tail},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # We honoured the edit as asked — surface (not block) any resulting pattern mismatch.
        warnings = list(notes)
        try:
            from core.paper_audit import audit_paper_marks, summary_line
            audit = audit_paper_marks(new_pd, paper.pattern)
            if not audit.get('ok'):
                warnings.append("Marks check — " + summary_line(audit))
        except Exception:
            pass

        paper.paper_data = new_pd
        paper.edited_content = None        # JSON is now the source of truth; text re-extracts from the new DOCX
        paper.save(update_fields=['paper_data', 'edited_content', 'updated_at'])
        try:
            file_url = _render_paper_from_stored_data(paper, request)
        except Exception as e:
            import traceback; traceback.print_exc()
            return Response({'error': f'Edit applied but re-render failed: {e}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({'status': 'edited', 'summary': '; '.join(applied),
                         'applied': applied, 'warnings': warnings,
                         'file': file_url, 'prev_data': prev_data})

    @action(detail=True, methods=['post'])
    def restore_data(self, request, pk=None):
        """Restore a previous paper_data snapshot (used by the change-log revert) and re-render."""
        paper = self.get_object()
        if not _can_modify_paper(request.user, paper):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.get('paper_data')
        if not isinstance(data, dict) or not data:
            return Response({'error': 'No paper_data provided'}, status=status.HTTP_400_BAD_REQUEST)
        paper.paper_data = data
        paper.edited_content = None
        paper.save(update_fields=['paper_data', 'edited_content', 'updated_at'])
        try:
            file_url = _render_paper_from_stored_data(paper, request)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({'status': 'restored', 'file': file_url})

    @action(detail=True, methods=['post'])
    def upload_image(self, request, pk=None):
        """Upload an image to embed in the paper. Returns the media URL."""
        paper = self.get_object()
        if not _can_modify_paper(request.user, paper):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

        img = request.FILES.get('image')
        if not img:
            return Response({'error': 'No image file provided'}, status=status.HTTP_400_BAD_REQUEST)

        import os, hashlib
        from django.conf import settings as _s
        ext      = os.path.splitext(img.name)[1].lower() or '.jpg'
        raw      = img.read()
        digest   = hashlib.sha256(raw).hexdigest()[:20]
        filename = f"paper_{paper.id}_{digest}{ext}"
        out_dir  = os.path.join(_s.MEDIA_ROOT, 'paper_images')
        os.makedirs(out_dir, exist_ok=True)
        dest     = os.path.join(out_dir, filename)
        with open(dest, 'wb') as f:
            f.write(raw)
        url = f"{_s.MEDIA_URL}paper_images/{filename}"
        return Response({'url': url, 'marker': f'[Image: {url}]'})

    @action(detail=True, methods=['post'])
    def save_content(self, request, pk=None):
        """Save edited content"""
        paper = self.get_object()
        if not _can_modify_paper(request.user, paper):
            return Response({'error': 'Not authorized to edit this paper'}, status=status.HTTP_403_FORBIDDEN)
        content = request.data.get('content', '')
        
        paper.edited_content = content
        paper.save()
        
        return Response({'status': 'Content saved'})

    @action(detail=True, methods=['post'])
    def regenerate_pdf(self, request, pk=None):
        """Regenerate PDF from edited content"""
        paper = self.get_object()
        if not _can_modify_paper(request.user, paper):
            return Response({'error': 'Not authorized to regenerate this paper'}, status=status.HTTP_403_FORBIDDEN)
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
            
            return Response({'status': 'PDF regenerated successfully', 'file_url': signed_file_url(request, paper.file)})
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _parse_chapter_list(raw):
    """Parse a 'chapters' field that may arrive as a JSON-array string (the upload form sends
    JSON.stringify(selectedChapters)), a single plain string, or a list (repeated form field).
    Returns a de-duplicated, order-preserving list of non-empty chapter names."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        candidates = list(raw)
    else:
        s = str(raw).strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                candidates = parsed if isinstance(parsed, list) else [parsed]
            except Exception:
                candidates = [s]
        else:
            candidates = [s]
    items, seen = [], set()
    for c in candidates:
        name = str(c).strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            items.append(name)
    return items


class MaterialViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Material model.
    Provides CRUD operations for educational materials (textbooks, notes, etc.).
    """
    serializer_class = MaterialSerializer
    pagination_class = LargeResultsSetPagination
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['class_name', 'subject', 'type', 'unit']
    search_fields = ['title', 'subject', 'class_name']

    def get_queryset(self):
        user = self.request.user
        base = Material.objects.all().select_related('uploaded_by', 'school').order_by('-uploaded_at')
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

    def update(self, request, *args, **kwargs):
        """Standard field edits via the serializer, plus chapter re-association for non-textbook
        materials: when a `chapters` field is sent, store it on metadata + unit and — if the set
        changed or the file was replaced — re-ingest the file under the new chapter labels (using
        the provider the material was originally embedded with, so dimensions stay consistent)."""
        response = super().update(request, *args, **kwargs)
        if response.status_code >= 400 or "chapters" not in request.data:
            return response

        instance = self.get_object()
        if instance.type == 'textbook':
            return response

        chapters = _parse_chapter_list(request.data.get("chapters"))
        if not chapters:
            return response

        meta = instance.metadata or {}
        old_chapters = meta.get("chapters") or []
        meta["chapters"] = chapters
        instance.metadata = meta
        instance.unit = chapters[0]
        instance.save(update_fields=["metadata", "unit"])

        if chapters != old_chapters or request.FILES.get("file"):
            sid = instance.school_id
            embeddings.delete_material_embeddings(instance.class_name, instance.subject, instance.id, school_id=sid)
            if instance.file:
                ingest_material_task.apply_async(
                    args=[instance.class_name, instance.subject,
                          [{"unit": chapters[0], "title": instance.title, "file_path": instance.file.path,
                            "material_id": instance.id, "chapters": chapters}],
                          instance.type],
                    kwargs={"provider": meta.get("provider", "local"), "school_id": sid},
                )
        response.data = self.get_serializer(instance).data
        return response

    def perform_destroy(self, instance):
        school_id = instance.school_id
        if instance.type == 'textbook':
            embeddings.delete_unit_embeddings(instance.class_name, instance.subject, instance.unit, school_id=None)
            if school_id:
                embeddings.delete_unit_embeddings(instance.class_name, instance.subject, instance.unit, school_id=school_id)
        elif (instance.metadata or {}).get("chapters"):
            # Chapter-linked material: its chunks share unit labels with the textbook, so delete
            # ONLY this material's chunks (by material_id) — never the textbook chapter's chunks.
            embeddings.delete_material_embeddings(instance.class_name, instance.subject, instance.id, school_id=school_id)
        else:
            embeddings.delete_unit_embeddings(instance.class_name, instance.subject, instance.unit, school_id=school_id)
        instance.delete()

    def create(self, request, *args, **kwargs):
        """Custom create to handle bulk and multi-chapter uploads with embeddings"""
        # Handle standard single file upload via DRF (no bulk/multi-chapter/url fields)
        if ("bulk_upload" not in request.data and "chapter_count" not in request.data
                and "import_url" not in request.data):
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

        # Intelligent-ingest opt-ins (default OFF → behaviour is unchanged unless requested).
        auto_detect_units = str(request.data.get("auto_detect_units")).lower() == "true"
        split_book = str(request.data.get("split_book")).lower() == "true"

        if not all([class_name, subject, material_type]):
            return Response({"error": "Missing required fields: class_name, subject, type"},
                            status=status.HTTP_400_BAD_REQUEST)

        materials_to_ingest = []
        user = request.user if request.user.is_authenticated else None
        school = _get_school(user) if user else None
        school_id = school.id if school else None

        import_url = (request.data.get("import_url") or "").strip()

        try:
            # ── Import a whole-book HTML page by URL → per-chapter units (async) ──
            if import_url:
                if not import_url.lower().startswith(("http://", "https://")):
                    return Response({"error": "import_url must be an http(s) URL"}, status=status.HTTP_400_BAD_REQUEST)
                task = ingest_url_task.apply_async(
                    args=[class_name, subject, import_url, material_type],
                    kwargs={"provider": embedding_provider, "school_id": school_id,
                            "uploaded_by_id": user.id if user else None},
                )
                return Response({
                    "message": f"Importing book from URL and splitting into chapters ({embedding_provider}).",
                    "task_id": task.id, "provider": embedding_provider,
                }, status=status.HTTP_202_ACCEPTED)

            # ── Whole-book split: one PDF → many per-chapter units (async detection) ──
            if split_book:
                book = (request.FILES.getlist("bulk_files") or [None])[0] or request.FILES.get("file_0")
                if not book:
                    return Response({"error": "No file provided to split"}, status=status.HTTP_400_BAD_REQUEST)
                ext = os.path.splitext(book.name)[1].lower()
                if ext not in ALLOWED_MATERIAL_EXTENSIONS:
                    return Response({"error": f"'{book.name}' has an unsupported type. Allowed: PDF, DOCX, DOC, TXT"},
                                    status=status.HTTP_400_BAD_REQUEST)
                base = Material.objects.create(
                    class_name=class_name, subject=subject, unit="(splitting…)",
                    title=os.path.splitext(book.name)[0], type=material_type, file=book,
                    school=school, uploaded_by=user, metadata={"source_book": True},
                )
                task = split_book_task.apply_async(
                    args=[class_name, subject, base.file.path, material_type],
                    kwargs={"provider": embedding_provider, "school_id": school_id,
                            "uploaded_by_id": user.id if user else None, "base_material_id": base.id},
                )
                return Response({
                    "message": f"Uploaded '{book.name}'. Splitting into chapters and ingesting ({embedding_provider}).",
                    "task_id": task.id, "provider": embedding_provider,
                }, status=status.HTTP_202_ACCEPTED)

            # Handle bulk upload
            if bulk_upload:
                files = request.FILES.getlist("bulk_files")
                if not files:
                    return Response({"error": "No files provided for bulk upload"}, status=status.HTTP_400_BAD_REQUEST)

                # Non-textbook materials (notes / bank / syllabus / reference) must declare which
                # chapter(s) they relate to — the whole batch shares the same selection.
                batch_chapters = _parse_chapter_list(request.data.get("chapters"))
                if material_type != "textbook" and not batch_chapters:
                    return Response(
                        {"error": "Select at least one chapter this material relates to."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                for file in files:
                    if not file:
                        continue
                    ext = os.path.splitext(file.name)[1].lower()
                    if ext not in ALLOWED_MATERIAL_EXTENSIONS:
                        return Response(
                            {"error": f"'{file.name}' has an unsupported type. Allowed: PDF, DOCX, DOC, TXT"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    filename = file.name
                    base_name = os.path.splitext(filename)[0]
                    if material_type == 'textbook':
                        unit = base_name
                    else:
                        unit = batch_chapters[0]  # representative chapter for listings/get_chapters

                    material = Material.objects.create(
                        class_name=class_name,
                        subject=subject,
                        unit=unit,
                        title=base_name,
                        type=material_type,
                        file=file,
                        school=school,
                        uploaded_by=user,
                        metadata={"chapters": batch_chapters, "provider": embedding_provider} if material_type != 'textbook' else {},
                    )
                    materials_to_ingest.append({
                        "unit": material.unit,
                        "title": material.title,
                        "file_path": material.file.path,
                        "material_id": material.id,
                        "chapters": batch_chapters if material_type != 'textbook' else None,
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
                    # Non-textbook files declare their own related chapter(s) via chapters_{i}.
                    chapters_i = _parse_chapter_list(request.data.get(f"chapters_{i}"))

                    if not file:
                        continue
                    ext = os.path.splitext(file.name)[1].lower()
                    if ext not in ALLOWED_MATERIAL_EXTENSIONS:
                        return Response(
                            {"error": f"'{file.name}' has an unsupported type. Allowed: PDF, DOCX, DOC, TXT"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    if material_type != "textbook":
                        if not chapters_i:
                            return Response(
                                {"error": f"File {i + 1}: select at least one chapter it relates to."},
                                status=status.HTTP_400_BAD_REQUEST,
                            )
                        unit = chapters_i[0]
                        title = title or chapters_i[0]

                    material = Material.objects.create(
                        class_name=class_name,
                        subject=subject,
                        unit=unit,
                        title=title,
                        type=material_type,
                        file=file,
                        school=school,
                        uploaded_by=user,
                        metadata={"chapters": chapters_i, "provider": embedding_provider} if material_type != 'textbook' else {},
                    )
                    materials_to_ingest.append({
                        "unit": unit,
                        "title": title,
                        "file_path": material.file.path,
                        "material_id": material.id,
                        "chapters": chapters_i if material_type != 'textbook' else None,
                    })

            # Queue embedding ingestion via Celery
            if materials_to_ingest:
                task = ingest_material_task.apply_async(args=[class_name, subject, materials_to_ingest, material_type], kwargs={'provider': embedding_provider, 'school_id': school_id, 'auto_name': auto_detect_units})
                return Response({
                    "message": f"Uploaded {len(materials_to_ingest)} material(s). Embedding ingestion queued ({embedding_provider}{', auto-naming chapters' if auto_detect_units else ''}).",
                    "count": len(materials_to_ingest),
                    "task_id": task.id,
                    "provider": embedding_provider,
                }, status=status.HTTP_202_ACCEPTED)

            return Response({"error": "No files were successfully processed"}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({"error": f"Upload failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='preview-url')
    def preview_url(self, request):
        """Fetch an HTML book URL and return its detected chapters (names + sizes) WITHOUT
        ingesting — powers the live preview shown when a URL is pasted on the upload page."""
        from core import material_intel
        url = (request.data.get('url') or '').strip()
        subject = request.data.get('subject') or ''
        if not url.lower().startswith(('http://', 'https://')):
            return Response({'error': 'Enter a valid http(s) URL'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            html = material_intel.fetch_url(url, timeout=25)
        except Exception as e:
            return Response({'error': f'Could not fetch that URL: {str(e)[:160]}'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            chapters = material_intel.extract_html_chapters(html, subject)
        except Exception as e:
            return Response({'error': f'Could not parse that page: {str(e)[:160]}'}, status=status.HTTP_400_BAD_REQUEST)
        out = [{'unit': c.get('unit') or '(unnamed)', 'chars': len(c.get('text') or '')} for c in chapters]
        return Response({'count': len(out), 'chapters': out, 'bytes': len(html)})

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
    permission_classes = [IsAuthenticated]
    filterset_fields = ['subject', 'class_name', 'is_default']
    search_fields = ['name', 'subject']

    def get_queryset(self):
        # Hierarchical: shared (default/superadmin) templates visible to all; school_admin also
        # sees their school's, a teacher only their own. (IDOR + own-only scoping.)
        return _scoped_blueprint_templates(self.request.user).order_by('subject', 'class_name')

    def perform_create(self, serializer):
        """Set the created_by field to the current user"""
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def defaults(self, request):
        """Get default templates for each subject/class combination"""
        defaults = self.get_queryset().filter(is_default=True)
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
    permission_classes = [IsAuthenticated]
    filterset_fields = ['class_name', 'subject']
    search_fields = ['subject', 'class_name', 'code']

    def get_queryset(self):
        # Hierarchical: superadmin → all, school_admin → school, teacher → own. (IDOR + own-only.)
        return _scoped_blueprints(self.request.user).order_by('class_name', 'subject')

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
@permission_classes([IsAuthenticated])
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
@permission_classes([IsAuthenticated])
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
@permission_classes([IsAuthenticated])
def get_blueprints(request):
    """API version of blueprint lookup"""
    try:
        class_name = request.GET.get("class_name", "").strip()
        subject = request.GET.get("subject", "").strip()
        
        if not class_name or not subject:
            return Response({"blueprints": []})
            
        class_num = class_name.split("-")[0]
        
        # 1. Standard Blueprint Templates (school-scoped)
        templates = _scoped_blueprint_templates(request.user).filter(
            class_name=class_num,
            subject__iexact=subject,
        ).values('id', 'name', 'created_at')
        
        template_list = []
        for t in templates:
            template_list.append({
                'id': f"template_{t['id']}",
                'name': f"[Template] {t['name']}",
                'source': 'template',
                'created_at': t['created_at']
            })

        # 2. AI-generated Blueprints (school-scoped)
        blueprints = _scoped_blueprints(request.user).filter(
            class_name=class_num,
            subject__iexact=subject,
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
@permission_classes([IsAuthenticated])
def get_blueprint_details(request, blueprint_id):
    """API version of blueprint details lookup"""
    try:
        if blueprint_id.startswith("exam_"):
            bp_id = blueprint_id.replace("exam_", "")
            blueprint = _scoped_blueprints(request.user).get(id=bp_id)
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
            template = _scoped_blueprint_templates(request.user).get(id=tp_id)
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
