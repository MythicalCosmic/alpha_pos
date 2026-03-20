import json
import logging
from django.core.cache import cache
from django.utils import timezone
from base.services.sync.encoder import serialize_payload

logger = logging.getLogger(__name__)

QUEUE_KEY = 'sync:queue:records'
QUEUE_TTL = 86400 * 7


class SyncQueue:

    @classmethod
    def add(cls, model_name, uuid_val, data):
        queue = cls._get()

        entry = {
            'model_name': model_name,
            'uuid': str(uuid_val),
            'data': serialize_payload(data),
            'created_at': timezone.now().isoformat(),
            'attempts': 0,
            'last_error': None,
        }

        existing_idx = None
        for i, r in enumerate(queue):
            if r['uuid'] == entry['uuid'] and r['model_name'] == entry['model_name']:
                existing_idx = i
                break

        if existing_idx is not None:
            entry['attempts'] = queue[existing_idx].get('attempts', 0)
            queue[existing_idx] = entry
        else:
            queue.append(entry)

        cls._set(queue)
        logger.debug(f'Sync queued: {model_name} {uuid_val}')

    @classmethod
    def get_all(cls):
        return cls._get()

    @classmethod
    def get_by_model(cls, model_name):
        return [r for r in cls._get() if r['model_name'] == model_name]

    @classmethod
    def get_grouped(cls):
        from collections import defaultdict
        grouped = defaultdict(list)
        for r in cls._get():
            grouped[r['model_name']].append(r)
        return dict(grouped)

    @classmethod
    def count(cls):
        queue = cls._get()
        total = len(queue)
        failed = sum(1 for r in queue if r.get('attempts', 0) > 0)
        return total, failed

    @classmethod
    def remove(cls, uuids):
        uuid_set = set(uuids)
        queue = [r for r in cls._get() if r['uuid'] not in uuid_set]
        cls._set(queue)

    @classmethod
    def mark_failed(cls, uuid_val, error):
        queue = cls._get()
        for r in queue:
            if r['uuid'] == uuid_val:
                r['attempts'] = r.get('attempts', 0) + 1
                r['last_error'] = str(error)[:500]
                break
        cls._set(queue)

    @classmethod
    def mark_batch_failed(cls, uuids, error):
        uuid_set = set(uuids)
        queue = cls._get()
        for r in queue:
            if r['uuid'] in uuid_set:
                r['attempts'] = r.get('attempts', 0) + 1
                r['last_error'] = str(error)[:500]
        cls._set(queue)

    @classmethod
    def clear(cls):
        cache.delete(QUEUE_KEY)

    @classmethod
    def get_summary(cls):
        from collections import defaultdict
        summary = defaultdict(int)
        for r in cls._get():
            summary[r['model_name']] += 1
        return dict(summary)

    @classmethod
    def _get(cls):
        data = cache.get(QUEUE_KEY)
        if data is None:
            return []
        if isinstance(data, str):
            try:
                return json.loads(data)
            except (json.JSONDecodeError, ValueError):
                return []
        return data

    @classmethod
    def _set(cls, queue):
        cache.set(QUEUE_KEY, queue, QUEUE_TTL)
