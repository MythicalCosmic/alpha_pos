from django.utils import timezone
from base.services.sync.cache import safe_get, safe_set, safe_delete


STATUS_KEY = 'sync:status'
STATUS_TTL = 86400


class SyncStatus:

    @classmethod
    def update(cls, **kwargs):
        data = cls.get()
        data.update(kwargs)
        data['updated_at'] = timezone.now().isoformat()
        safe_set(STATUS_KEY, data, STATUS_TTL)

    @classmethod
    def get(cls):
        return safe_get(STATUS_KEY) or {}

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
    def set_last_pull(cls, created=0, updated=0, errors=None):
        # IMPORTANT: do NOT write `last_pull` here. `last_pull` is the durable
        # pull CURSOR — a cloud-clock `synced_at` frontier that pull_from_cloud
        # advances page by page and sends back as the `since` filter. Stamping
        # it with the terminal's local `now()` (this used to) clobbers that
        # cursor: with any clock skew between terminal and cloud, records the
        # cloud created between the true frontier and the terminal's clock are
        # silently skipped forever (a server-created user never arrives). This
        # field is a separate "when did we last finish a pull" status value.
        cls.update(
            last_pull_at=timezone.now().isoformat(),
            last_pull_created=created,
            last_pull_updated=updated,
            last_pull_error=errors[0] if errors else None,
        )

    @classmethod
    def set_error(cls, error):
        cls.update(last_error=str(error)[:500])

    @classmethod
    def clear(cls):
        safe_delete(STATUS_KEY)
