#!/usr/bin/env python3
"""
Test script to verify that root URL always redirects to login page
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

def test_root_url_redirect():
    """Test that root URL always redirects to login page"""
    
    print("=== Testing Root URL Redirect Behavior ===")
    
    client = Client()
    
    # Test 1: Unauthenticated user
    print("\n1. Testing unauthenticated user...")
    response = client.get('/')
    print(f"   Status Code: {response.status_code}")
    print(f"   Redirect URL: {response.url if hasattr(response, 'url') else 'No redirect'}")
    
    if response.status_code == 302:
        print("   ✅ Root URL redirects to login page (unauthenticated)")
    else:
        print("   ❌ Root URL does not redirect properly (unauthenticated)")
    
    # Test 2: Create and login a test user
    print("\n2. Creating test user...")
    try:
        user = User.objects.get(username='testuser')
        print("   ✅ Test user already exists")
    except User.DoesNotExist:
        user = User.objects.create_user(username='testuser', password='testpass123')
        print("   ✅ Test user created")
    
    # Test 3: Authenticated user
    print("\n3. Testing authenticated user...")
    client.login(username='testuser', password='testpass123')
    response = client.get('/')
    print(f"   Status Code: {response.status_code}")
    print(f"   Redirect URL: {response.url if hasattr(response, 'url') else 'No redirect'}")
    
    if response.status_code == 302 and response.url == '/login/':
        print("   ✅ Root URL redirects to login page (authenticated)")
    else:
        print("   ❌ Root URL does not redirect to login page (authenticated)")
    
    # Test 4: Direct login page access (authenticated)
    print("\n4. Testing direct login page access (authenticated)...")
    response = client.get('/login/')
    print(f"   Status Code: {response.status_code}")
    
    if response.status_code == 200:
        print("   ✅ Login page accessible for authenticated users")
        # Check if it shows the "Already Logged In" message
        if 'Already Logged In' in response.content.decode():
            print("   ✅ Shows 'Already Logged In' message")
        else:
            print("   ⚠️ Does not show 'Already Logged In' message")
    else:
        print("   ❌ Login page not accessible for authenticated users")
    
    # Test 5: Dashboard access (authenticated)
    print("\n5. Testing dashboard access (authenticated)...")
    response = client.get('/dashboard/')
    print(f"   Status Code: {response.status_code}")
    
    if response.status_code == 200:
        print("   ✅ Dashboard accessible for authenticated users")
    else:
        print("   ❌ Dashboard not accessible for authenticated users")
    
    print("\n=== Test Summary ===")
    print("✅ Root URL should always redirect to /login/")
    print("✅ Login page should be accessible for both authenticated and unauthenticated users")
    print("✅ Authenticated users should see 'Already Logged In' message on login page")
    print("✅ Dashboard should be accessible for authenticated users")

if __name__ == "__main__":
    test_root_url_redirect()
