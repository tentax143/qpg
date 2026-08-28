from rest_framework import viewsets, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.utils import timezone
from core.models import ExamPattern, QuestionPaper, Material, BlueprintTemplate, ExamBlueprint, Subject, Issue
from core import embeddings
from core.tasks import (ingest_material_task, split_book_task, ingest_url_task,
                        dispatch_paper, dispatch_next_queued_paper)
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
    IssueSerializer,
)
from .permissions import IsSuperAdmin

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


def _can_modify_material(user, material):
    """A material may be edited/deleted only by a superadmin, or by a member of the school that
    OWNS it. This stops one school from mutating another school's shared/institutional material
    (which is now visible to it for retrieval) or the superadmin's global shared store."""
    if _user_role(user) == 'superadmin' or getattr(user, 'is_superuser', False):
        return True
    school = _get_school(user)
    return school is not None and material.school_id == school.id


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


class IssueViewSet(viewsets.ModelViewSet):
    """User issue reports. Any authenticated user can create an issue and list/read their
    OWN issues; superadmin sees every issue (filterable by ?status=) and is the only role
    allowed to change status / add a note / delete."""
    serializer_class = IssueSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = LargeResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['status']
    search_fields = ['title', 'description']

    def get_permissions(self):
        # Only superadmin may edit status/note or delete; anyone authenticated may create/read.
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsSuperAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = Issue.objects.select_related('created_by', 'school').all()
        if _user_role(self.request.user) == 'superadmin' or self.request.user.is_superuser:
            return qs
        # Regular users only ever see the issues they reported.
        return qs.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        # Force safe defaults regardless of request body: a reporter can never set status
        # or an admin note. Only title + description come from the user.
        serializer.save(
            created_by=self.request.user,
            school=_get_school(self.request.user),
            status=Issue.STATUS_OPEN,
            admin_note='',
        )


def _budget_blocked(user):
    """Hard guard before queuing a paper-generation task: the school token budget (0 = unlimited).
    Returns an error string if generation must be refused, else None. Concurrency is NOT handled
    here any more — a second concurrent request is *queued* (see _has_active_generation), not refused,
    so the user sees a 'queued' paper instead of an error."""
    school = _get_school(user)
    if school and school.monthly_token_budget and school.total_tokens_used >= school.monthly_token_budget:
        return (f"Your school has reached its token budget "
                f"({school.total_tokens_used:,}/{school.monthly_token_budget:,} tokens). "
                "Contact your administrator to raise it.")
    return None


def _billing_blocked(user):
    """Hard guard on every AI-generation action: when the superadmin has marked the user's
    school's billing period as over, return a refusal Response (402 — deliberately NOT 403,
    which the frontend interceptor treats as an auth failure and logs the user out), else None."""
    school = _get_school(user)
    if school and school.billing_period_over:
        return Response(
            {'error': 'The billing period of your school is over. Please contact the admin.',
             'billing_over': True},
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )
    return None


def _has_active_generation(user, exclude_id=None):
    """True if the user already has a paper occupying (or about to occupy) a Celery worker: status
    'generating', or 'queued' with a task_id already dispatched. A 'queued' paper WITHOUT a task_id is
    only *waiting in line* and does NOT count. When this is True a new request is left waiting (shown
    as 'queued') rather than dispatched; the per-user serial queue promotes it when the active one ends.
    `exclude_id` skips the paper being retried/regenerated so it doesn't see itself as active."""
    from django.db.models import Q
    from core.tasks import reap_stale_papers
    reap_stale_papers(user.id)   # a dead generation must not hold the slot forever
    qs = QuestionPaper.objects.filter(created_by=user).filter(
        Q(status='generating') | (Q(status='queued') & ~(Q(task_id__isnull=True) | Q(task_id='')))
    )
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    return qs.exists()


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
        cache_only=True, generate_missing_images=True,
        # Reuse cached images first; if an image-backed question has no cached diagram yet,
        # generate it now so re-rendered papers do not silently drop visuals.
    )
    if os.path.exists(os.path.join(_dj.MEDIA_ROOT, file_path)):
        paper.file.name = file_path        # assign directly — file.save() renames on collision → 404
    # Persist paper_data too: the renderer stamps every question with its PRINTED number
    # (blueprint section order, questions regrouped by type) by mutating the question dicts
    # shared with paper.paper_data. paper_edit.renumber() numbers in STORAGE order instead,
    # which diverges from the printed order after any edit — without saving the renderer's
    # numbering, the next "change question N" resolves N against stale qnums and edits a
    # different question than the one the teacher reads in the DOCX.
    paper.save(update_fields=['file', 'paper_data', 'updated_at'])
    return signed_file_url(request, paper.file)


def _sync_answer_key_staleness(paper):
    """Return the paper's AnswerKey (or None), flipping a finished key to 'stale' when the
    paper's content changed since the key was generated. Lazy — runs on every answer-key
    read, so it covers ALL edit paths (ai_edit / restore / rerender / whole-paper
    regenerate) without needing a hook at each paper_data write site."""
    from core.models import AnswerKey
    key = AnswerKey.objects.filter(paper=paper).first()
    if key and key.status == 'done':
        from core.answer_key_generator import paper_revision_hash
        if paper_revision_hash(paper.paper_data) != key.source_revision_hash:
            key.status = 'stale'
            key.save(update_fields=['status', 'updated_at'])
    return key


def _answer_key_payload(key):
    """Status JSON the frontend polls. 'none' means no key has been requested yet."""
    if key is None:
        return {'status': 'none'}
    data = key.data or {}
    return {
        'status': key.status,
        'error_detail': key.error_detail or '',
        'generated_questions': data.get('generated_questions'),
        'failed_questions': len(data.get('errors') or []),
        'cost': str(key.cost) if key.cost is not None else None,
        'updated_at': key.updated_at.isoformat() if key.updated_at else None,
    }


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

    # Sources whose rows are premade, clone-only templates rather than somebody's work.
    _PREMADE_SOURCES = ('cbse_official', 'cbse_sqp', 'one_mark_test')

    def get_queryset(self):
        """Every pattern is VISIBLE to every school, regardless of who created it.

        Patterns are structure — sections, question counts, marks — not exam content (papers stay
        private to their creator). Sharing them across schools makes a good structure reusable
        instead of rebuilt, and it removes a whole class of disappearance: visibility used to be
        derived by joining through the creator's profile to their school, so deleting a teacher
        NULLed `created_by`, broke the chain, and silently hid every pattern they had built from
        everyone.

        Visible is not the same as editable — `_owned_queryset` governs writes, so another
        school's pattern is read-only and can be cloned but never edited or deleted.

        Premade templates stay out of this list: they are reached through the `templates` action
        and would otherwise bury a school's own handful of patterns under ~70 CBSE rows.
        """
        base = ExamPattern.objects.select_related('created_by__profile__school')
        if self._is_superadmin(self.request.user):
            return base.all().order_by('-created_at')

        # Hiding the premade rows is a LIST concern — it keeps ~70 CBSE templates from burying a
        # school's own handful. Applied to a DETAIL route it 404s them instead, which is how the
        # blueprint builder came to be unable to load the sample paper it was asked to plan (and
        # /pattern/<id> to 404 on a pattern the generate page had just offered). Writes stay
        # governed by `_assert_owned`, which refuses these outright, so reading one is safe.
        if getattr(self, 'detail', False):
            return base.all().order_by('-created_at')

        excluded = list(self._PREMADE_SOURCES)
        # ?include_official=1 — the generate page asks for the official CBSE sample papers so a
        # teacher can set a paper straight from one. Opt-in rather than default: the Exam Patterns
        # management page is the school's OWN work, and folding ~18 read-only official rows into
        # it would change what that page is for. The seeded `cbse_official` aggregates stay out
        # either way — those are 58 rows nobody picks directly.
        if str(self.request.query_params.get('include_official', '')).lower() in ('1', 'true', 'yes'):
            excluded.remove('cbse_sqp')

        return base.exclude(pattern_source__in=excluded).order_by('-created_at')

    def _owned_queryset(self, user):
        """Patterns this user may EDIT or DELETE — their school's own work.

        Deliberately still keyed on the creator's school: that is the only ownership signal the
        model has. It means an orphaned pattern (creator deleted) is editable by nobody but a
        superadmin, which is the safe direction — it stays visible and clonable, it just cannot be
        changed or removed by a school that never made it.
        """
        if self._is_superadmin(user):
            return ExamPattern.objects.all()
        school = _get_school(user)
        if school:
            return ExamPattern.objects.filter(created_by__profile__school=school)
        return ExamPattern.objects.filter(created_by=user)

    def _assert_owned(self, instance, user):
        """Raise PermissionDenied unless `user` may modify `instance`."""
        from rest_framework.exceptions import PermissionDenied
        if instance.pattern_source in self._GLOBAL_SOURCES and not self._is_superadmin(user):
            raise PermissionDenied(
                "Shared official patterns can only be changed by a superadmin.")
        if not self._owned_queryset(user).filter(pk=instance.pk).exists():
            raise PermissionDenied(
                "This pattern belongs to another school. You can view it or clone it into your "
                "own patterns, but not edit or delete it.")

    def retrieve(self, request, *args, **kwargs):
        """The create-pattern page polls this endpoint every 3s while a pattern generates.
        Reap the caller's stale patterns first: a pattern whose Celery task evaporated in a
        worker/broker restart used to stay 'queued' forever and the page spun forever with
        no error — the "AI pattern is just loading" report. Reaping here means the very poll
        that would have spun forever is the one that resolves it to 'failed'."""
        from core.tasks import reap_stale_patterns
        reap_stale_patterns(user_id=request.user.id)
        return super().retrieve(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        """Slot-authored sections (question_slots): whenever sections are updated
        (e.g. by the per-question editor), re-normalize the slots, refresh the
        structure warnings, and re-derive the legacy aggregates so counts/marks/
        question_types can never drift from the edited slots."""
        # Patterns are visible school-wide AND cross-school; only the owning school may change
        # one. Without this, widening visibility would have handed every school an edit button on
        # everyone else's work.
        self._assert_owned(serializer.instance, self.request.user)

        sections = serializer.validated_data.get('sections')
        if isinstance(sections, list) and any(
                isinstance(s, dict) and s.get('question_slots') for s in sections):
            from core import pattern_structure
            pattern_structure.normalize_slots(sections)
            for s in sections:
                if isinstance(s, dict):
                    s.pop('_structure_warnings', None)
            # Derive BEFORE validating: on the editor path the edited slots are the
            # source of truth and the incoming section marks are merely the stale
            # pre-edit aggregates — flagging that mismatch would be a false warning.
            # (The generation task validates first, because there the section marks
            # come from the teacher's text and a mismatch IS a real conflict.)
            pattern_structure.derive_aggregates_from_slots(sections)
            for e in pattern_structure.validate_pattern_structure(sections):
                idx = e.get('section')
                target = (sections[idx] if idx is not None and 0 <= idx < len(sections)
                          else (sections[0] if sections else None))
                if isinstance(target, dict):
                    target.setdefault('_structure_warnings', []).append(e['msg'])
        serializer.save()

    @staticmethod
    def _template_queryset():
        """Premade patterns — the clone source, matched by SOURCE only.

        It used to also match `created_by__isnull=True`, which meant any pattern whose creator was
        deleted was silently promoted into the official template pool and offered to every other
        school. Source is the honest signal: these rows are premade because of what they are, not
        because of who does or does not own them.
        """
        return ExamPattern.objects.filter(
            pattern_source__in=['cbse_official', 'cbse_sqp', 'one_mark_test'])

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
        et = (exam_type or '').strip().lower()

        # The SQP-derived board patterns are reusable STRUCTURES — neither class- nor
        # subject-specific. A CBSE sample paper's shape (16 one-markers, 5 two-markers, 7
        # three-markers, 2 case studies, 3 long answers) is the same board-paper skeleton whatever
        # subject or class you sit it for, and only ten subjects have an SQP at all. Filtering them
        # by class meant a Class 10 Biology teacher saw nothing, because the Biology SQP happens to
        # be the Class 12 paper. clone_template already takes `class_name` and `subject` overrides,
        # so the clone lands in the teacher's own class and subject — this only makes them visible.
        #
        # Everything else (cbse_official seeds, one_mark_test, other superadmin templates) keeps
        # the class+subject narrowing: those ARE specific to what they were built for.
        sqp_pool = qs.filter(pattern_source='cbse_sqp')
        others = qs.exclude(pattern_source='cbse_sqp')
        if class_name:
            others = others.filter(class_name__iexact=class_name)

        # A board-shaped paper is only a sensible suggestion for a board-shaped exam. Offering an
        # 80-mark board structure for a 20-mark PT-1 is worse than offering nothing — the front end
        # then falls back to its 20-mark periodic-test default, which is what that teacher wants.
        sqp_allowed = exam_type is None or et in self._BOARD_EXAM_TYPES

        cross = []
        sqp_first = []
        if subject:
            narrowed = others.filter(subject__iexact=subject)
            if not narrowed.exists():
                narrowed = others.filter(subject__icontains=subject)
            results = list(narrowed.order_by('-created_at'))

            if sqp_allowed:
                # The subject's OWN sample paper is the most faithful structure available, so it
                # leads — and is not flagged cross-subject, because it isn't.
                #
                # Matched by FAMILY and ranked by BAND, not by string equality: a Class 6 teacher
                # picks "English", the paper is "English Language & Literature", and there is a
                # second English paper for 11-12. Plain `subject__iexact` matched neither, so the
                # caller (which takes the first result) was handed an unrelated subject entirely.
                from core.subjects import same_subject
                family = [p for p in sqp_pool if same_subject(p.subject, subject)]
                family.sort(key=lambda p: (
                    not p.serves_class(class_name),   # papers covering this class first
                    p.subject,
                ))
                sqp_first = family
                seen = {p.id for p in family} | {p.id for p in results}
                cross = [p for p in sqp_pool.order_by('subject') if p.id not in seen]
                # Same rule for the rest: an official paper that covers the chosen class is a
                # better suggestion than one from the other stage.
                cross.sort(key=lambda p: (not p.serves_class(class_name), p.subject))
        else:
            results = list(others.order_by('-created_at'))
            if sqp_allowed:
                results += sorted(sqp_pool, key=lambda p: (not p.serves_class(class_name), p.subject))

        # Soft exam_type narrowing by name; keep the broader set if nothing name-matches.
        # Applied to the school/seeded patterns ONLY. The official sample papers are named
        # "CBSE Sample Paper — X", so a `board` request name-matched the seeded "CBSE Board X
        # Class 6" row and this filter then DISCARDED the very sample paper the caller wanted —
        # `templates` is read first-result-first by the create-pattern page.
        if exam_type:
            hit = [p for p in results if et in (p.name or '').lower()]
            if hit:
                results = hit
        results = sqp_first + results

        data = ExamPatternSerializer(results, many=True).data
        for row in data:
            row['is_cross_subject'] = False
        cross_data = ExamPatternSerializer(cross, many=True).data
        for row in cross_data:
            # The UI labels these "structure from <subject> — reusable" so a teacher understands
            # why a Physics pattern is on their Sociology list.
            row['is_cross_subject'] = True
        # Own-subject first: a teacher whose subject HAS an SQP must never have to hunt for it.
        return Response(data + cross_data)

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

    # Exam types for which a cross-subject BOARD pattern is a sensible suggestion. A 20-mark
    # PT-1 request must not be offered an 80-mark board paper from another subject.
    _BOARD_EXAM_TYPES = ('board', 'half_yearly', 'pre_board', 'annual', '')

    # Global/system templates shared across all schools — only a superadmin may delete these.
    _GLOBAL_SOURCES = ('cbse_official', 'cbse_sqp', 'one_mark_test')

    def _is_superadmin(self, user):
        return _user_role(user) == 'superadmin' or user.is_superuser

    def destroy(self, request, *args, **kwargs):
        """Only the owning school (or a superadmin) may delete a pattern.

        Every school can now SEE every pattern, so visibility is no longer a delete boundary —
        this check is what stops one school removing another's work.
        """
        instance = self.get_object()
        try:
            self._assert_owned(instance, request.user)
        except Exception as exc:
            return Response({"error": str(getattr(exc, 'detail', exc))},
                            status=status.HTTP_403_FORBIDDEN)
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

        # NOT get_queryset(): that now spans every school, so using it as the boundary would
        # make this a cross-school delete. Ownership is the boundary for writes.
        visible = self._owned_queryset(request.user).filter(id__in=ids)

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

        billing = _billing_blocked(request.user)
        if billing:
            return billing

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

    @action(detail=False, methods=['post'], url_path='import-from-pdf',
            parser_classes=[MultiPartParser, FormParser])
    def import_from_pdf(self, request):
        """Create a pattern from an uploaded sample-paper PDF (e.g. a CBSE SQP): extract
        the PDF's text here (so scanned PDFs fail fast with a clear error), then queue
        the LLM schema extraction as a Celery task. Returns 202 with the pattern id —
        same polling contract as generate_from_ai."""
        from core.tasks import generate_pattern_task
        from core.material_intel import extract_pages_text
        from api.ai_service import SQP_MAX_CHARS

        billing = _billing_blocked(request.user)
        if billing:
            return billing

        upload = request.FILES.get('file')
        class_name   = request.data.get('class_name', '')
        subject      = request.data.get('subject', '')
        pattern_name = request.data.get('name', '')

        if not upload:
            return Response({"error": "Upload a PDF file in the 'file' field."},
                            status=status.HTTP_400_BAD_REQUEST)
        if os.path.splitext(upload.name or '')[1].lower() != '.pdf':
            return Response({"error": "Only PDF files are supported for pattern import."},
                            status=status.HTTP_400_BAD_REQUEST)
        if upload.size > 25 * 1024 * 1024:
            return Response({"error": "PDF too large (max 25 MB)."},
                            status=status.HTTP_400_BAD_REQUEST)

        # extract_pages_text needs a filesystem path — stage the upload in a temp file.
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                for chunk in upload.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            sqp_text = extract_pages_text(tmp_path, max_chars=SQP_MAX_CHARS)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        if len((sqp_text or '').strip()) < 200:
            return Response(
                {"error": "No readable text found in this PDF — it looks like a scanned or "
                          "image-based paper. Upload a text-based PDF."},
                status=status.HTTP_400_BAD_REQUEST)

        pattern = ExamPattern.objects.create(
            name=pattern_name or f"Imported Pattern — {subject} {class_name}".strip(),
            description=f"Structure extracted from uploaded paper: {upload.name}",
            subject=subject,
            class_name=class_name,
            sections=[],
            total_marks=0,
            total_questions=0,
            pattern_source='imported',
            ai_prompt=sqp_text,   # generate_pattern_task reads the SQP text from here
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

    @action(detail=True, methods=['get'], url_path='blueprint-scaffold')
    def blueprint_scaffold(self, request, pk=None):
        """Everything the blueprint builder needs for this pattern, in ONE request.

        Returns each section with its PRINTED questions (number, type label, marks, choice) plus
        the units that have uploaded material for the class+subject — so the builder can render a
        unit dropdown per question without N round trips.

        `section_id` is computed exactly as `section_generator.build_work_orders` computes it
        (explicit `id`, else derived from the name), because that is the key `apply_unit_map`
        matches on at generation time. Deriving it differently here would produce blueprints that
        save fine and then quietly fail to apply.
        """
        from core import pattern_structure
        from core.section_generator import _section_id_from_name

        # NOT self.get_object(): that runs the filter backends over the queryset first, and this
        # endpoint's own `class_name`/`subject` params are also filterset fields on ExamPattern.
        # Asking for "this pattern, planned for Class 6 Science" therefore filtered the pattern
        # itself down to class_name=6 and 404'd every sample paper (whose own class is 10 or 12).
        pattern = get_object_or_404(self.get_queryset(), pk=pk)
        subject = request.query_params.get('subject') or pattern.subject
        class_name = request.query_params.get('class_name') or pattern.class_name

        sections = []
        for idx, sec in enumerate(pattern.sections or []):
            if not isinstance(sec, dict):
                continue
            name = sec.get('name') or f'Section {chr(65 + idx)}'
            section_id = sec.get('id') or _section_id_from_name(name, idx)
            slots = pattern_structure.slots_for_section(sec)

            questions = []
            for slot in slots:
                qnum = slot.get('qnum')
                if not isinstance(qnum, int) or qnum <= 0:
                    continue
                stype = str(slot.get('type') or '')
                questions.append({
                    'qnum': qnum,
                    'type': stype,
                    'type_label': pattern_structure.SLOT_TYPE_LABEL.get(stype, stype or 'Question'),
                    'marks': slot.get('marks'),
                    'topic': slot.get('topic') or '',
                    'choice': slot.get('choice') or 'none',
                    # An unseen-passage or general-knowledge question is deliberately NOT drawn
                    # from a chapter, so pinning a unit to it would contradict the pattern.
                    'unit_applicable': str(slot.get('source') or '') not in ('unseen', 'general'),
                })

            sections.append({
                'section_id': section_id,
                'name': name,
                'marks': sec.get('marks'),
                'questions': questions,
                # Legacy aggregate-only sections print no individual question numbers, so they
                # can only be planned as a whole.
                'section_level_only': not questions,
                'questions_count': sec.get('questions_count') or len(questions),
            })

        return Response({
            'pattern': {
                'id': pattern.id, 'name': pattern.name, 'subject': pattern.subject,
                'class_name': pattern.class_name, 'total_marks': pattern.total_marks,
                'total_questions': pattern.total_questions,
            },
            'sections': sections,
            'units': available_units(request.user, class_name, subject),
        })

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

        billing = _billing_blocked(request.user)
        if billing:
            return billing

        pattern = self.get_object()
        try:
            self._assert_owned(pattern, request.user)   # regeneration overwrites the pattern
        except Exception as exc:
            return Response({"error": str(getattr(exc, 'detail', exc))},
                            status=status.HTTP_403_FORBIDDEN)
        if pattern.pattern_source not in ('ai_generated', 'imported'):
            return Response({"error": "Only AI-generated or PDF-imported patterns can be regenerated"}, status=status.HTTP_400_BAD_REQUEST)

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

    @action(detail=False, methods=['post'], url_path='regenerate-all')
    def regenerate_all(self, request):
        """Re-queue AI generation for every AI-generated pattern in the caller's scope
        (or only the given `ids`), each from its own EXISTING prompt. Skips manual /
        official patterns (nothing to re-run), promptless ones, and ones already
        queued/generating. Returns 202 with per-bucket counts."""
        from django.db.models import Q
        from core.tasks import generate_pattern_task

        billing = _billing_blocked(request.user)
        if billing:
            return billing

        # NOT get_queryset(): that now spans every school. Regeneration blanks a pattern's
        # sections and re-runs the LLM over it, so it is a write and belongs to the owner only.
        qs = self._owned_queryset(request.user)
        ids = request.data.get('ids')
        if ids is not None:
            if not isinstance(ids, list) or not ids:
                return Response({"error": "'ids' must be a non-empty list."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                qs = qs.filter(id__in=[int(i) for i in ids])
            except (TypeError, ValueError):
                return Response({"error": "'ids' must be a list of integers."}, status=status.HTTP_400_BAD_REQUEST)

        skipped_not_ai = list(qs.exclude(pattern_source='ai_generated').values_list('id', flat=True))
        ai_qs = qs.filter(pattern_source='ai_generated')
        skipped_no_prompt = list(ai_qs.filter(Q(ai_prompt__isnull=True) | Q(ai_prompt=''))
                                 .values_list('id', flat=True))
        skipped_active = list(ai_qs.filter(status__in=['queued', 'generating'])
                              .values_list('id', flat=True))

        queued_ids = []
        for pattern in ai_qs.exclude(id__in=skipped_no_prompt + skipped_active):
            pattern.status = 'queued'
            pattern.sections = []
            pattern.save(update_fields=['status', 'sections'])
            task = generate_pattern_task.delay(pattern.id)
            pattern.task_id = task.id
            pattern.save(update_fields=['task_id'])
            queued_ids.append(pattern.id)

        return Response({
            'queued': len(queued_ids),
            'queued_ids': queued_ids,
            'skipped_not_ai': skipped_not_ai,        # manual/official — no prompt to re-run
            'skipped_no_prompt': skipped_no_prompt,  # AI-generated but prompt text is missing
            'skipped_active': skipped_active,        # already queued or generating
        }, status=status.HTTP_202_ACCEPTED)


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
        # answer_key joined so serializing answer_key_status doesn't N+1 the list.
        queryset = _owner_scope(
            QuestionPaper.objects.select_related('answer_key').order_by('-created_at'), user)
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
            billing = _billing_blocked(request.user)
            if billing:
                return billing

            # Budget guard — refuse before creating the paper or queuing work. (Concurrency is no
            # longer refused: a second request is queued behind the active one — see below.)
            blocked = _budget_blocked(request.user)
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
            # Source mix: percent of questions written from the model's own knowledge
            # rather than the book. Absent / unparseable keeps the all-from-the-book default.
            try:
                creative_ratio = max(0, min(100, int(float(data.get("creative_ratio", 0) or 0))))
            except (TypeError, ValueError):
                creative_ratio = 0

            paper = QuestionPaper.objects.create(
                class_name=class_name,
                subject=subject,
                pattern_id=pattern_id,
                chapters=chapters_list,
                difficulty=data.get("difficulty", "Medium"),
                creative_ratio=creative_ratio,
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
                "creative_ratio": creative_ratio,
            }
            additional_context_json = json.dumps(meta_payload)

            # Persist the task kwargs so this paper can be dispatched later if it has to wait.
            paper.gen_params = {
                'blueprint_id': blueprint_id,
                'model_source': model_source,
                'additional_context': additional_context_json,
            }
            paper.save(update_fields=['gen_params'])

            # Per-user serial queue: run now only if nothing else is active for this user; otherwise
            # leave it 'queued' (waiting) — dispatch_next_queued_paper promotes it when the current
            # generation finishes. Either way the paper already exists with status 'queued'.
            if not _has_active_generation(request.user, exclude_id=paper.id):
                dispatch_paper(paper)

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

    def destroy(self, request, *args, **kwargs):
        """Deleting a queued/generating paper must behave like a cancel first: revoke its
        Celery task and free the owner's serial slot by promoting their next waiting
        paper. Without this, deleting an active paper left its slot occupied forever and
        every later paper sat 'queued' with no task (production defect, 2026-07-16)."""
        paper = self.get_object()
        owner_id = paper.created_by_id
        was_active = paper.status in ('queued', 'generating')
        task_id = paper.task_id

        response = super().destroy(request, *args, **kwargs)

        if was_active:
            if task_id:
                try:
                    from celery import current_app
                    current_app.control.revoke(task_id, terminate=True, signal='SIGTERM')
                except Exception as _e:
                    print(f"[Delete] revoke failed for task {task_id}: {_e}")
            try:
                dispatch_next_queued_paper(owner_id)
            except Exception as _dq:
                print(f"[Delete] dispatch_next_queued failed: {_dq}")
        return response

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
            # Free the user's slot: promote their next waiting paper, if any.
            try:
                dispatch_next_queued_paper(paper.created_by_id)
            except Exception as _dq:
                print(f"[Cancel] dispatch_next_queued failed: {_dq}")
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
                billing = _billing_blocked(request.user)
                if billing:
                    return billing
                blocked = _budget_blocked(request.user)
                if blocked:
                    return Response({'error': blocked}, status=status.HTTP_429_TOO_MANY_REQUESTS)
                # Reset to a clean waiting state (no task_id) — retry reuses the paper's stored
                # gen_params so it re-runs with its original blueprint / model / context.
                paper.status = "queued"
                paper.status_detail = ""
                paper.task_id = None
                paper.save()

                # Per-user serial queue: dispatch now only if nothing else is active for this user,
                # else leave it waiting to be promoted when the current generation finishes.
                if _has_active_generation(request.user, exclude_id=paper.id):
                    return Response({'status': 'Queued', 'queued': True})
                task = dispatch_paper(paper)
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
        billing = _billing_blocked(request.user)
        if billing:
            return billing
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

        # Source mix: re-uses the paper's stored setting unless this request overrides it.
        try:
            creative_ratio = max(0, min(100, int(float(
                request.data.get('creative_ratio', paper.creative_ratio) or 0))))
        except (TypeError, ValueError):
            creative_ratio = paper.creative_ratio or 0

        meta_payload = {
            "class_name": paper.class_name,
            "duration": str(request.data.get('duration', '') or '').strip(),
            "marks": str(paper.pattern.total_marks or ''),
            "test_type": paper.pattern.name or '',
            "extra_context": '',
            "num_one_mark_questions": num_one_mark,
            "school_name": school_name,
            "creative_ratio": creative_ratio,
        }

        blocked = _budget_blocked(request.user)
        if blocked:
            return Response({'error': blocked}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Re-queue. Keep the current file/paper_data until the new one is ready (so the paper
        # stays viewable if generation fails); drop any AI-edited text overlay. Clear task_id so it
        # is a clean waiting state, and stash the task kwargs for the queue to dispatch later.
        paper.status = 'queued'
        paper.edited_content = None
        paper.task_id = None
        paper.creative_ratio = creative_ratio
        paper.gen_params = {
            'model_source': request.session.get('model_choice', 'aws'),
            'additional_context': _json.dumps(meta_payload),
        }
        paper.save(update_fields=['status', 'edited_content', 'task_id', 'creative_ratio',
                                  'gen_params', 'updated_at'])

        # Per-user serial queue: dispatch now only if nothing else is active for this user, else
        # leave it waiting to be promoted when the current generation finishes.
        if _has_active_generation(request.user, exclude_id=paper.id):
            return Response({'status': 'Queued', 'queued': True})
        task = dispatch_paper(paper)
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
                cache_only=True, generate_missing_images=True,
                # Reuse cached images first; generate missing question images on demand.
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
        billing = _billing_blocked(request.user)
        if billing:
            return billing

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
        billing = _billing_blocked(request.user)
        if billing:
            return billing
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

    # ── Answer key (teacher copy, rendered to DOCX on demand) ────────────────

    @action(detail=True, methods=['get', 'post'])
    def answer_key(self, request, pk=None):
        """GET → answer-key status (lazily flips 'done' → 'stale' when the paper changed).
        POST → queue (re)generation. One LLM call per question, so it always runs in Celery."""
        paper = self.get_object()
        key = _sync_answer_key_staleness(paper)
        if request.method == 'GET':
            return Response(_answer_key_payload(key))

        if not _can_modify_paper(request.user, paper):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        billing = _billing_blocked(request.user)
        if billing:
            return billing
        if paper.status != 'done':
            return Response({'error': 'The paper is still generating — try again once it is done.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(paper.paper_data, dict) or not paper.paper_data:
            return Response({'error': 'no_paper_data'}, status=status.HTTP_400_BAD_REQUEST)
        if key and key.status in ('queued', 'generating'):
            # Already in flight — idempotent: report the current state instead of double-queuing.
            return Response(_answer_key_payload(key))

        from core.models import AnswerKey
        from core.tasks import generate_answer_key_task
        if key is None:
            key = AnswerKey.objects.create(paper=paper, requested_by=request.user)
        else:
            key.status = 'queued'
            key.requested_by = request.user
            key.error_detail = ''
            key.task_id = None
            key.save(update_fields=['status', 'requested_by', 'error_detail', 'task_id', 'updated_at'])
        task = generate_answer_key_task.delay(key.id)
        key.task_id = task.id
        key.save(update_fields=['task_id'])
        return Response(_answer_key_payload(key), status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'])
    def answer_key_docx(self, request, pk=None):
        """Render and stream the answer-key DOCX from the stored JSON. A stale key still
        downloads (the status endpoint carries the badge) — the teacher decides."""
        from django.http import FileResponse
        paper = self.get_object()
        key = _sync_answer_key_staleness(paper)
        if key is None or key.status not in ('done', 'stale') or not key.data:
            return Response({'error': 'No generated answer key for this paper yet.'},
                            status=status.HTTP_404_NOT_FOUND)
        school_name = ''
        try:
            s = paper.created_by.profile.school
            school_name = (s.name or '') if s else ''
        except Exception:
            pass
        from core.answer_key_docx import render_answer_key_docx
        buffer = render_answer_key_docx(paper, key.data, school_name=school_name)
        response = FileResponse(
            buffer, as_attachment=True, filename=f"answer_key_{paper.id}.docx",
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Access-Control-Allow-Origin'] = '*'
        return response

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
            from core.access import visibility_q
            return base.filter(visibility_q(school))   # own ∪ shared(if granted) ∪ institutional
        return base.filter(uploaded_by=user)

    def create(self, request, *args, **kwargs):
        # Uploads queue embedding/enrichment work, so they count as generation for billing.
        billing = _billing_blocked(request.user)
        if billing:
            return billing
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        # Superadmin uploads populate the global shared store (school=None, visibility=shared);
        # a school's uploads are private to that school by default.
        user = self.request.user
        if _user_role(user) == 'superadmin' or user.is_superuser:
            serializer.save(uploaded_by=user, school=None, visibility='shared')
        else:
            serializer.save(uploaded_by=user, school=_get_school(user), visibility='private')

    def update(self, request, *args, **kwargs):
        """Standard field edits via the serializer, plus chapter re-association for non-textbook
        materials: when a `chapters` field is sent, store it on metadata + unit and — if the set
        changed or the file was replaced — re-ingest the file under the new chapter labels (using
        the provider the material was originally embedded with, so dimensions stay consistent)."""
        if not _can_modify_material(request.user, self.get_object()):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only edit materials your school owns.")
        # Only the superadmin manages the global shared store; a school may flip its own material
        # between 'private' and 'institutional' (cross-school) but not promote it to 'shared'.
        if request.data.get("visibility") == "shared" and not (
                _user_role(request.user) == 'superadmin' or request.user.is_superuser):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only a superadmin can mark a material as globally shared.")
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
        if not _can_modify_material(self.request.user, instance):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only delete materials your school owns.")
        # MaterialChunk has FK(Material, on_delete=CASCADE), so deleting the row removes its
        # embeddings precisely — no unit-based deletion (which could hit other materials).
        instance.delete()

    def create(self, request, *args, **kwargs):
        """Custom create to handle bulk and multi-chapter uploads with embeddings"""
        # Handle standard single file upload via DRF (no bulk/multi-chapter/url/split fields)
        if ("bulk_upload" not in request.data and "chapter_count" not in request.data
                and "import_url" not in request.data and "split_book" not in request.data):
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
        # Superadmin uploads build the global shared store (school=None, visibility=shared);
        # everyone else's uploads are private to their own school.
        is_superadmin = bool(user) and (_user_role(user) == 'superadmin' or user.is_superuser)
        if is_superadmin:
            school = None
            visibility = 'shared'
        else:
            school = _get_school(user) if user else None
            visibility = 'private'
        school_id = school.id if school else None

        # Optional named vector store (superadmin only): the material becomes part of that store —
        # visibility "store", seen ONLY by schools the store is allocated to (core.access.visibility_q).
        vector_store = None
        vs_id = request.data.get("vector_store_id") or None
        if vs_id and is_superadmin:
            from core.models import VectorStore
            vector_store = VectorStore.objects.filter(id=vs_id).first()
            if not vector_store:
                return Response({"error": "Selected vector store not found"}, status=status.HTTP_400_BAD_REQUEST)
            visibility = 'store'
        vector_store_id = vector_store.id if vector_store else None

        import_url = (request.data.get("import_url") or "").strip()

        try:
            # ── Import a whole-book HTML page by URL → per-chapter units (async) ──
            if import_url:
                if not import_url.lower().startswith(("http://", "https://")):
                    return Response({"error": "import_url must be an http(s) URL"}, status=status.HTTP_400_BAD_REQUEST)
                task = ingest_url_task.apply_async(
                    args=[class_name, subject, import_url, material_type],
                    kwargs={"provider": embedding_provider, "school_id": school_id,
                            "uploaded_by_id": user.id if user else None,
                            "vector_store_id": vector_store_id},
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
                    school=school, visibility=visibility, vector_store=vector_store,
                    uploaded_by=user, metadata={"source_book": True},
                )
                task = split_book_task.apply_async(
                    args=[class_name, subject, base.file.path, material_type],
                    kwargs={"provider": embedding_provider, "school_id": school_id,
                            "uploaded_by_id": user.id if user else None, "base_material_id": base.id,
                            "vector_store_id": vector_store_id},
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
                        visibility=visibility,
                        vector_store=vector_store,
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
                        visibility=visibility,
                        vector_store=vector_store,
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

    @action(detail=False, methods=['post'], url_path='preview-names')
    def preview_names(self, request):
        """Detect each uploaded PDF's chapter/lesson name from its CONTENT (no DB writes, no
        ingestion) so the bulk-upload UI can show the names for review before the user commits.
        Returns names in the SAME ORDER the files were sent, so the client aligns them by index."""
        from core import material_intel
        import tempfile
        from concurrent.futures import ThreadPoolExecutor

        class_name = request.data.get('class_name') or ''
        subject = request.data.get('subject') or ''
        files = request.FILES.getlist('files')
        if not files:
            return Response({'error': 'No files provided'}, status=status.HTTP_400_BAD_REQUEST)
        if len(files) > 50:
            return Response({'error': 'Detect at most 50 files at a time'}, status=status.HTTP_400_BAD_REQUEST)

        def _detect(f):
            base = os.path.splitext(f.name)[0]
            ext = os.path.splitext(f.name)[1].lower() or '.pdf'
            name = None
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            try:
                for chunk in f.chunks():
                    tmp.write(chunk)
                tmp.close()
                name = material_intel.detect_unit_name(tmp.name, class_name, subject)
            except Exception as e:
                print(f"[preview_names] '{f.name}' detection failed: {e}")
            finally:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
            return {'filename': f.name, 'name': name or base, 'detected': bool(name)}

        # Parallel — detection is one small LLM call per file; keep the request snappy.
        with ThreadPoolExecutor(max_workers=4) as ex:
            names = list(ex.map(_detect, files))
        return Response({'names': names, 'count': len(names)})

    @action(detail=False, methods=['post'], url_path='preview-split')
    def preview_split(self, request):
        """For each uploaded PDF, detect its sub-chapters (lessons) via detect_book_chapters so the
        bulk-upload UI can preview how a whole-unit PDF will split before committing (no DB writes).
        Returns per-file chapter-name lists in the SAME ORDER the files were sent."""
        from core import material_intel
        import tempfile
        from concurrent.futures import ThreadPoolExecutor

        class_name = request.data.get('class_name') or ''
        subject = request.data.get('subject') or ''
        files = request.FILES.getlist('files')
        if not files:
            return Response({'error': 'No files provided'}, status=status.HTTP_400_BAD_REQUEST)
        if len(files) > 50:
            return Response({'error': 'Detect at most 50 files at a time'}, status=status.HTTP_400_BAD_REQUEST)

        # Scope the BookContents (TOC) lookup: superadmin → global (None), others → their school.
        _u = request.user
        _toc_school_id = None
        if not (_user_role(_u) == 'superadmin' or getattr(_u, 'is_superuser', False)):
            _sch = _get_school(_u)
            _toc_school_id = _sch.id if _sch else None

        def _split(f):
            base = os.path.splitext(f.name)[0]
            ext = os.path.splitext(f.name)[1].lower() or '.pdf'
            chapters = []
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            try:
                for chunk in f.chunks():
                    tmp.write(chunk)
                tmp.close()
                # refine_names=False → no LLM for the title-font path (names are the printed titles).
                detected = material_intel.detect_book_chapters(tmp.name, class_name, subject,
                                                               refine_names=False, school_id=_toc_school_id)
                chapters = [c.get('unit') for c in detected if c.get('unit')]
                if not chapters:
                    nm = material_intel.detect_unit_name(tmp.name, class_name, subject)
                    chapters = [nm or base]
            except Exception as e:
                print(f"[preview_split] '{f.name}' failed: {e}")
                chapters = [base]
            finally:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
            return {'filename': f.name, 'chapters': chapters, 'count': len(chapters), 'split': len(chapters) > 1}

        # Parallel, but conservatively — detect_book_chapters parses the whole PDF (pdfminer).
        with ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(_split, files))
        return Response({'files': results, 'count': len(results)})

    @action(detail=False, methods=['get', 'post'], url_path='book-contents')
    def book_contents(self, request):
        """The book's parsed table-of-contents (BookContents), used to split per-unit PDFs at exact
        offsets with official lesson titles.
        GET  ?class_name=&subject=  → the stored TOC (or {exists:false}).
        POST (multipart: file, class_name, subject) → parse the prelims/contents PDF & store it.
        Superadmin's TOC is global (school=None); others' are scoped to their school."""
        from core import material_intel
        from core.models import BookContents
        import tempfile

        user = request.user
        is_superadmin = _user_role(user) == 'superadmin' or getattr(user, 'is_superuser', False)
        school = None if is_superadmin else _get_school(user)
        school_id = school.id if school else None

        def _payload(tc):
            return {'exists': True, 'title': tc.title, 'units': tc.units,
                    'unit_count': len(tc.units or []),
                    'lesson_count': sum(len(u.get('lessons', [])) for u in (tc.units or []))}

        if request.method == 'GET':
            cls = request.query_params.get('class_name') or ''
            subj = request.query_params.get('subject') or ''
            qs = BookContents.objects.filter(class_name=cls, subject__iexact=subj)
            tc = (qs.filter(school_id=school_id).first() if school_id else None) or qs.filter(school__isnull=True).first()
            return Response(_payload(tc) if tc else {'exists': False})

        # POST — parse the contents PDF and (re)store it.
        cls = request.data.get('class_name') or ''
        subj = request.data.get('subject') or ''
        f = request.FILES.get('file') or (request.FILES.getlist('files') or [None])[0]
        if not (cls and subj and f):
            return Response({'error': 'class_name, subject and a contents PDF are required'},
                            status=status.HTTP_400_BAD_REQUEST)
        ext = os.path.splitext(f.name)[1].lower() or '.pdf'
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        try:
            for chunk in f.chunks():
                tmp.write(chunk)
            tmp.close()
            parsed = material_intel.parse_book_contents(tmp.name)
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
        units = parsed.get('units') or []
        if not units:
            return Response({'error': 'No table-of-contents could be parsed from this PDF'},
                            status=status.HTTP_400_BAD_REQUEST)
        BookContents.objects.filter(class_name=cls, subject__iexact=subj, school=school).delete()
        tc = BookContents.objects.create(
            class_name=cls, subject=subj, school=school, title=parsed.get('title', '') or '',
            units=units, created_by=user if user.is_authenticated else None,
        )
        return Response(_payload(tc))

    @action(detail=False, methods=['post'], url_path='bulk-delete')
    def bulk_delete(self, request):
        ids = request.data.get('ids', [])
        if not ids:
            return Response({'error': 'No IDs provided'}, status=status.HTTP_400_BAD_REQUEST)
        qs = self.get_queryset().filter(id__in=ids).select_related('school')
        # Only delete materials the caller owns (own school) or, for superadmin, anything —
        # the visible queryset now includes shared/other-school materials it must not delete.
        deletable_ids = [m.id for m in qs if _can_modify_material(request.user, m)]
        if not deletable_ids:
            return Response({'error': 'No deletable materials found'}, status=status.HTTP_404_NOT_FOUND)

        # MaterialChunk has FK(Material, on_delete=CASCADE), so deleting the rows removes their
        # embeddings precisely (no unit-based deletion that could hit other materials).
        Material.objects.filter(id__in=deletable_ids).delete()
        return Response({'message': f'Deleted {len(deletable_ids)} material(s)'})


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
    # `pattern` so the blueprints page can list a pattern's plans without client-side filtering.
    filterset_fields = ['class_name', 'subject', 'pattern']
    search_fields = ['subject', 'class_name', 'code', 'name']

    def get_queryset(self):
        # Hierarchical: superadmin → all, school_admin → school, teacher → own. (IDOR + own-only.)
        return _scoped_blueprints(self.request.user).order_by('class_name', 'subject')

    def perform_create(self, serializer):
        """Set the created_by field to the current user"""
        serializer.save(created_by=self.request.user)
    def perform_destroy(self, instance):
        """Deactivate rather than drop the row.

        Every read path already filters `is_active=True` (`_scoped_blueprints`, `get_blueprints`,
        `core.tasks._resolve_blueprint`), so the blueprint disappears from the lists, the generate
        form and generation itself — the delete is complete as far as the teacher is concerned.
        What it is not is irreversible: a unit plan can be forty hand-picked questions, and one
        mis-click should not destroy it beyond recovery.
        """
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])

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

    role = _user_role(request.user) if request.user.is_authenticated else None
    school = _get_school(request.user) if request.user.is_authenticated else None
    if role == 'superadmin' or getattr(request.user, 'is_superuser', False):
        qs = base_qs                                  # superadmin sees everything
    else:
        from core.access import visibility_q
        qs = base_qs.filter(visibility_q(school))     # own ∪ shared(if granted) ∪ institutional

    subjects = qs.values_list("subject", flat=True).distinct().order_by("subject")

    allowed = _allowed_subject(request.user) if request.user.is_authenticated else None
    if allowed:
        subjects = [s for s in list(subjects) if s.lower() == allowed.lower()]
        return Response({"subjects": subjects})

    return Response({"subjects": list(subjects)})


def available_units(user, class_name, subject):
    """Units (chapters) with uploaded material for this class+subject, visible to `user`.

    Shared by `get_chapters` and the blueprint scaffold: both offer the teacher a list of units
    to choose from and must offer exactly the same list, scoped by the same visibility rules. A
    second copy of this query drifting out of sync would let a teacher pin a blueprint to a unit
    they cannot actually see material for.
    """
    class_name = (class_name or "").strip()
    subject = (subject or "").strip()
    if not class_name or not subject:
        return []

    class_num = class_name.split("-")[0]
    base_qs = Material.objects.filter(class_name__istartswith=class_num, subject__iexact=subject)

    role = _user_role(user) if getattr(user, 'is_authenticated', False) else None
    school = _get_school(user) if getattr(user, 'is_authenticated', False) else None
    if role == 'superadmin' or getattr(user, 'is_superuser', False):
        qs = base_qs                                  # superadmin sees everything
    else:
        from core.access import visibility_q
        qs = base_qs.filter(visibility_q(school))     # own ∪ shared(if granted) ∪ institutional

    return list(qs.values_list("unit", flat=True).distinct().order_by("unit"))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_chapters(request):
    """Return chapters available to the requesting user's school."""
    class_name = request.GET.get("class_name", "").strip()
    subject = request.GET.get("subject", "").strip()

    if not class_name or not subject:
        return Response({"chapters": []})

    return Response({"chapters": available_units(request.user, class_name, subject)})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_blueprints(request):
    """Blueprints the generate form may attach, for a class+subject and optionally a pattern.

    Only real per-pattern unit plans are offered. Two things are deliberately NOT listed:

      * BlueprintTemplates ("template_<id>"). They described a paper structure, which is an
        ExamPattern's job; `core.tasks._resolve_blueprint` ignores that form outright, so listing
        them would offer the teacher a choice that silently does nothing.
      * Blueprints whose unit map is empty. Same reason — attaching one changes no question.

    When `pattern` is supplied the list is restricted to that pattern's blueprints. A blueprint
    addresses its pattern's printed question numbers, so attaching one built for a different
    pattern would map units onto the wrong questions; the task rejects that, and the form should
    never present it in the first place.
    """
    try:
        class_name = request.GET.get("class_name", "").strip()
        subject = request.GET.get("subject", "").strip()
        pattern_id = (request.GET.get("pattern") or "").strip()

        if not pattern_id.isdigit() and (not class_name or not subject):
            return Response({"blueprints": []})

        qs = _scoped_blueprints(request.user).select_related('pattern')
        if pattern_id.isdigit():
            qs = qs.filter(pattern_id=int(pattern_id))
        if class_name:
            qs = qs.filter(class_name=class_name.split("-")[0])

        from core.subjects import same_subject

        out = []
        for bp in qs.order_by('-created_at'):
            # Subject matched by FAMILY, not string equality. The blueprint records the subject
            # whose material its units came from ("English"), while the paper may be set from the
            # sample paper for "English Language & Literature" — the same subject under the name
            # CBSE prints on the paper. An exact match dropped the blueprint from this list.
            if subject and not same_subject(bp.subject, subject):
                continue
            mapped = sum(len(per_q) for per_q in bp.question_units().values())
            section_wide = len(bp.section_units())
            if not mapped and not section_wide:
                continue        # nothing pinned — attaching it would be a no-op
            detail = []
            if mapped:
                detail.append(f"{mapped} question{'' if mapped == 1 else 's'}")
            if section_wide:
                detail.append(f"{section_wide} section{'' if section_wide == 1 else 's'}")
            out.append({
                'id': f"exam_{bp.id}",
                'name': (bp.name or f"Blueprint #{bp.id}") + f" ({', '.join(detail)} pinned)",
                'source': 'unit_plan',
                'pattern_id': bp.pattern_id,
                'pattern_name': bp.pattern.name if bp.pattern else '',
                'units': bp.all_units(),
                'created_at': bp.created_at,
            })

        return Response({"blueprints": out})
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
