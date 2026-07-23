"""Authentication classes that also record user activity.

The frontend authenticates every API call with a DRF token (SessionAuthentication is
kept as a fallback for the legacy CSRF/model-choice views). We subclass both so that
each authenticated request refreshes the user's ``UserProfile.last_seen`` — throttled to
at most one write per minute so it never adds a write to every request. This is what the
superadmin "Active Users" page reads to tell who is genuinely active right now versus who
merely holds a stale token.
"""

from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from django.utils import timezone

# Don't touch the DB more often than this per user (seconds).
_TOUCH_THROTTLE_SECONDS = 60


def touch_last_seen(user):
    """Best-effort refresh of the user's last_seen. Never raises — activity tracking
    must not be able to break an otherwise-valid request."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return
    try:
        from core.models import UserProfile
        profile = UserProfile.objects.filter(user=user).only('id', 'last_seen').first()
        if profile is None:
            return
        now = timezone.now()
        if profile.last_seen is None or (now - profile.last_seen).total_seconds() > _TOUCH_THROTTLE_SECONDS:
            # update() avoids the post_save signal and touches only the one column.
            UserProfile.objects.filter(pk=profile.pk).update(last_seen=now)
    except Exception:
        pass


class LastSeenTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        result = super().authenticate_credentials(key)
        touch_last_seen(result[0])
        return result


class LastSeenSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            touch_last_seen(result[0])
        return result
