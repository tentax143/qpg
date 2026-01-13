#!/usr/bin/env python3
"""
Test script to verify that the system always asks for login credentials
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

def test_force_login_behavior():
    """Test that system always asks for login credentials"""
    
    print("=== Testing Force Login Behavior ===")
    
    client = Client()
    
    # Test 1: Unauthenticated user
    print("\n1. Testing unauthenticated user...")
    response = client.get('/')
    print(f"   Status Code: {response.status_code}")
    print(f"   Redirect URL: {response.url if hasattr(response, 'url') else 'No redirect'}")
    
    if response.status_code == 302 and response.url == '/login/':
        print("   ✅ Root URL redirects to login page")
    else:
        print("   ❌ Root URL does not redirect to login page")
    
    # Test 2: Create and login a test user
    print("\n2. Creating test user...")
    try:
        user = User.objects.get(username='testuser')
        print("   ✅ Test user already exists")
    except User.DoesNotExist:
        user = User.objects.create_user(username='testuser', password='testpass123')
        print("   ✅ Test user created")
    
    # Test 3: Login the user
    print("\n3. Logging in user...")
    response = client.post('/login/', {
        'username': 'testuser',
        'password': 'testpass123'
    })
    print(f"   Status Code: {response.status_code}")
    print(f"   Redirect URL: {response.url if hasattr(response, 'url') else 'No redirect'}")
    
    if response.status_code == 302:
        print("   ✅ Login successful")
    else:
        print("   ❌ Login failed")
    
    # Test 4: Check if user is authenticated
    print("\n4. Checking authentication status...")
    response = client.get('/dashboard/')
    print(f"   Dashboard Status Code: {response.status_code}")
    
    if response.status_code == 200:
        print("   ✅ User is authenticated and can access dashboard")
    else:
        print("   ❌ User is not authenticated")
    
    # Test 5: Visit root URL again (should force logout and show login)
    print("\n5. Testing root URL access (should force logout)...")
    response = client.get('/')
    print(f"   Status Code: {response.status_code}")
    print(f"   Redirect URL: {response.url if hasattr(response, 'url') else 'No redirect'}")
    
    if response.status_code == 302 and response.url == '/login/':
        print("   ✅ Root URL forces logout and redirects to login")
    else:
        print("   ❌ Root URL does not force logout")
    
    # Test 6: Check if user is still authenticated after visiting root
    print("\n6. Checking authentication status after root URL visit...")
    response = client.get('/dashboard/')
    print(f"   Dashboard Status Code: {response.status_code}")
    
    if response.status_code == 302:  # Should redirect to login
        print("   ✅ User is no longer authenticated (forced logout worked)")
    else:
        print("   ❌ User is still authenticated (forced logout failed)")
    
    # Test 7: Visit login page directly (should show login form)
    print("\n7. Testing direct login page access...")
    response = client.get('/login/')
    print(f"   Status Code: {response.status_code}")
    
    if response.status_code == 200:
        print("   ✅ Login page accessible")
        # Check if it shows the login form
        if 'username' in response.content.decode() and 'password' in response.content.decode():
            print("   ✅ Login form is displayed")
        else:
            print("   ❌ Login form is not displayed")
    else:
        print("   ❌ Login page not accessible")
    
    print("\n=== Test Summary ===")
    print("✅ Root URL should always redirect to login page")
    print("✅ Visiting root URL should force logout of authenticated users")
    print("✅ Login page should always show login form")
    print("✅ Users should be required to login fresh every time")

if __name__ == "__main__":
    test_force_login_behavior()
