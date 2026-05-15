from django.core.cache import cache
from django.conf import settings
from base.repositories.base import BaseRepository
from base.models import Session


class SessionRepository(BaseRepository):
    model = Session

    @classmethod
    def get_by_session_key(cls, session_key):
        cache_key = f"session:{session_key}"
        ttl = getattr(settings, 'SESSION_CACHE_TTL', 300)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        session = cls.model.objects.select_related('user_id').filter(payload=session_key).first()
        if session:
            cache.set(cache_key, session, ttl)
        return session

    @classmethod
    def invalidate_cache(cls, session_key):
        cache.delete(f"session:{session_key}")

    @classmethod
    def get_by_user(cls, user):
        return cls.model.objects.filter(user_id=user)

    @classmethod
    def get_latest_by_user(cls, user):
        return cls.model.objects.filter(user_id=user).order_by('-last_activity').first()

    @classmethod
    def delete_by_user(cls, user):
        sessions = cls.model.objects.filter(user_id=user)
        for s in sessions:
            cache.delete(f"session:{s.payload}")
        sessions.delete()

    @classmethod
    def delete_by_user_except(cls, user, except_session_key):
        # Used by change-password to revoke every session except the one
        # making the change, so a leaked token doesn't survive remediation.
        sessions = cls.model.objects.filter(user_id=user).exclude(payload=except_session_key)
        for s in sessions:
            cache.delete(f"session:{s.payload}")
        sessions.delete()
