from django.urls import path
from . import views

urlpatterns = [
    path('plans/',          views.plans_list,       name='billing_plans'),
    path('status/',         views.billing_status,   name='billing_status'),
    path('create-order/',   views.create_order,     name='billing_create_order'),
    path('verify-payment/', views.verify_payment,   name='billing_verify_payment'),
    path('webhook/',        views.razorpay_webhook, name='billing_webhook'),
]
