from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import School, Plan


class Subscription(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_TRIAL = 'trial'
    STATUS_CANCELLED = 'cancelled'
    STATUS_EXPIRED = 'expired'
    STATUS_PENDING = 'pending'

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('trial', 'Trial'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
        ('pending', 'Pending Payment'),
    ]

    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trial')

    # Razorpay identifiers
    razorpay_subscription_id = models.CharField(max_length=100, blank=True)
    razorpay_customer_id = models.CharField(max_length=100, blank=True)

    # Billing period
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.school.name} — {self.plan.display_name} ({self.status})"

    @property
    def is_active(self):
        return self.status in (self.STATUS_ACTIVE, self.STATUS_TRIAL)


class PaymentOrder(models.Model):
    """One row per Razorpay order (checkout session). Linked to the school upgrading."""
    STATUS_CREATED = 'created'
    STATUS_PAID = 'paid'
    STATUS_FAILED = 'failed'

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='payment_orders')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    razorpay_order_id = models.CharField(max_length=100, unique=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    amount_inr = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, default=STATUS_CREATED)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order {self.razorpay_order_id} — {self.school.name}"
