"""
Custom middleware to handle authentication and session management
"""

from django.shortcuts import redirect
from django.contrib.auth import logout
from django.contrib import messages

class ForceLogoutMiddleware:
    """
    Middleware to force logout when visiting root URL or login page
    """
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only process GET requests to avoid interfering with POST requests
        if request.method == 'GET':
            # Force logout when visiting root URL
            if request.path == '/' and request.user.is_authenticated:
                logout(request)
                messages.info(request, "Please log in again.")
                return redirect('/login/')
            
            # Force logout when visiting login page (but not on POST)
            if request.path == '/login/' and request.user.is_authenticated:
                logout(request)
                messages.info(request, "Please log in again.")
                # Don't redirect, just show the login page

        response = self.get_response(request)
        return response























