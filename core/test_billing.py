"""Tests for the school billing-period-over block (School.billing_period_over)."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import School


class BillingPeriodOverTest(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Billing Test School', billing_period_over=True)
        self.teacher = User.objects.create_user(username='billing_teacher', password='pass12345')
        profile = self.teacher.profile
        profile.school = self.school
        profile.role = 'teacher'
        profile.require_password_change = False
        profile.save()
        self.client = APIClient()
        self.client.force_authenticate(self.teacher)

    def test_login_payload_carries_flag(self):
        anon = APIClient()
        r = anon.post(reverse('api_login'),
                      {'username': 'billing_teacher', 'password': 'pass12345'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['user']['billing_period_over'])

    def test_paper_generation_blocked_with_402(self):
        r = self.client.post(reverse('questionpaper-list'),
                             {'class_name': '10', 'subject': 'English'}, format='json')
        self.assertEqual(r.status_code, 402)
        self.assertTrue(r.data.get('billing_over'))
        self.assertIn('billing period', r.data['error'].lower())

    def test_pattern_ai_generation_blocked_with_402(self):
        r = self.client.post(reverse('exampattern-generate-from-ai'),
                             {'teacher_input': 'A 40-mark test'}, format='json')
        self.assertEqual(r.status_code, 402)
        self.assertTrue(r.data.get('billing_over'))

    def test_notifications_include_billing_banner(self):
        r = self.client.get(reverse('api_notifications_public'))
        ids = [n['id'] for n in r.data['notifications']]
        self.assertIn(f'billing-{self.school.id}', ids)

    def test_clearing_flag_unblocks(self):
        self.school.billing_period_over = False
        self.school.save()
        r = self.client.get(reverse('api_notifications_public'))
        ids = [n['id'] for n in r.data['notifications']]
        self.assertNotIn(f'billing-{self.school.id}', ids)
        r = self.client.post(reverse('exampattern-generate-from-ai'), {}, format='json')
        self.assertNotEqual(r.status_code, 402)   # falls through to normal validation (400)

    def test_superadmin_can_toggle_flag(self):
        admin = User.objects.create_user(username='billing_root', password='pass12345')
        ap = admin.profile
        ap.role = 'superadmin'
        ap.save()
        c = APIClient()
        c.force_authenticate(admin)
        r = c.patch(reverse('api_school_detail', args=[self.school.id]),
                    {'billing_period_over': False}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['billing_period_over'])
        self.school.refresh_from_db()
        self.assertFalse(self.school.billing_period_over)
