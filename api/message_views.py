"""Direct (user-to-user) messaging.

A superadmin sends a message to one specific user; that user's app polls for unread
messages and shows each as a toast in the top-right corner. Dismissing a toast marks the
message read so it stops coming back. Kept separate from SystemNotification (which is the
broadcast banner) because these are targeted, per-user, and acknowledged individually.
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import DirectMessage
from .permissions import IsSuperAdmin


def _dm_dict(m):
    return {
        'id': m.id,
        'body': m.body,
        'level': m.level,
        'is_read': m.is_read,
        'created_at': m.created_at,
        'sender': (m.sender.get_full_name() or m.sender.username) if m.sender else 'Admin',
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_messages(request):
    """Unread direct messages for the current user — polled by the top-right toast."""
    qs = (DirectMessage.objects
          .filter(recipient=request.user, is_read=False)
          .order_by('created_at'))
    return Response({'messages': [_dm_dict(m) for m in qs]})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_message_read(request, pk):
    """Acknowledge a message (called when the recipient dismisses its toast)."""
    try:
        m = DirectMessage.objects.get(pk=pk, recipient=request.user)
    except DirectMessage.DoesNotExist:
        return Response({'error': 'Message not found'}, status=status.HTTP_404_NOT_FOUND)
    if not m.is_read:
        m.is_read = True
        m.read_at = timezone.now()
        m.save(update_fields=['is_read', 'read_at'])
    return Response({'ok': True})


@api_view(['POST'])
@permission_classes([IsSuperAdmin])
def send_message(request):
    """Superadmin: send a direct message to one user."""
    user_id = request.data.get('user_id')
    body = (request.data.get('body') or '').strip()
    level = request.data.get('level', DirectMessage.LEVEL_INFO)

    if not user_id:
        return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)
    if not body:
        return Response({'error': 'Message body is required'}, status=status.HTTP_400_BAD_REQUEST)
    if level not in dict(DirectMessage.LEVEL_CHOICES):
        level = DirectMessage.LEVEL_INFO

    try:
        recipient = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

    m = DirectMessage.objects.create(
        recipient=recipient, sender=request.user, body=body, level=level,
    )
    return Response(_dm_dict(m), status=status.HTTP_201_CREATED)
