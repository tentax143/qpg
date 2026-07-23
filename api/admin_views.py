from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.db.models import Sum
from django.utils import timezone
from core.models import School, UserProfile, QuestionPaper
from .permissions import IsSuperAdmin, IsSchoolAdminOrAbove
from .auth_serializers import UserSerializer, CreateUserSerializer
from .serializers import QuestionPaperListSerializer


# ── helpers ──────────────────────────────────────────────────────────────────

def _school_to_dict(school, include_stats=False):
    d = {
        'id': school.id,
        'name': school.name,
        'address': school.address,
        'phone': school.phone,
        'email': school.email,
        'monthly_token_budget': school.monthly_token_budget,
        'is_active': school.is_active,
        'billing_period_over': school.billing_period_over,
        'access_shared_vector_store': school.access_shared_vector_store,
        'created_at': school.created_at,
        'updated_at': school.updated_at,
    }
    if include_stats:
        d.update({
            'member_count': school.members.count(),
            # Cumulative — persists even after papers are deleted
            'paper_count': school.total_papers_generated,
            'images_generated': school.total_images_generated,
            'total_cost': str(school.total_cost_accumulated),
        })
    return d


def _check_school_access(request, school):
    """Returns error Response if the requester cannot access this school, else None."""
    try:
        profile = request.user.profile
        if profile.role == 'school_admin' and profile.school_id != school.id:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    except Exception:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    return None


# ── superadmin dashboard ──────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsSuperAdmin])
def superadmin_dashboard(request):
    schools = School.objects.filter(is_active=True)
    agg = QuestionPaper.objects.aggregate(
        total_input=Sum('input_tokens'),
        total_output=Sum('output_tokens'),
        total_cost=Sum('cost'),
    )
    school_rows = []
    for s in schools:
        school_rows.append({
            'id': s.id,
            'name': s.name,
            'member_count': s.members.count(),
            # Cumulative — persists even after papers are deleted
            'paper_count': s.total_papers_generated,
            'images_generated': s.total_images_generated,
            'total_tokens': s.total_tokens_used,
            'total_cost': str(s.total_cost_accumulated),
            'monthly_token_budget': s.monthly_token_budget,
            'is_active': s.is_active,
        })
    return Response({
        'total_schools': schools.count(),
        'total_users': User.objects.count(),
        'total_papers': QuestionPaper.objects.count(),
        'total_tokens': (agg['total_input'] or 0) + (agg['total_output'] or 0),
        'total_cost': str(agg['total_cost'] or 0),
        'schools': school_rows,
    })


# ── school CRUD ───────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsSuperAdmin])
def schools_list(request):
    if request.method == 'GET':
        schools = School.objects.all()
        return Response([_school_to_dict(s, include_stats=True) for s in schools])

    name = request.data.get('name', '').strip()
    if not name:
        return Response({'error': 'name is required'}, status=status.HTTP_400_BAD_REQUEST)
    access_shared = bool(request.data.get('access_shared_vector_store', False))
    school = School.objects.create(
        name=name,
        address=request.data.get('address', ''),
        phone=request.data.get('phone', ''),
        email=request.data.get('email', ''),
        monthly_token_budget=int(request.data.get('monthly_token_budget', 0)),
        is_active=request.data.get('is_active', True),
        access_shared_vector_store=access_shared,
    )
    # Kick off vector store copy if shared access is granted at creation time
    if access_shared:
        from core.tasks import copy_shared_vectorstore_task
        copy_shared_vectorstore_task.delay(school.id)
    return Response(_school_to_dict(school), status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsSuperAdmin])
def school_detail(request, pk):
    try:
        school = School.objects.get(pk=pk)
    except School.DoesNotExist:
        return Response({'error': 'School not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(_school_to_dict(school, include_stats=True))

    if request.method == 'DELETE':
        school.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    prev_shared = school.access_shared_vector_store
    for field in ('name', 'address', 'phone', 'email', 'monthly_token_budget', 'is_active',
                  'billing_period_over', 'access_shared_vector_store'):
        if field in request.data:
            val = request.data[field]
            if field == 'monthly_token_budget':
                val = int(val)
            elif field in ('is_active', 'billing_period_over', 'access_shared_vector_store'):
                val = bool(val)
            setattr(school, field, val)
    school.save()
    # If shared access was just enabled, trigger the copy task
    if not prev_shared and school.access_shared_vector_store:
        from core.tasks import copy_shared_vectorstore_task
        copy_shared_vectorstore_task.delay(school.id)
    return Response(_school_to_dict(school))


# ── school users ──────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsSchoolAdminOrAbove])
def school_users(request, pk):
    try:
        school = School.objects.get(pk=pk)
    except School.DoesNotExist:
        return Response({'error': 'School not found'}, status=status.HTTP_404_NOT_FOUND)

    err = _check_school_access(request, school)
    if err:
        return err

    if request.method == 'GET':
        users = User.objects.filter(profile__school=school).select_related('profile')
        return Response(UserSerializer(users, many=True).data)

    serializer = CreateUserSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.save()
    role = request.data.get('role', 'teacher')
    # school_admin can only create teachers; superadmin can create school_admin too
    try:
        requester_role = request.user.profile.role
    except Exception:
        requester_role = None
    if requester_role != 'superadmin' and role == 'superadmin':
        role = 'teacher'
    if role not in ('superadmin', 'school_admin', 'teacher'):
        role = 'teacher'

    profile = user.profile
    profile.school = school
    profile.role = role
    profile.require_password_change = True
    profile.allowed_subject = request.data.get('allowed_subject', '') or None
    profile.save()

    return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@api_view(['DELETE', 'PATCH'])
@permission_classes([IsSchoolAdminOrAbove])
def school_user_remove(request, pk, user_id):
    try:
        school = School.objects.get(pk=pk)
    except School.DoesNotExist:
        return Response({'error': 'School not found'}, status=status.HTTP_404_NOT_FOUND)

    err = _check_school_access(request, school)
    if err:
        return err

    try:
        profile = UserProfile.objects.get(user_id=user_id, school=school)
    except UserProfile.DoesNotExist:
        return Response({'error': 'User not found in this school'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'PATCH':
        new_role = request.data.get('role')
        allowed_roles = [UserProfile.ROLE_SCHOOL_ADMIN, UserProfile.ROLE_TEACHER]
        if new_role not in allowed_roles:
            return Response({'error': f'role must be one of {allowed_roles}'}, status=status.HTTP_400_BAD_REQUEST)
        profile.role = new_role
        profile.save(update_fields=['role'])
        return Response({
            'id': profile.user_id,
            'role': profile.role,
        })

    if profile.user_id == request.user.id:
        return Response({'error': 'Cannot remove yourself'}, status=status.HTTP_400_BAD_REQUEST)

    profile.user.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── school usage stats ────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsSchoolAdminOrAbove])
def school_usage(request, pk):
    try:
        school = School.objects.get(pk=pk)
    except School.DoesNotExist:
        return Response({'error': 'School not found'}, status=status.HTTP_404_NOT_FOUND)

    err = _check_school_access(request, school)
    if err:
        return err

    papers_qs = QuestionPaper.objects.filter(created_by__profile__school=school)

    # Monthly stats — from live paper records (for budget tracking)
    now = timezone.now()
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_qs = papers_qs.filter(created_at__gte=first_of_month)
    m_agg = monthly_qs.aggregate(
        monthly_cost=Sum('cost'),
        monthly_input=Sum('input_tokens'),
        monthly_output=Sum('output_tokens'),
    )
    monthly_tokens = (m_agg['monthly_input'] or 0) + (m_agg['monthly_output'] or 0)
    budget = school.monthly_token_budget

    return Response({
        'school': school.name,
        # All-time totals — cumulative, persists after paper deletion
        'total_papers': school.total_papers_generated,
        'done_papers': school.total_papers_generated,
        'total_images': school.total_images_generated,
        'total_input_tokens': 0,
        'total_output_tokens': 0,
        'total_tokens': school.total_tokens_used,
        'total_cost': str(school.total_cost_accumulated),
        # Monthly — from live records
        'monthly_tokens': monthly_tokens,
        'monthly_cost': str(m_agg['monthly_cost'] or 0),
        'monthly_token_budget': budget,
        'budget_used_pct': round(monthly_tokens / budget * 100, 1) if budget else None,
    })


# ── school activity (papers list) ─────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsSchoolAdminOrAbove])
def school_papers(request, pk):
    try:
        school = School.objects.get(pk=pk)
    except School.DoesNotExist:
        return Response({'error': 'School not found'}, status=status.HTTP_404_NOT_FOUND)

    err = _check_school_access(request, school)
    if err:
        return err

    papers = QuestionPaper.objects.filter(
        created_by__profile__school=school
    ).select_related('created_by').order_by('-created_at')[:100]
    rows = QuestionPaperListSerializer(
        papers,
        many=True,
        context={'request': request},
    ).data
    for row, paper in zip(rows, papers):
        row['created_by'] = paper.created_by.username if paper.created_by else None
    return Response(rows)


# ── per-user usage within a school ───────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsSchoolAdminOrAbove])
def school_user_usage(request, pk):
    try:
        school = School.objects.get(pk=pk)
    except School.DoesNotExist:
        return Response({'error': 'School not found'}, status=status.HTTP_404_NOT_FOUND)

    err = _check_school_access(request, school)
    if err:
        return err

    from django.db.models import Sum, Count
    from django.utils import timezone
    from core.models import UsageEvent

    users = User.objects.filter(profile__school=school).select_related('profile')
    now = timezone.now()
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    rows = []
    for u in users:
        # Aggregate the persistent usage log (survives paper deletion), not live papers, so a
        # teacher's tokens/cost don't reset when they delete a paper. 'total_papers' counts
        # generation events — consistent with the school's persistent total_papers_generated.
        events = UsageEvent.objects.filter(user=u)
        agg = events.aggregate(
            n=Count('id'),
            total_input=Sum('input_tokens'),
            total_output=Sum('output_tokens'),
            total_cost=Sum('cost'),
        )
        monthly = events.filter(created_at__gte=first_of_month).aggregate(
            monthly_input=Sum('input_tokens'),
            monthly_output=Sum('output_tokens'),
            monthly_cost=Sum('cost'),
        )
        # Papers the user currently owns (separate from all-time generated count above).
        live_papers = QuestionPaper.objects.filter(created_by=u).count()
        rows.append({
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'role': getattr(u.profile, 'role', 'teacher'),
            'allowed_subject': getattr(u.profile, 'allowed_subject', None),
            'total_papers': agg['n'] or 0,
            'current_papers': live_papers,
            'total_tokens': (agg['total_input'] or 0) + (agg['total_output'] or 0),
            'total_cost': str(agg['total_cost'] or 0),
            'monthly_tokens': (monthly['monthly_input'] or 0) + (monthly['monthly_output'] or 0),
            'monthly_cost': str(monthly['monthly_cost'] or 0),
        })

    rows.sort(key=lambda r: r['total_tokens'], reverse=True)
    return Response({'users': rows, 'school': school.name})


# ── resync shared vector store ────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsSuperAdmin])
def school_resync_vectorstore(request, pk):
    try:
        school = School.objects.get(pk=pk)
    except School.DoesNotExist:
        return Response({'error': 'School not found'}, status=status.HTTP_404_NOT_FOUND)

    if not school.access_shared_vector_store:
        return Response({'error': 'School does not have shared vector store access'}, status=status.HTTP_400_BAD_REQUEST)

    from core.tasks import copy_shared_vectorstore_task
    task = copy_shared_vectorstore_task.delay(school.id)
    return Response({'message': 'Re-sync started', 'task_id': task.id})


@api_view(['GET', 'POST'])
@permission_classes([IsSuperAdmin])
def school_vector_links(request, pk):
    """Cross-school vector-store links for a school (viewer = this school).

    GET  → {links:[{source_id, source_name, mutual}], linkable:[{id,name}]}
    POST → body {source_id, mutual?}: grant this school read access to source's materials;
           `mutual` also grants the reciprocal. Scope-based — instant, nothing copied."""
    try:
        school = School.objects.get(pk=pk)
    except School.DoesNotExist:
        return Response({'error': 'School not found'}, status=status.HTTP_404_NOT_FOUND)
    from core.models import SchoolVectorLink

    if request.method == 'GET':
        out_ids = set(SchoolVectorLink.objects.filter(viewer=school).values_list('source_id', flat=True))
        in_ids = set(SchoolVectorLink.objects.filter(source=school).values_list('viewer_id', flat=True))
        names = {s.id: s.name for s in School.objects.filter(id__in=out_ids)}
        links = sorted(
            [{'source_id': sid, 'source_name': names.get(sid, '?'), 'mutual': sid in in_ids} for sid in out_ids],
            key=lambda x: x['source_name'].lower(),
        )
        linkable = [{'id': s.id, 'name': s.name} for s in School.objects.exclude(id=school.id).order_by('name')]
        return Response({'links': links, 'linkable': linkable})

    # POST — add a link
    source = School.objects.filter(pk=request.data.get('source_id')).first()
    if not source:
        return Response({'error': 'Source school not found'}, status=status.HTTP_404_NOT_FOUND)
    if source.id == school.id:
        return Response({'error': 'A school cannot link to itself'}, status=status.HTTP_400_BAD_REQUEST)
    mutual = bool(request.data.get('mutual', False))
    SchoolVectorLink.objects.get_or_create(viewer=school, source=source, defaults={'created_by': request.user})
    if mutual:
        SchoolVectorLink.objects.get_or_create(viewer=source, source=school, defaults={'created_by': request.user})
    return Response(
        {'message': f'{school.name} can now read {source.name}' + (' (mutual)' if mutual else '')},
        status=status.HTTP_201_CREATED,
    )


@api_view(['DELETE'])
@permission_classes([IsSuperAdmin])
def school_vector_link_remove(request, pk, source_id):
    """Remove the viewer(pk) → source link. ?mutual=1 also removes the reciprocal link."""
    from core.models import SchoolVectorLink
    SchoolVectorLink.objects.filter(viewer_id=pk, source_id=source_id).delete()
    if request.GET.get('mutual') in ('1', 'true', 'True'):
        SchoolVectorLink.objects.filter(viewer_id=source_id, source_id=pk).delete()
    return Response({'message': 'Link removed'})


@api_view(['GET', 'POST'])
@permission_classes([IsSuperAdmin])
def school_vector_stores(request, pk):
    """Named vector stores allocated to a school (the other side of the M2M managed on the
    Vector Stores page).
    GET  → {allocated:[{id,name}], allocatable:[{id,name}]}
    POST {store_id} → allocate that store to this school (scope-based, instant)."""
    from core.models import VectorStore
    try:
        school = School.objects.get(pk=pk)
    except School.DoesNotExist:
        return Response({'error': 'School not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        allocated_ids = set(school.vector_stores.values_list('id', flat=True))
        allocated = [{'id': s.id, 'name': s.name, 'material_count': s.materials.count()}
                     for s in school.vector_stores.all().order_by('name')]
        allocatable = [{'id': s.id, 'name': s.name}
                       for s in VectorStore.objects.exclude(id__in=allocated_ids).order_by('name')]
        return Response({'allocated': allocated, 'allocatable': allocatable})

    store = VectorStore.objects.filter(pk=request.data.get('store_id')).first()
    if not store:
        return Response({'error': 'Vector store not found'}, status=status.HTTP_404_NOT_FOUND)
    store.schools.add(school)
    return Response({'message': f'{store.name} allocated to {school.name}'}, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsSuperAdmin])
def school_vector_store_remove(request, pk, store_id):
    """Remove a named vector store's allocation to this school."""
    from core.models import VectorStore
    school = School.objects.filter(pk=pk).first()
    store = VectorStore.objects.filter(pk=store_id).first()
    if school and store:
        store.schools.remove(school)
    return Response({'message': 'Allocation removed'})


# ── named vector stores (superadmin-managed shared corpora) ───────────────────

def _store_content_tree(vs):
    """What's uploaded into this store, grouped class → subject → units (chapters).
    [{class_name, material_count, subjects: [{subject, material_count, units: [...]}]}]"""
    from collections import defaultdict
    units = defaultdict(lambda: defaultdict(list))   # class → subject → [unit names]
    counts = defaultdict(lambda: defaultdict(int))
    for m in vs.materials.all().values('class_name', 'subject', 'unit'):
        c = (m['class_name'] or '—').strip() or '—'
        s = (m['subject'] or '—').strip() or '—'
        u = (m['unit'] or '').strip()
        counts[c][s] += 1
        if u and u not in units[c][s]:
            units[c][s].append(u)
    out = []
    for c in sorted(units, key=lambda x: (len(x), x)):   # "8","9","10" sort sensibly-ish
        subjects = [{'subject': s, 'material_count': counts[c][s], 'units': sorted(units[c][s])}
                    for s in sorted(units[c])]
        out.append({'class_name': c, 'material_count': sum(counts[c].values()), 'subjects': subjects})
    return out


def _vector_store_to_dict(vs, include_detail=False):
    d = {
        'id': vs.id,
        'name': vs.name,
        'description': vs.description,
        'material_count': vs.materials.count(),
        'school_count': vs.schools.count(),
        'created_at': vs.created_at,
        'updated_at': vs.updated_at,
    }
    if include_detail:
        d['schools'] = [{'id': s.id, 'name': s.name}
                        for s in vs.schools.all().order_by('name')]
        d['allocatable'] = [{'id': s.id, 'name': s.name}
                            for s in School.objects.exclude(id__in=vs.schools.values_list('id', flat=True)).order_by('name')]
        d['content'] = _store_content_tree(vs)
    return d


@api_view(['GET', 'POST'])
@permission_classes([IsSuperAdmin])
def vector_stores_list(request):
    """GET → list every vector store (with material/school counts).
    POST {name, description?, school_ids?} → create a store, optionally allocated to schools."""
    from core.models import VectorStore
    if request.method == 'GET':
        stores = VectorStore.objects.all().order_by('name')
        return Response([_vector_store_to_dict(vs) for vs in stores])

    name = (request.data.get('name') or '').strip()
    if not name:
        return Response({'error': 'name is required'}, status=status.HTTP_400_BAD_REQUEST)
    if VectorStore.objects.filter(name__iexact=name).exists():
        return Response({'error': 'A vector store with this name already exists'}, status=status.HTTP_400_BAD_REQUEST)
    vs = VectorStore.objects.create(
        name=name,
        description=request.data.get('description', '') or '',
        created_by=request.user,
    )
    school_ids = request.data.get('school_ids') or []
    if school_ids:
        vs.schools.set(School.objects.filter(id__in=school_ids))
    return Response(_vector_store_to_dict(vs, include_detail=True), status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsSuperAdmin])
def vector_store_detail(request, pk):
    """GET → store detail incl. allocated + allocatable schools.
    PATCH {name?, description?, school_ids?} → rename / re-describe / REPLACE the allocation set.
    DELETE → delete the store (its materials' vector_store FK is set null; embeddings survive but
             become invisible to schools that only reached them via this store)."""
    from core.models import VectorStore
    try:
        vs = VectorStore.objects.get(pk=pk)
    except VectorStore.DoesNotExist:
        return Response({'error': 'Vector store not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(_vector_store_to_dict(vs, include_detail=True))

    if request.method == 'DELETE':
        vs.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    if 'name' in request.data:
        new_name = (request.data.get('name') or '').strip()
        if not new_name:
            return Response({'error': 'name cannot be empty'}, status=status.HTTP_400_BAD_REQUEST)
        if VectorStore.objects.filter(name__iexact=new_name).exclude(pk=vs.pk).exists():
            return Response({'error': 'A vector store with this name already exists'}, status=status.HTTP_400_BAD_REQUEST)
        vs.name = new_name
    if 'description' in request.data:
        vs.description = request.data.get('description', '') or ''
    vs.save()
    if 'school_ids' in request.data:
        ids = request.data.get('school_ids') or []
        vs.schools.set(School.objects.filter(id__in=ids))
    return Response(_vector_store_to_dict(vs, include_detail=True))


# ── CBSE patterns list ────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsSuperAdmin])
def cbse_patterns_list(request):
    from core.models import ExamPattern
    qs = ExamPattern.objects.filter(pattern_source='cbse_official').order_by('class_name', 'subject')
    data = [{
        'id': p.id,
        'name': p.name,
        'subject': p.subject,
        'class_name': p.class_name,
        'total_marks': p.total_marks,
        'total_questions': p.total_questions,
        'sections': p.sections,
        'sqp_year': p.sqp_year or '',
    } for p in qs]
    return Response({'patterns': data, 'count': len(data)})


# ── CBSE pattern auto-update ──────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsSuperAdmin])
def update_cbse_patterns(request):
    """Launch a Celery task that uses DeepSeek-V3 to refresh all CBSE official patterns."""
    class_filter = request.data.get('classes') or None   # e.g. ["11","12"]
    subject_filter = request.data.get('subjects') or None
    from core.tasks import update_cbse_patterns_task
    task = update_cbse_patterns_task.delay(
        class_filter=class_filter,
        subject_filter=subject_filter,
    )
    return Response({'task_id': task.id, 'status': 'started'})


@api_view(['GET'])
@permission_classes([IsSuperAdmin])
def cbse_update_status(request, task_id):
    """Poll the status of a running update_cbse_patterns_task."""
    from celery.result import AsyncResult
    result = AsyncResult(task_id)

    if result.state == 'PENDING':
        return Response({'state': 'pending', 'current': 0, 'total': 0, 'results': []})

    if result.state == 'PROGRESS':
        meta = result.info or {}
        return Response({
            'state': 'running',
            'current': meta.get('current', 0),
            'total': meta.get('total', 0),
            'current_subject': meta.get('current_subject', ''),
            'results': meta.get('results', []),
        })

    if result.state == 'SUCCESS':
        data = result.result or {}
        return Response({
            'state': 'done',
            'current': data.get('total', 0),
            'total': data.get('total', 0),
            'results': data.get('results', []),
        })

    # FAILURE
    return Response({'state': 'error', 'error': str(result.info)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Chunk enrichment (LLM metadata labeling — core/enrichment.py) ─────────────

def _fail_if_stale(run, window=900):
    """Auto-close a run whose heartbeat (updated_at, bumped per LLM batch and per task)
    has been silent for `window` seconds — the worker died or the broker lost the queue.
    'running' → 'failed'; 'stopping' → 'stopped' (the stop, in effect, completed).
    Returns the (possibly updated) run."""
    from django.utils import timezone
    if run and run.status in ('running', 'stopping') and \
            (timezone.now() - run.updated_at).total_seconds() > window:
        run.status = 'stopped' if run.status == 'stopping' else 'failed'
        run.error_samples = (run.error_samples or []) + ['run went stale (worker restart?)']
        run.save(update_fields=['status', 'error_samples', 'updated_at'])
    return run


def _enrichment_run_to_dict(run):
    if run is None:
        return None
    return {
        'id': run.id,
        'status': run.status,
        'force': run.force,
        'total_groups': run.total_groups,
        'done_groups': run.done_groups,
        'failed_groups': run.failed_groups,
        'drained_groups': run.drained_groups,
        'chunks_labeled': run.chunks_labeled,
        'summaries_created': run.summaries_created,
        'garbled_found': run.garbled_found,
        'input_tokens': run.input_tokens,
        'output_tokens': run.output_tokens,
        'cost': str(run.cost),
        'error_samples': run.error_samples or [],
        'created_by': run.created_by.username if run.created_by else None,
        'created_at': run.created_at,
        'updated_at': run.updated_at,
    }


@api_view(['GET'])
@permission_classes([IsSuperAdmin])
def enrichment_stats(request):
    """Coverage counters for the enrichment page. Live DB counts (not Celery state), so
    progress survives page refreshes and worker restarts."""
    from django.utils import timezone
    from core.models import MaterialChunk, EnrichmentRun

    # A run with no heartbeat for 15 min is dead (worker restarted mid-run) — flip it
    # here, where the UI polls, or the page would show "running"/"stopping" forever.
    # Live work heartbeats per LLM batch (enrichment._run_is_live), so staleness is real.
    latest = EnrichmentRun.objects.order_by('-created_at').first()
    latest = _fail_if_stale(latest)

    body = MaterialChunk.objects.filter(kind='body')
    total = body.count()
    enriched = body.filter(enriched_at__isnull=False).count()
    return Response({
        'total_chunks': total,
        'enriched_chunks': enriched,
        'pending_chunks': total - enriched,
        'garbled_chunks': body.filter(garbled=True).count(),
        'summary_chunks': MaterialChunk.objects.filter(kind='summary').count(),
        # Chunks without a Material FK can't be grouped for enrichment — surfaced so the
        # superadmin knows they exist rather than wondering why pending never hits zero.
        'unlinked_chunks': body.filter(material__isnull=True).count(),
        'pending_materials': body.filter(enriched_at__isnull=True, material__isnull=False)
                                 .values('material_id').distinct().count(),
        'latest_run': _enrichment_run_to_dict(latest),
    })


@api_view(['POST'])
@permission_classes([IsSuperAdmin])
def enrichment_run(request):
    """Queue the enrichment backfill: one small Celery task per material that still has
    unenriched chunks (or every material when force=true), tied to an EnrichmentRun row
    the frontend polls. 409 if a run is already making progress."""
    from django.utils import timezone
    from core.models import MaterialChunk, EnrichmentRun
    from core.tasks import enrich_materials_group_task
    from core import enrichment as enrichment_mod

    force = bool(request.data.get('force'))

    # Refuse while a run is active ('running' OR draining after a stop) — two live runs
    # could process the same material concurrently and double-bill the LLM. A stale run
    # (no heartbeat for 15 min) is auto-closed first so a dead worker can't block forever.
    latest = _fail_if_stale(EnrichmentRun.objects.order_by('-created_at').first())
    if latest and latest.status in ('running', 'stopping'):
        msg = ('An enrichment run is already in progress'
               if latest.status == 'running'
               else 'The previous run is still stopping — wait for it to finish draining')
        return Response({'error': msg, 'run': _enrichment_run_to_dict(latest)},
                        status=status.HTTP_409_CONFLICT)

    qs = MaterialChunk.objects.filter(kind='body', material__isnull=False)
    if not force:
        qs = qs.filter(enriched_at__isnull=True)
    material_ids = list(qs.values_list('material_id', flat=True).distinct())

    if not material_ids:
        return Response({'detail': 'Nothing to enrich — all chunks are already labeled.',
                         'run': None})

    run = EnrichmentRun.objects.create(status='running', force=force,
                                       total_groups=len(material_ids), created_by=request.user)
    # Enqueue in GROUPS of the parallel pool size (3 per Mantle API key): each group task
    # enriches its materials concurrently, so throughput ≈ pool size instead of 1.
    # Defensively: a dead broker (Redis down) must not leave a zombie 'running' row that
    # blocks the page for 15 minutes.
    size = max(1, enrichment_mod.enrich_concurrency())
    queued, enqueue_error = 0, None
    for i in range(0, len(material_ids), size):
        group = material_ids[i:i + size]
        try:
            enrich_materials_group_task.delay(group, run_id=run.id, force=force)
            queued += len(group)
        except Exception as e:
            enqueue_error = str(e)[:200]
            break
    if queued == 0:
        run.delete()
        return Response(
            {'error': f'Could not queue enrichment tasks — is Redis running? ({enqueue_error})'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if queued < len(material_ids):
        # Partial enqueue: shrink the run to what actually made it onto the queue so the
        # completion math still closes; the rest is picked up by the next (resume) run.
        run.total_groups = queued
        run.error_samples = [f'broker error after queuing {queued}/{len(material_ids)} '
                             f'materials: {enqueue_error}']
        run.save(update_fields=['total_groups', 'error_samples', 'updated_at'])

    return Response({'run': _enrichment_run_to_dict(run)}, status=status.HTTP_202_ACCEPTED)


@api_view(['POST'])
@permission_classes([IsSuperAdmin])
def enrichment_stop(request):
    """Request a stop: the run flips to 'stopping', the material currently in an LLM
    call pauses at its next batch boundary (nothing partial is persisted — that copy
    stays pending), and every queued task drains as a counted no-op. When all tasks are
    accounted for, the run flips to 'stopped'. Finished work is kept — pressing the run
    button again later resumes exactly what is still pending. Idempotent: pressing Stop
    again while stopping just reports the current state."""
    from django.utils import timezone
    from core.models import EnrichmentRun

    run = EnrichmentRun.objects.order_by('-created_at').first()
    if not run or run.status not in ('running', 'stopping'):
        return Response({'error': 'No enrichment run is in progress'},
                        status=status.HTTP_400_BAD_REQUEST)

    # Dead worker / lost queue: no heartbeat for 15 min means nothing will ever drain —
    # close the stop immediately instead of hanging in 'stopping'. Must be judged BEFORE
    # the flip below, which refreshes updated_at.
    stale = (timezone.now() - run.updated_at).total_seconds() > 900

    if run.status == 'running':
        # Race-safe: only flip if it is still running (a finishing task may have just
        # closed the run).
        EnrichmentRun.objects.filter(id=run.id, status='running').update(
            status='stopped' if stale else 'stopping', updated_at=timezone.now())
        run.refresh_from_db()
    elif stale:  # 'stopping' but the drain died — close it out
        run.status = 'stopped'
        run.error_samples = (run.error_samples or []) + ['run went stale (worker restart?)']
        run.save(update_fields=['status', 'error_samples', 'updated_at'])

    return Response({'run': _enrichment_run_to_dict(run)})


@api_view(['POST'])
@permission_classes([IsSuperAdmin])
def enrichment_classify(request):
    """Queue the chapter-kind backfill (ChapterInfo — one kind per chapter, judged from
    name + summary + sample). Cheap and independent of chunk-enrichment runs: it never
    re-reads the corpus through the LLM. force=true re-classifies everything."""
    from django.db.models import Count
    from core.models import MaterialChunk, ChapterInfo
    from core.tasks import classify_all_chapters_task

    from core.enrichment import is_language_subject

    force = bool(request.data.get('force'))
    # Pending must be judged against the LIVE corpus, exactly like the task does —
    # a global ChapterInfo count would let stale rows (chapters whose materials were
    # deleted) mask genuinely unclassified chapters and refuse the backfill forever.
    # Only language subjects count: kinds don't exist for Maths/Science chapters.
    live = {(c, s, u) for c, s, u in
            MaterialChunk.objects.filter(kind='body', chapter_links__isnull=False)
            .values_list('class_name', 'subject', 'chapter_links__unit').distinct()
            if is_language_subject(s)}
    classified_keys = set(ChapterInfo.objects.exclude(kind='')
                          .values_list('class_name', 'subject', 'unit'))
    total = len(live)
    classified = len(live & classified_keys)
    pending = total if force else len(live - classified_keys)
    if pending == 0:
        return Response({'detail': 'All chapters are already classified.',
                         'total': total, 'classified': classified, 'queued': 0})
    try:
        classify_all_chapters_task.delay(force=force, user_id=request.user.id)
    except Exception as e:
        return Response({'error': f'Could not queue the classification task — is Redis '
                                  f'running? ({str(e)[:120]})'},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({'detail': f'Classifying ~{pending} chapters in the background — '
                               'refresh the corpus browser in a couple of minutes.',
                     'total': total, 'classified': classified, 'queued': pending},
                    status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsSuperAdmin])
def enrichment_coverage(request):
    """Corpus browser: per (class, subject, unit) row counts so the superadmin can see
    what is stored and how far enrichment got, chapter by chapter. A chunk linked to
    several chapters appears under each (that's the per-unit view's point); chunks with
    no chapter link group under unit=null."""
    from django.db.models import Count, Q
    from core.models import MaterialChunk

    rows = (MaterialChunk.objects.filter(kind='body')
            .values('class_name', 'subject', 'chapter_links__unit')
            .annotate(
                chunks=Count('id', distinct=True),
                enriched=Count('id', filter=Q(enriched_at__isnull=False), distinct=True),
                garbled=Count('id', filter=Q(garbled=True), distinct=True),
                cleaned=Count('id', filter=~Q(content_clean=''), distinct=True),
                materials=Count('material_id', distinct=True),
            )
            .order_by('class_name', 'subject', 'chapter_links__unit'))

    summary_counts = {
        (r['class_name'], r['subject'], r['chapter_links__unit']): r['n']
        for r in (MaterialChunk.objects.filter(kind='summary')
                  .values('class_name', 'subject', 'chapter_links__unit')
                  .annotate(n=Count('id')))
    }

    from core.models import ChapterInfo
    chapter_kinds = {
        (c, s, u): k
        for c, s, u, k in ChapterInfo.objects.exclude(kind='')
                                             .values_list('class_name', 'subject', 'unit', 'kind')
    }

    data = [{
        'class_name': r['class_name'],
        'subject': r['subject'],
        'unit': r['chapter_links__unit'],
        'materials': r['materials'],
        'chunks': r['chunks'],
        'enriched': r['enriched'],
        'garbled': r['garbled'],
        'cleaned': r['cleaned'],
        'summaries': summary_counts.get((r['class_name'], r['subject'], r['chapter_links__unit']), 0),
        'kind': chapter_kinds.get((r['class_name'], r['subject'], r['chapter_links__unit']), ''),
    } for r in rows]
    return Response({'rows': data, 'count': len(data)})


@api_view(['GET'])
@permission_classes([IsSuperAdmin])
def enrichment_unit_detail(request):
    """Drill-down for one (class, subject, unit): the chapter summary plus the actual
    stored content, chunk by chunk in document order (cleaned copy where one exists).
    Query params because unit labels are free text in any script."""
    from core.models import MaterialChunk

    cls = (request.query_params.get('class') or '').strip()
    subj = (request.query_params.get('subject') or '').strip()
    unit = (request.query_params.get('unit') or '').strip()
    if not cls or not subj:
        return Response({'error': 'class and subject are required'}, status=status.HTTP_400_BAD_REQUEST)

    qs = MaterialChunk.objects.filter(kind='body', class_name=cls, subject=subj)
    qs = qs.filter(chapter_links__unit=unit) if unit else qs.filter(chapter_links__isnull=True)
    # Textbook double-storage keeps identical shared + school copies — show one copy only.
    if qs.filter(school__isnull=True).exists():
        qs = qs.filter(school__isnull=True)

    chunks, cleaned_count, garbled_count = [], 0, 0
    # Order by material first: a unit can span several materials, and each material's
    # chunk_index restarts at 0 — the row id is the only unique key.
    rows = qs.order_by('material_id', 'chunk_index').values_list(
        'id', 'chunk_index', 'content', 'content_clean', 'garbled', 'enriched_at')[:300]
    for pk, idx, content, clean, garbled, enriched_at in rows:
        if clean:
            cleaned_count += 1
        if garbled:
            garbled_count += 1
        chunks.append({
            'id': pk,
            'index': idx,
            'text': (clean or content or '')[:1500],
            'cleaned': bool(clean),
            'garbled': garbled,
            'enriched': enriched_at is not None,
        })

    summary_qs = MaterialChunk.objects.filter(kind='summary', class_name=cls, subject=subj)
    summary_qs = summary_qs.filter(chapter_links__unit=unit) if unit else summary_qs
    summary = summary_qs.values_list('content', flat=True).first()

    return Response({
        'total': len(chunks),
        'cleaned': cleaned_count,
        'garbled': garbled_count,
        'summary': summary,
        'chunks': chunks,
    })


# ── my-school (school admin self-service) ─────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsSchoolAdminOrAbove])
def my_school(request):
    try:
        school = request.user.profile.school
    except Exception:
        school = None
    if not school:
        return Response({'error': 'No school assigned'}, status=status.HTTP_404_NOT_FOUND)
    return Response(_school_to_dict(school, include_stats=True))


# ── system notifications ──────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsSuperAdmin])
def notifications_manage(request):
    """Superadmin: GET active notifications, POST to create a new one."""
    from core.models import SystemNotification, School

    if request.method == 'GET':
        notifications = SystemNotification.objects.filter(is_active=True).prefetch_related('schools').order_by('-created_at')
        data = [{
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'severity': n.severity,
            'animation_interval': n.animation_interval,
            'is_active': n.is_active,
            'school_ids': list(n.schools.values_list('id', flat=True)),
            'school_names': [s.name for s in n.schools.all()],
            'is_global': n.schools.count() == 0,
            'created_at': n.created_at,
            'created_by': n.created_by.username if n.created_by else 'System',
        } for n in notifications]
        return Response({'notifications': data})

    if request.method == 'POST':
        title = (request.data.get('title') or '').strip()
        message = (request.data.get('message') or '').strip()
        severity = request.data.get('severity', 'info')
        school_ids = request.data.get('school_ids', []) or []

        if not title:
            return Response({'error': 'title is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not message:
            return Response({'error': 'message is required'}, status=status.HTTP_400_BAD_REQUEST)
        if severity not in ['info', 'warning', 'error']:
            return Response({'error': 'Invalid severity'}, status=status.HTTP_400_BAD_REQUEST)

        n = SystemNotification.objects.create(
            title=title,
            message=message,
            severity=severity,
            created_by=request.user,
        )

        # Assign schools if provided
        if school_ids:
            schools = School.objects.filter(id__in=school_ids)
            n.schools.set(schools)

        return Response({
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'severity': n.severity,
            'school_ids': list(n.schools.values_list('id', flat=True)),
            'school_names': [s.name for s in n.schools.all()],
            'is_global': n.schools.count() == 0,
            'is_active': n.is_active,
        }, status=status.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsSuperAdmin])
def notification_detail(request, pk):
    """Superadmin: PATCH to update, DELETE to remove a notification."""
    from core.models import SystemNotification, School

    try:
        n = SystemNotification.objects.get(pk=pk)
    except SystemNotification.DoesNotExist:
        return Response({'error': 'Notification not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'DELETE':
        n.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    if request.method == 'PATCH':
        if 'title' in request.data:
            n.title = (request.data.get('title') or '').strip()
        if 'message' in request.data:
            n.message = (request.data.get('message') or '').strip()
        if 'severity' in request.data:
            severity = request.data.get('severity')
            if severity not in ['info', 'warning', 'error']:
                return Response({'error': 'Invalid severity'}, status=status.HTTP_400_BAD_REQUEST)
            n.severity = severity
        if 'is_active' in request.data:
            n.is_active = request.data.get('is_active', True)
        if 'school_ids' in request.data:
            school_ids = request.data.get('school_ids') or []
            schools = School.objects.filter(id__in=school_ids)
            n.schools.set(schools)

        n.save()
        return Response({
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'severity': n.severity,
            'school_ids': list(n.schools.values_list('id', flat=True)),
            'school_names': [s.name for s in n.schools.all()],
            'is_global': n.schools.count() == 0,
            'is_active': n.is_active,
        })


@api_view(['GET'])
def notifications_public(request):
    """Public endpoint: fetch active notifications for display.
    Returns global notifications + school-specific notifications based on user's school."""
    from core.models import SystemNotification
    from django.db.models import Q

    # Get user's school if they belong to one
    user_school = None
    if request.user.is_authenticated:
        try:
            user_school = request.user.profile.school
        except Exception:
            pass
    user_school_id = user_school.id if user_school else None

    # Get notifications: global (no schools) OR targeted to user's school
    if user_school_id:
        notifications = SystemNotification.objects.filter(
            is_active=True
        ).filter(
            Q(schools__isnull=True) | Q(schools__id=user_school_id)
        ).distinct().order_by('-created_at')
    else:
        # Non-authenticated or no school: only global notifications
        notifications = SystemNotification.objects.filter(
            is_active=True,
            schools__isnull=True
        ).order_by('-created_at')

    data = [{
        'id': n.id,
        'title': n.title,
        'message': n.message,
        'severity': n.severity,
        'animation_interval': n.animation_interval,
    } for n in notifications]

    # Synthetic banner while the school's billing period is over — dismissible client-side
    # (per page load) like any other notification, but not stored in SystemNotification.
    if user_school and user_school.billing_period_over:
        data.insert(0, {
            'id': f'billing-{user_school.id}',
            'title': 'Billing period over',
            'message': 'The billing period of your school is over. Please contact the admin.',
            'severity': 'error',
            'animation_interval': 10,
        })
    return Response({'notifications': data})


# ── Active users / live session control (superadmin) ─────────────────────────

# last_seen recency buckets, in seconds. Updates are throttled server-side to ~60s
# (see api.authentication.touch_last_seen), so an actively-working user's last_seen is
# at most ~1 min stale — hence "online" allows a little headroom beyond that.
_ONLINE_WITHIN = 180      # green — active in the last 3 minutes
_IDLE_WITHIN = 15 * 60    # amber — seen in the last 15 minutes


def _activity_status(seconds):
    if seconds is None:
        return 'unknown'
    if seconds <= _ONLINE_WITHIN:
        return 'online'
    if seconds <= _IDLE_WITHIN:
        return 'idle'
    return 'away'


@api_view(['GET'])
@permission_classes([IsSuperAdmin])
def active_users(request):
    """Every currently logged-in user (i.e. holding an auth token), annotated with how
    recently they were active. The superadmin uses this to see who is online and to
    force-log-out or message a specific user."""
    now = timezone.now()
    # A live auth token == currently logged in (login mints one, logout deletes it).
    users = (User.objects
             .filter(auth_token__isnull=False)
             .select_related('profile', 'profile__school'))

    rows = []
    for u in users:
        profile = getattr(u, 'profile', None)
        last_seen = getattr(profile, 'last_seen', None)
        seconds = int((now - last_seen).total_seconds()) if last_seen else None
        school = getattr(profile, 'school', None)
        rows.append({
            'id': u.id,
            'username': u.username,
            'full_name': u.get_full_name(),
            'email': u.email,
            'role': getattr(profile, 'role', 'teacher') if profile else 'teacher',
            'school_id': school.id if school else None,
            'school_name': school.name if school else None,
            'last_seen': last_seen,
            'last_login': u.last_login,
            'seconds_since_seen': seconds,
            'status': _activity_status(seconds),
            'is_you': u.id == request.user.id,
        })

    # Most-recently-active first; never-seen (token but no activity yet) last.
    rows.sort(key=lambda r: (r['seconds_since_seen'] is None, r['seconds_since_seen'] or 0))
    online = sum(1 for r in rows if r['status'] == 'online')
    return Response({
        'now': now,
        'users': rows,
        'total_logged_in': len(rows),
        'online_count': online,
    })


@api_view(['POST'])
@permission_classes([IsSuperAdmin])
def force_logout(request):
    """Force-log-out one user: delete their auth token and any Django sessions. Their app
    is kicked to the login screen on its next request (polls run every ~10s)."""
    from rest_framework.authtoken.models import Token
    from django.contrib.sessions.models import Session

    user_id = request.data.get('user_id')
    if not user_id:
        return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        target = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

    if target.id == request.user.id:
        return Response({'error': "You can't force-log-out yourself."},
                        status=status.HTTP_400_BAD_REQUEST)

    tokens_deleted, _ = Token.objects.filter(user=target).delete()

    # Sessions store the user id in their (encoded) payload, so scan and drop matching ones.
    sessions_deleted = 0
    for s in Session.objects.iterator():
        if str(s.get_decoded().get('_auth_user_id')) == str(target.id):
            s.delete()
            sessions_deleted += 1

    return Response({
        'ok': True,
        'username': target.username,
        'tokens_deleted': tokens_deleted,
        'sessions_deleted': sessions_deleted,
    })
