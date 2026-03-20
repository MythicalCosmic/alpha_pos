from django.core.cache import cache
from django.utils import timezone


STATUS_KEY = 'sync:status'
STATUS_TTL = 86400


class SyncStatus:

    @classmethod
    def update(cls, **kwargs):
        data = cls.get()
        data.update(kwargs)
        data['updated_at'] = timezone.now().isoformat()
        cache.set(STATUS_KEY, data, STATUS_TTL)

    @classmethod
    def get(cls):
        return cache.get(STATUS_KEY) or {}

    @classmethod
    def set_online(cls, online=True):
        cls.update(is_online=online)

    @classmethod
    def set_last_sync(cls, synced=0, failed=0, errors=None):
        cls.update(
            last_sync=timezone.now().isoformat(),
            last_synced_count=synced,
            last_failed_count=failed,
            last_error=errors[0] if errors else None,
        )

    @classmethod
    def set_error(cls, error):
        cls.update(last_error=str(error)[:500])

    @classmethod
    def clear(cls):
        cache.delete(STATUS_KEY)
