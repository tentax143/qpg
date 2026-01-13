# Login Redirect Fix

## Problem
The user wanted to ensure that when someone visits the root URL (`127.0.0.1:8000`), they are **always** redirected to the login page, regardless of their authentication status.

## Solution
Redesigned the authentication logic to enforce this behavior:

### 1. **Updated `core/views.py` - `login_view` function**
**Before:**
```python
def login_view(request):
    # Debug: Check if user is already authenticated
    if request.user.is_authenticated:
        messages.info(request, f"You are already logged in as {request.user.username}. Redirecting to dashboard.")
        return redirect('dashboard')
    # ... rest of function
```

**After:**
```python
def login_view(request):
    # Always show login page - no automatic redirects for authenticated users
    # This ensures root URL always goes to login page
    # ... rest of function (removed the automatic redirect)
```

### 2. **Root URL Configuration (Already Correct)**
The `qpg/urls.py` already has the correct configuration:
```python
def redirect_to_login(request):
    """Redirect root URL to login page"""
    return HttpResponseRedirect('/login/')

urlpatterns = [
    path("", redirect_to_login, name="home"),
    # ... other patterns
]
```

### 3. **Login Template (Already Correct)**
The `core/templates/login.html` already handles authenticated users properly:
- Shows "Already Logged In" message for authenticated users
- Provides options to go to dashboard or clear session
- Shows login form for unauthenticated users

## Behavior After Fix

### **For Unauthenticated Users:**
1. Visit `127.0.0.1:8000` → Redirects to `/login/`
2. See login form
3. Can login or register

### **For Authenticated Users:**
1. Visit `127.0.0.1:8000` → Redirects to `/login/`
2. See "Already Logged In" message with options:
   - "Go to Dashboard" button
   - "Clear Session & Login Again" button
3. Can still access dashboard via `/dashboard/` directly

## Key Benefits
- ✅ **Consistent Behavior**: Root URL always goes to login page
- ✅ **User-Friendly**: Authenticated users get clear options
- ✅ **Secure**: No automatic redirects that might bypass intended flow
- ✅ **Flexible**: Users can still access dashboard directly if needed

## Testing
Run the test script to verify the behavior:
```bash
python test_login_redirect.py
```

## Files Modified
- `core/views.py` - Updated `login_view` function
- `test_login_redirect.py` - Created test script
- `LOGIN_REDIRECT_FIX.md` - This documentation
