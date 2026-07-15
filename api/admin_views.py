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
        'access_shared_vector_store': school.access_shared_vector_store,
        'created_at': school.created_at,
        'updated_at': school.updated_at,
    }
    if include_stats:
        d.update({
            'member_count': school.members.count(),
            # Cumulative — persists even after papers are deleted
            'paper_count': school.total_papers_generated,
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
    for field in ('name', 'address', 'phone', 'email', 'monthly_token_budget', 'is_active', 'access_shared_vector_store'):
        if field in request.data:
            val = request.data[field]
            if field == 'monthly_token_budget':
                val = int(val)
            elif field in ('is_active', 'access_shared_vector_store'):
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
    user_school_id = None
    if request.user.is_authenticated:
        try:
            user_school_id = request.user.profile.school_id
        except Exception:
            pass

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
    return Response({'notifications': data})
