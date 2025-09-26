#!/usr/bin/env python3
"""
Test script to verify that login redirect works properly
"""

import os
import sys
import django

# Add the project directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qpg.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User

def test_login_redirect():
    """Test that login properly redirects to dashboard"""
    
    print("=== Testing Login Redirect Fix ===")
    
    client = Client()
    
    # Test 1: Create test user
    print("\n1. Creating test user...")
    try:
        user = User.objects.get(username='testuser')
        print("   ✅ Test user already exists")
    except User.DoesNotExist:
        user = User.objects.create_user(username='testuser', password='testpass123')
        print("   ✅ Test user created")
    
    # Test 2: Visit login page (GET request)
    print("\n2. Testing login page access (GET request)...")
    response = client.get('/login/')
    print(f"   Status Code: {response.status_code}")
    
    if response.status_code == 200:
        print("   ✅ Login page accessible")
    else:
        print("   ❌ Login page not accessible")
    
    # Test 3: Submit login form (POST request)
    print("\n3. Testing login form submission (POST request)...")
    response = client.post('/login/', {
        'username': 'testuser',
        'password': 'testpass123'
    })
    print(f"   Status Code: {response.status_code}")
    print(f"   Redirect URL: {response.url if hasattr(response, 'url') else 'No redirect'}")
    
    if response.status_code == 302 and response.url == '/dashboard/':
        print("   ✅ Login successful and redirects to dashboard")
    else:
        print("   ❌ Login failed or incorrect redirect")
    
    # Test 4: Check if user can access dashboard
    print("\n4. Testing dashboard access after login...")
    response = client.get('/dashboard/')
    print(f"   Status Code: {response.status_code}")
    
    if response.status_code == 200:
        print("   ✅ Dashboard accessible after login")
    else:
        print("   ❌ Dashboard not accessible after login")
    
    # Test 5: Visit login page again (should logout and show login form)
    print("\n5. Testing login page access after being logged in (GET request)...")
    response = client.get('/login/')
    print(f"   Status Code: {response.status_code}")
    
    if response.status_code == 200:
        print("   ✅ Login page accessible (user should be logged out)")
        # Check if it shows the login form
        if 'username' in response.content.decode() and 'password' in response.content.decode():
            print("   ✅ Login form is displayed")
        else:
            print("   ❌ Login form is not displayed")
    else:
        print("   ❌ Login page not accessible")
    
    # Test 6: Check if user is still authenticated after visiting login page
    print("\n6. Testing authentication status after visiting login page...")
    response = client.get('/dashboard/')
    print(f"   Status Code: {response.status_code}")
    
    if response.status_code == 302:  # Should redirect to login
        print("   ✅ User is no longer authenticated (logout worked)")
    else:
        print("   ❌ User is still authenticated (logout failed)")
    
    print("\n=== Test Summary ===")
    print("✅ Login form submission should redirect to dashboard")
    print("✅ Visiting login page should logout authenticated users")
    print("✅ Login page should always show login form")
    print("✅ Users should be required to login fresh every time")

if __name__ == "__main__":
    test_login_redirect()
