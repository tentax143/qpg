# Force Login Every Time - Fix

## Problem
The user wanted the system to **always ask for login credentials** every time they visit the site, even if they were previously logged in. The current behavior was keeping users logged in between browser sessions.

## Solution
Implemented multiple changes to force fresh login every time:

### 1. **Updated Session Settings in `qpg/settings.py`**
```python
# Session settings - Force logout when browser is closed
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 0  # Session expires immediately when browser closes
SESSION_SAVE_EVERY_REQUEST = True  # Save session on every request
```

**What this does:**
- `SESSION_EXPIRE_AT_BROWSER_CLOSE = True`: Sessions expire when browser is closed
- `SESSION_COOKIE_AGE = 0`: No persistent session cookies
- `SESSION_SAVE_EVERY_REQUEST = True`: Session is saved on every request

### 2. **Updated Login View in `core/views.py`**
```python
def login_view(request):
    # If user is already authenticated, show login form anyway
    # This forces fresh login every time
    if request.user.is_authenticated:
        # Logout the current user to force fresh login
        logout(request)
        messages.info(request, "Please log in again.")
    
    # ... rest of login logic
```

**What this does:**
- Automatically logs out any authenticated user who visits the login page
- Forces them to enter credentials again
- Shows "Please log in again" message

### 3. **Simplified Login Template in `core/templates/login.html`**
- Removed the "Already Logged In" section
- Always shows the login form
- No conditional rendering based on authentication status

## New Behavior

### **Every Time You Visit the Site:**
1. **Visit `127.0.0.1:8000`** → Redirects to `/login/`
2. **See login form** (even if previously logged in)
3. **Enter credentials** → Login successful
4. **Redirected to dashboard**
5. **Close browser** → Session expires
6. **Reopen browser and visit site** → Must login again

### **Session Management:**
- ✅ **No persistent sessions**: Sessions don't survive browser closure
- ✅ **Force logout on login page**: Visiting login page logs out current user
- ✅ **Fresh login required**: Must enter credentials every time
- ✅ **Secure**: No automatic logins or session persistence

## Benefits
- 🔒 **Enhanced Security**: No persistent login sessions
- 🎯 **Consistent Behavior**: Always asks for credentials
- 🚫 **No Auto-Login**: Prevents unwanted automatic logins
- 🔄 **Fresh Sessions**: Each visit requires new authentication

## Testing
Run the test script to verify the behavior:
```bash
python test_force_login.py
```

## Files Modified
- `qpg/settings.py` - Added session settings
- `core/views.py` - Updated login view to force logout
- `core/templates/login.html` - Simplified template
- `test_force_login.py` - Created test script
- `FORCE_LOGIN_FIX.md` - This documentation

## User Experience
Now when you:
1. **Login** → Access dashboard
2. **Close browser** → Session expires
3. **Reopen browser** → Must login again
4. **Visit `127.0.0.1:8000`** → Always shows login form

This ensures you **always** need to enter your username and password to access the system! 🔐
