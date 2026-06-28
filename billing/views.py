import hashlib
import hmac
import json
import os

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from dateutil.relativedelta import relativedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status

from core.models import Plan, School
from .models import Subscription, PaymentOrder


def _get_school(user):
    try:
        return user.profile.school
    except Exception:
        return None


def _razorpay_client():
    import razorpay
    key_id = os.environ.get('RAZORPAY_KEY_ID', '')
    key_secret = os.environ.get('RAZORPAY_KEY_SECRET', '')
    return razorpay.Client(auth=(key_id, key_secret))


# ── Plan listing (public) ─────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def plans_list(request):
    """Return all plans for the pricing page."""
    plans = Plan.objects.all().order_by('price_inr')
    return Response([{
        'name': p.name,
        'display_name': p.display_name,
        'monthly_paper_limit': p.monthly_paper_limit,
        'teacher_limit': p.teacher_limit,
        'price_inr': str(p.price_inr),
    } for p in plans])


# ── Billing status for the current school ────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def billing_status(request):
    """Return the current school's plan + usage + trial info."""
    school = _get_school(request.user)
    if not school:
        return Response({'error': 'No school assigned'}, status=status.HTTP_404_NOT_FOUND)

    plan = school.effective_plan()
    papers_used = school.papers_this_month()
    paper_limit = plan.monthly_paper_limit if plan else 5
    teacher_count = school.members.count()
    teacher_limit = plan.teacher_limit if plan else 2

    return Response({
        'plan_name': plan.display_name if plan else 'Free',
        'plan_key': plan.name if plan else 'free',
        'price_inr': str(plan.price_inr) if plan else '0',
        'papers_this_month': papers_used,
        'paper_limit': paper_limit,
        'paper_limit_unlimited': paper_limit == -1,
        'teacher_count': teacher_count,
        'teacher_limit': teacher_limit,
        'teacher_limit_unlimited': teacher_limit == -1,
        'is_on_trial': school.is_on_trial(),
        'trial_ends_at': school.plan_expires_at if school.is_on_trial() else None,
        'plan_expires_at': school.plan_expires_at,
        'razorpay_key_id': os.environ.get('RAZORPAY_KEY_ID', ''),
    })


# ── Create Razorpay order ─────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    """Create a Razorpay order for upgrading to a paid plan.

    Body: { plan_name: "basic" | "pro" | "school" }
    Returns: { order_id, amount, currency, razorpay_key_id }
    """
    school = _get_school(request.user)
    if not school:
        return Response({'error': 'No school assigned'}, status=status.HTTP_400_BAD_REQUEST)

    plan_name = (request.data.get('plan_name') or '').strip()
    try:
        plan = Plan.objects.get(name=plan_name)
    except Plan.DoesNotExist:
        return Response({'error': f'Unknown plan: {plan_name}'}, status=status.HTTP_400_BAD_REQUEST)

    if plan.name == Plan.PLAN_FREE:
        return Response({'error': 'Cannot purchase the free plan'}, status=status.HTTP_400_BAD_REQUEST)

    # Amount in paise (1 INR = 100 paise)
    amount_paise = int(plan.price_inr * 100)

    try:
        client = _razorpay_client()
        order = client.order.create({
            'amount': amount_paise,
            'currency': 'INR',
            'receipt': f'school_{school.id}_plan_{plan.name}',
            'notes': {
                'school_id': str(school.id),
                'school_name': school.name,
                'plan': plan.name,
            },
        })
    except Exception as e:
        return Response({'error': f'Could not create payment order: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    PaymentOrder.objects.create(
        school=school,
        plan=plan,
        razorpay_order_id=order['id'],
        amount_inr=plan.price_inr,
        status='created',
        created_by=request.user,
    )

    return Response({
        'order_id': order['id'],
        'amount': amount_paise,
        'currency': 'INR',
        'razorpay_key_id': os.environ.get('RAZORPAY_KEY_ID', ''),
        'plan_display': plan.display_name,
    })


# ── Verify payment after Razorpay checkout ────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_payment(request):
    """Called by the frontend after Razorpay checkout succeeds.

    Body: { razorpay_order_id, razorpay_payment_id, razorpay_signature }
    Verifies the signature, activates the plan, and returns updated billing status.
    """
    order_id   = request.data.get('razorpay_order_id', '')
    payment_id = request.data.get('razorpay_payment_id', '')
    signature  = request.data.get('razorpay_signature', '')

    secret = os.environ.get('RAZORPAY_KEY_SECRET', '')
    expected = hmac.new(
        secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        return Response({'error': 'Invalid payment signature'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        po = PaymentOrder.objects.get(razorpay_order_id=order_id)
    except PaymentOrder.DoesNotExist:
        return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

    po.razorpay_payment_id = payment_id
    po.status = 'paid'
    po.save(update_fields=['razorpay_payment_id', 'status'])

    _activate_plan(po.school, po.plan)
    return Response({'status': 'activated', 'plan': po.plan.display_name})


def _activate_plan(school, plan):
    """Upgrade the school to a paid plan for one month."""
    now = timezone.now()
    school.plan = plan
    school.plan_expires_at = now + relativedelta(months=1)
    school.trial_started_at = None   # trial over once paid
    school.save(update_fields=['plan', 'plan_expires_at', 'trial_started_at'])

    Subscription.objects.update_or_create(
        school=school,
        defaults={
            'plan': plan,
            'status': Subscription.STATUS_ACTIVE,
            'current_period_start': now,
            'current_period_end': now + relativedelta(months=1),
        },
    )


# ── Razorpay webhook ──────────────────────────────────────────────────────────

@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def razorpay_webhook(request):
    """Razorpay sends events here. Used for subscription renewals + payment.captured events."""
    secret = os.environ.get('RAZORPAY_WEBHOOK_SECRET', '')

    if secret:
        sig = request.headers.get('X-Razorpay-Signature', '')
        body = request.body
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        event = json.loads(request.body)
    except Exception:
        return Response({'error': 'Bad JSON'}, status=status.HTTP_400_BAD_REQUEST)

    event_type = event.get('event', '')

    if event_type == 'payment.captured':
        payload = event.get('payload', {}).get('payment', {}).get('entity', {})
        order_id = payload.get('order_id', '')
        payment_id = payload.get('id', '')
        try:
            po = PaymentOrder.objects.get(razorpay_order_id=order_id, status='created')
            po.razorpay_payment_id = payment_id
            po.status = 'paid'
            po.save(update_fields=['razorpay_payment_id', 'status'])
            _activate_plan(po.school, po.plan)
        except PaymentOrder.DoesNotExist:
            pass

    elif event_type == 'subscription.charged':
        # Auto-renewal: extend plan by one month
        sub_id = (event.get('payload', {})
                      .get('subscription', {})
                      .get('entity', {})
                      .get('id', ''))
        try:
            sub = Subscription.objects.get(razorpay_subscription_id=sub_id)
            _activate_plan(sub.school, sub.plan)
        except Subscription.DoesNotExist:
            pass

    elif event_type in ('subscription.cancelled', 'subscription.completed'):
        sub_id = (event.get('payload', {})
                      .get('subscription', {})
                      .get('entity', {})
                      .get('id', ''))
        try:
            sub = Subscription.objects.get(razorpay_subscription_id=sub_id)
            sub.status = Subscription.STATUS_CANCELLED
            sub.save(update_fields=['status'])
        except Subscription.DoesNotExist:
            pass

    return Response({'status': 'ok'})
