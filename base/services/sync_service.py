from django.core.cache import cache
from django.utils import timezone
from django.conf import settings


SYNC_ORDER = [
    'user', 'category', 'product', 'delivery_person',
    'order', 'order_item', 'cash_register', 'inkassa',
]

SYNC_LOCK_TTL = 120
SYNC_STATE_TTL = 86400


def _get_model_map():
    from base.models import (
        User, Category, Product, DeliveryPerson,
        Order, OrderItem, CashRegister, Inkassa,
    )
    return {
        'user': User,
        'category': Category,
        'product': Product,
        'delivery_person': DeliveryPerson,
        'order': Order,
        'order_item': OrderItem,
        'cash_register': CashRegister,
        'inkassa': Inkassa,
    }


def _resolve_model(name):
    return _get_model_map().get(name.lower())


class SyncService:

    @staticmethod
    def acquire_lock(lock_name='sync'):
        key = f'sync:lock:{lock_name}'
        if cache.add(key, True, SYNC_LOCK_TTL):
            return True
        return False

    @staticmethod
    def release_lock(lock_name='sync'):
        cache.delete(f'sync:lock:{lock_name}')

    @staticmethod
    def get_unsynced(model_class, branch_id=None):
        qs = model_class.objects.unsynced()
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return [obj.to_sync_dict() for obj in qs]

    @staticmethod
    def get_changes_since(model_class, since_version, branch_id=None):
        qs = model_class.objects.filter(sync_version__gt=since_version)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return [obj.to_sync_dict() for obj in qs]

    @staticmethod
    def get_changes_after(model_class, after_timestamp, branch_id=None):
        qs = model_class.objects.filter(synced_at__gt=after_timestamp)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return [obj.to_sync_dict() for obj in qs]

    @staticmethod
    def apply_records(model_class, records, source_branch=None):
        results = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': []}
        for record in records:
            try:
                _, action = model_class.from_sync_dict(record, branch_id=source_branch)
                if action in results:
                    results[action] += 1
            except Exception as e:
                results['errors'].append({
                    'uuid': record.get('uuid'),
                    'error': str(e),
                })
                results['skipped'] += 1
        return results

    @staticmethod
    def mark_synced(model_class, uuids):
        now = timezone.now()
        for obj in model_class.objects.filter(uuid__in=uuids):
            obj.synced_at = now
            obj.save(_syncing=True, update_fields=['synced_at'])

    @staticmethod
    def push(branch_id=None):
        if not SyncService.acquire_lock('push'):
            return {'success': False, 'message': 'Sync push already in progress'}

        try:
            branch = branch_id or getattr(settings, 'BRANCH_ID', '')
            model_map = _get_model_map()
            payload = {}
            total = 0

            for name in SYNC_ORDER:
                model_class = model_map[name]
                records = SyncService.get_unsynced(model_class, branch)
                if records:
                    payload[name] = records
                    total += len(records)

            cache.set(f'sync:last_push:{branch}', timezone.now().isoformat(), SYNC_STATE_TTL)

            return {
                'success': True,
                'branch_id': branch,
                'total_records': total,
                'data': payload,
            }
        finally:
            SyncService.release_lock('push')

    @staticmethod
    def pull(data, source_branch=None):
        if not SyncService.acquire_lock('pull'):
            return {'success': False, 'message': 'Sync pull already in progress'}

        try:
            results = {}
            total_created = 0
            total_updated = 0
            total_errors = 0

            for name in SYNC_ORDER:
                if name in data:
                    model_class = _resolve_model(name)
                    if not model_class:
                        continue
                    result = SyncService.apply_records(model_class, data[name], source_branch)
                    results[name] = result
                    total_created += result['created']
                    total_updated += result['updated']
                    total_errors += len(result['errors'])

            branch = getattr(settings, 'BRANCH_ID', '')
            cache.set(f'sync:last_pull:{branch}', timezone.now().isoformat(), SYNC_STATE_TTL)

            return {
                'success': True,
                'total_created': total_created,
                'total_updated': total_updated,
                'total_errors': total_errors,
                'details': results,
            }
        finally:
            SyncService.release_lock('pull')

    @staticmethod
    def acknowledge(data):
        model_map = _get_model_map()
        for name, uuids in data.items():
            model_class = model_map.get(name)
            if model_class and uuids:
                SyncService.mark_synced(model_class, uuids)
        return {'success': True, 'message': 'Records acknowledged'}

    @staticmethod
    def status(branch_id=None):
        branch = branch_id or getattr(settings, 'BRANCH_ID', '')
        model_map = _get_model_map()
        models_status = {}

        for name in SYNC_ORDER:
            model_class = model_map[name]
            qs = model_class.objects.all()
            if branch:
                qs = qs.filter(branch_id=branch)
            total = qs.count()
            synced = qs.exclude(synced_at__isnull=True).count()
            unsynced = qs.filter(synced_at__isnull=True).count()
            last_synced = (
                qs.exclude(synced_at__isnull=True)
                .order_by('-synced_at')
                .values_list('synced_at', flat=True)
                .first()
            )
            models_status[name] = {
                'total': total,
                'synced': synced,
                'unsynced': unsynced,
                'last_synced': last_synced.isoformat() if last_synced else None,
            }

        return {
            'success': True,
            'branch_id': branch,
            'last_push': cache.get(f'sync:last_push:{branch}'),
            'last_pull': cache.get(f'sync:last_pull:{branch}'),
            'models': models_status,
        }

    @staticmethod
    def queue_record(instance):
        branch = instance.branch_id or getattr(settings, 'BRANCH_ID', '')
        model_name = instance.__class__.__name__.lower()
        key = f'sync:queue:{branch}'
        entry = f'{model_name}:{instance.uuid}'
        queue = cache.get(key) or []
        if entry not in queue:
            queue.append(entry)
            cache.set(key, queue, SYNC_STATE_TTL)

    @staticmethod
    def get_queue(branch_id=None):
        branch = branch_id or getattr(settings, 'BRANCH_ID', '')
        return cache.get(f'sync:queue:{branch}') or []

    @staticmethod
    def clear_queue(branch_id=None):
        branch = branch_id or getattr(settings, 'BRANCH_ID', '')
        cache.delete(f'sync:queue:{branch}')

    @staticmethod
    def resolve_conflicts(model_class, local_record, remote_record):
        local_version = local_record.get('sync_version', 0)
        remote_version = remote_record.get('sync_version', 0)
        if remote_version > local_version:
            return 'remote'
        if local_version > remote_version:
            return 'local'
        return 'conflict'
