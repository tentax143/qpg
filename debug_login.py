#!/usr/bin/env python3
"""
Debug script to test login redirect
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

def debug_login():
    """Debug login redirect issue"""
    
    print("=== Debug Login Redirect ===")
    
    client = Client()
    
    # Test 1: Create test user
    print("\n1. Creating test user...")
    try:
        user = User.objects.get(username='admin')
        print("   ✅ Admin user exists")
    except User.DoesNotExist:
        user = User.objects.create_user(username='admin', password='admin123')
        print("   ✅ Admin user created")
    
    # Test 2: Test login with next parameter
    print("\n2. Testing login with next parameter...")
    response = client.post('/login/?next=/dashboard/', {
        'username': 'admin',
        'password': 'admin123'
    })
    print(f"   Status Code: {response.status_code}")
    print(f"   Redirect URL: {response.url if hasattr(response, 'url') else 'No redirect'}")
    print(f"   Response Content Length: {len(response.content)}")
    
    if response.status_code == 302:
        print("   ✅ Redirect successful")
        if response.url == '/dashboard/':
            print("   ✅ Redirecting to correct URL")
        else:
            print(f"   ⚠️ Redirecting to unexpected URL: {response.url}")
    else:
        print("   ❌ No redirect")
        print(f"   Response content preview: {response.content.decode()[:200]}...")
    
    # Test 3: Test login without next parameter
    print("\n3. Testing login without next parameter...")
    response = client.post('/login/', {
        'username': 'admin',
        'password': 'admin123'
    })
    print(f"   Status Code: {response.status_code}")
    print(f"   Redirect URL: {response.url if hasattr(response, 'url') else 'No redirect'}")
    
    if response.status_code == 302:
        print("   ✅ Redirect successful")
        if response.url == '/dashboard/':
            print("   ✅ Redirecting to dashboard")
        else:
            print(f"   ⚠️ Redirecting to unexpected URL: {response.url}")
    else:
        print("   ❌ No redirect")
    
    # Test 4: Check if user is authenticated
    print("\n4. Checking authentication status...")
    response = client.get('/dashboard/')
    print(f"   Dashboard Status Code: {response.status_code}")
    
    if response.status_code == 200:
        print("   ✅ User is authenticated")
    else:
        print("   ❌ User is not authenticated")

if __name__ == "__main__":
    debug_login()
