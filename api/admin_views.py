from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.db.models import Sum
from django.utils import timezone
from core.models import School, UserProfile, QuestionPaper
from .permissions import IsSuperAdmin, IsSchoolAdminOrAbove
from .auth_serializers import UserSerializer, CreateUserSerializer


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
    school = School.objects.create(
        name=name,
        address=request.data.get('address', ''),
        phone=request.data.get('phone', ''),
        email=request.data.get('email', ''),
        monthly_token_budget=int(request.data.get('monthly_token_budget', 0)),
        is_active=request.data.get('is_active', True),
    )
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

    for field in ('name', 'address', 'phone', 'email', 'monthly_token_budget', 'is_active'):
        if field in request.data:
            val = request.data[field]
            if field == 'monthly_token_budget':
                val = int(val)
            setattr(school, field, val)
    school.save()
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

    serializer = CreateUserSerializer(data=request.data)
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
    profile.save()

    return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
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

    return Response([{
        'id': p.id,
        'class_name': p.class_name,
        'subject': p.subject,
        'status': p.status,
        'difficulty': p.difficulty,
        'cost': str(p.cost) if p.cost else None,
        'input_tokens': p.input_tokens,
        'output_tokens': p.output_tokens,
        'created_by': p.created_by.username if p.created_by else None,
        'created_at': p.created_at,
    } for p in papers])


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
