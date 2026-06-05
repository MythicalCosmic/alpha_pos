import logging
from django.utils import timezone
from base.services.sync.cache import safe_add, safe_delete
from base.services.sync.config import (
    SYNC_ORDER, SyncConfig, get_branch_id, is_local_mode,
    get_all_models, get_sync_batch_size,
)
from base.services.sync.queue import SyncQueue
from base.services.sync.transport import check_health, send_batch, fetch_changes
from base.services.sync.status import SyncStatus

logger = logging.getLogger(__name__)

LOCK_TTL = 120


class SyncService:

    @classmethod
    def queue_record(cls, instance):
        if not SyncConfig.is_enabled():
            return

        model_name = instance.__class__.__name__.lower()
        SyncQueue.add(model_name, str(instance.uuid), instance.to_sync_dict())

    @classmethod
    def queue_tombstone(cls, model_name, uuid_val, payload):
        # Push a delete-marker payload for a record that has been hard-deleted
        # locally, so the peer applies the same deletion semantics.
        if not SyncConfig.is_enabled():
            return
        SyncQueue.add(model_name, uuid_val, payload)

    @classmethod
    def push(cls):
        if not SyncConfig.is_enabled():
            return {'success': False, 'message': 'Sync not enabled'}

        if not is_local_mode():
            return {'success': False, 'message': 'Push only available in local mode'}

        if not cls._acquire_lock('push'):
            return {'success': False, 'message': 'Push already in progress'}

        try:
            if not check_health():
                SyncStatus.set_online(False)
                cls._notify_error('Cannot reach cloud server')
                return {'success': False, 'message': 'Cannot reach cloud server', 'offline': True}

            SyncStatus.set_online(True)

            # Self-heal rows whose transaction.on_commit enqueue silently failed
            # (DB hiccup / queue-table lock): SyncMixin.save() leaves synced_at
            # NULL and relies on on_commit to enqueue, but _queue_for_sync
            # swallows exceptions — such a row is live locally yet never pushed.
            # The queue is a cache, not the source of truth; reconcile any
            # unsynced row that isn't already queued before building the batch.
            cls._reconcile_unsynced()

            grouped = SyncQueue.get_grouped()
            if not grouped:
                return {'success': True, 'message': 'Nothing to sync', 'synced': 0}

            sorted_models = sorted(
                grouped.keys(),
                key=lambda m: SYNC_ORDER.index(m) if m in SYNC_ORDER else 999
            )

            total_synced = 0
            total_failed = 0
            errors = []
            synced_uuids = []
            confirmed_by_model = {}
            batch_size = get_sync_batch_size()

            for model_name in sorted_models:
                records = grouped[model_name]

                for i in range(0, len(records), batch_size):
                    batch = records[i:i + batch_size]
                    batch_data = [r['data'] for r in batch]
                    batch_uuids = [r['uuid'] for r in batch]

                    result = send_batch(model_name, batch_data)

                    if result['success']:
                        # A 200 can still carry per-record failures (partial
                        # batch). Remove ONLY the records the receiver confirmed
                        # and keep the rest queued — purging the whole batch on
                        # the HTTP-200 silently lost the failed rows.
                        failed = set(result.get('failed_uuids') or [])
                        confirmed = [u for u in batch_uuids if u not in failed]
                        synced_uuids.extend(confirmed)
                        confirmed_by_model.setdefault(model_name, []).extend(confirmed)
                        total_synced += len(confirmed)
                        if failed:
                            failed_in_batch = [u for u in batch_uuids if u in failed]
                            total_failed += len(failed_in_batch)
                            SyncQueue.mark_batch_failed(
                                failed_in_batch,
                                'receiver rejected record(s) in a partial batch',
                            )
                            msg = (f'{model_name}: {len(failed_in_batch)} of '
                                   f'{len(batch_uuids)} record(s) rejected by receiver')
                            errors.append(msg)
                            logger.warning(msg)
                        logger.info(f'Synced {len(confirmed)} {model_name} records')
                    else:
                        total_failed += len(batch)
                        error_msg = f'{model_name}: {result.get("error", "Unknown")}'
                        errors.append(error_msg)
                        SyncQueue.mark_batch_failed(batch_uuids, result.get('error', 'Unknown'))
                        logger.warning(f'Sync failed for {model_name}: {result.get("error")}')
                        break

            if synced_uuids:
                SyncQueue.remove(synced_uuids)

            # Stamp synced_at on the local rows the cloud confirmed so
            # objects.unsynced() is a meaningful "not yet pushed" signal — both
            # for status_report and the orphan-reconcile sweep. .update() bypasses
            # save(), so it won't bump sync_version or re-null synced_at; a later
            # edit to the row sets synced_at=None again and re-queues it normally.
            if confirmed_by_model:
                models_map = get_all_models()
                now = timezone.now()
                for mname, uuids in confirmed_by_model.items():
                    mclass = models_map.get(mname)
                    if mclass and uuids:
                        mclass.objects.filter(uuid__in=uuids).update(synced_at=now)

            SyncStatus.set_last_sync(total_synced, total_failed, errors)

            if total_synced > 0 and total_failed == 0:
                cls._notify_success(total_synced)
            elif errors:
                cls._notify_error(errors[0])

            return {
                'success': total_failed == 0,
                'synced': total_synced,
                'failed': total_failed,
                'errors': errors,
            }
        finally:
            cls._release_lock('push')

    @classmethod
    def pull(cls, data, source_branch=None):
        if not cls._acquire_lock('pull'):
            return {'success': False, 'message': 'Pull already in progress'}

        try:
            models = get_all_models()
            total_created = 0
            total_updated = 0
            total_errors = 0
            details = {}

            for name in SYNC_ORDER:
                if name not in data:
                    continue

                model_class = models.get(name)
                if not model_class:
                    continue

                result = cls._apply_records(model_class, data[name], source_branch)
                details[name] = result
                total_created += result['created']
                total_updated += result['updated']
                total_errors += len(result['errors'])

            return {
                'success': True,
                'total_created': total_created,
                'total_updated': total_updated,
                'total_errors': total_errors,
                'details': details,
            }
        finally:
            cls._release_lock('pull')

    @classmethod
    def pull_from_cloud(cls):
        if not SyncConfig.is_enabled():
            return {'success': False, 'message': 'Sync not enabled'}

        if not is_local_mode():
            return {'success': False, 'message': 'Pull only available in local mode'}

        from base.services.sync.config import get_pull_enabled
        if not get_pull_enabled():
            return {'success': False, 'message': 'Pull disabled'}

        if not cls._acquire_lock('pull'):
            return {'success': False, 'message': 'Pull already in progress'}

        try:
            if not check_health():
                SyncStatus.set_online(False)
                return {'success': False, 'message': 'Cannot reach cloud server', 'offline': True}

            SyncStatus.set_online(True)

            status_data = SyncStatus.get()
            cursor = status_data.get('last_pull')

            models = get_all_models()
            total_created = 0
            total_updated = 0
            errors = []
            # Page through the change set. The server caps each response at
            # per_page and returns has_more + next_since (the frontier that is
            # safe to resume from). We must follow that frontier instead of
            # jumping the cursor to server_timestamp, or every record past the
            # first page is permanently lost on a long-disconnected branch.
            MAX_PAGES = 10000  # safety bound against a misbehaving server
            for _ in range(MAX_PAGES):
                result = fetch_changes(since_timestamp=cursor)
                if not result['success']:
                    error = result.get('error', 'Unknown')
                    cls._notify_error(f'Pull failed: {error}')
                    SyncStatus.set_last_pull(
                        total_created, total_updated, [str(e) for e in errors[:1]]
                    )
                    return {'success': False, 'message': error,
                            'created': total_created, 'updated': total_updated}

                data = result.get('data', {})
                for name in SYNC_ORDER:
                    if name not in data:
                        continue
                    model_class = models.get(name)
                    if not model_class:
                        continue
                    apply_result = cls._apply_records(model_class, data[name])
                    total_created += apply_result['created']
                    total_updated += apply_result['updated']
                    if apply_result['errors']:
                        errors.extend(apply_result['errors'])

                has_more = result.get('has_more', False)
                next_since = result.get('next_since')
                server_ts = result.get('server_timestamp')

                if not has_more:
                    # Fully drained — advance the persisted cursor to the
                    # server's snapshot time.
                    if server_ts:
                        SyncStatus.update(last_pull=server_ts)
                    break

                if not next_since or next_since == cursor:
                    # Server reports more but can't give us a frontier to
                    # advance to (e.g. NULL synced_at rows). Stop without
                    # advancing the cursor so the next pull retries from the
                    # same point rather than skipping the unfetched tail.
                    logger.warning(
                        'Pull: has_more set but cursor cannot advance '
                        '(next_since=%r); stopping to avoid data loss', next_since
                    )
                    break

                # The frontier is "complete up to next_since"; persisting it now
                # makes the paging crash-safe (a mid-loop failure resumes here
                # instead of re-pulling from the start). Re-applies are
                # idempotent upserts.
                SyncStatus.update(last_pull=next_since)
                cursor = next_since
            else:
                logger.warning('Pull: hit MAX_PAGES (%s); will resume next cycle', MAX_PAGES)

            SyncStatus.set_last_pull(total_created, total_updated, [str(e) for e in errors[:1]])

            total = total_created + total_updated
            if total > 0 and not errors:
                cls._notify_pull_success(total_created, total_updated)
            elif errors:
                cls._notify_error(f'Pull errors: {errors[0]}')

            return {
                'success': True,
                'created': total_created,
                'updated': total_updated,
                'errors': [str(e) for e in errors],
            }
        finally:
            cls._release_lock('pull')

    @classmethod
    def acknowledge(cls, data):
        models = get_all_models()
        now = timezone.now()
        for name, uuids in data.items():
            model_class = models.get(name)
            if model_class and uuids:
                # `.update()` is one SQL statement; the previous loop fired
                # one UPDATE per row plus all SyncMixin.save() side effects
                # (queue add, signals). Acknowledgement should be cheap.
                model_class.objects.filter(uuid__in=uuids).update(synced_at=now)
        return {'success': True, 'message': 'Records acknowledged'}

    @classmethod
    def get_unsynced(cls, model_class, branch_id=None):
        qs = model_class.objects.unsynced()
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return [obj.to_sync_dict() for obj in qs]

    @classmethod
    def get_changes_since(cls, model_class, since_version, branch_id=None):
        qs = model_class.objects.filter(sync_version__gt=since_version)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return [obj.to_sync_dict() for obj in qs]

    @classmethod
    def get_changes_after(cls, model_class, after_timestamp, branch_id=None, limit=None):
        """Return records updated after `after_timestamp`.

        `limit` caps the result set — without it the changes view can
        materialize the entire queue for a long-disconnected branch in a
        single response (OOM on 1M+ row tables). Callers should pass a
        sane page size; pagination is then driven by the most-recent
        `synced_at` the client received.
        """
        qs = model_class.objects.filter(synced_at__gt=after_timestamp).order_by('synced_at')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if limit is not None:
            qs = qs[:limit]
        return [obj.to_sync_dict() for obj in qs]

    @classmethod
    def get_status(cls):
        pending, failed = SyncQueue.count()
        status_data = SyncStatus.get()

        return {
            'enabled': SyncConfig.is_enabled(),
            'mode': get_branch_id(),
            'is_online': status_data.get('is_online', False),
            'last_sync': status_data.get('last_sync'),
            'last_pull': status_data.get('last_pull'),
            'pending_count': pending,
            'failed_count': failed,
            'last_error': status_data.get('last_error'),
            'pending_by_model': SyncQueue.get_summary(),
        }

    @classmethod
    def full_push(cls):
        if not SyncConfig.is_enabled():
            return {'success': False, 'message': 'Sync not enabled'}

        if not is_local_mode():
            return {'success': False, 'message': 'Push only available in local mode'}

        branch = get_branch_id()
        models = get_all_models()

        for name in SYNC_ORDER:
            model_class = models.get(name)
            if not model_class:
                continue

            qs = model_class.objects.all()
            if branch:
                qs = qs.filter(branch_id=branch)

            for obj in qs.iterator():
                SyncQueue.add(name, str(obj.uuid), obj.to_sync_dict())

        return cls.push()

    @classmethod
    def status_report(cls):
        branch = get_branch_id()
        models = get_all_models()
        models_status = {}

        for name in SYNC_ORDER:
            model_class = models.get(name)
            if not model_class:
                continue

            qs = model_class.objects.all()
            if branch:
                qs = qs.filter(branch_id=branch)

            # One aggregate instead of three full scans. The `last_synced`
            # lookup still needs its own query (a Max() aggregate over the
            # same row set), so we keep that as the cheaper of the two.
            from django.db.models import Count, Q, Max
            counts = qs.aggregate(
                total=Count('id'),
                synced=Count('id', filter=Q(synced_at__isnull=False)),
                unsynced=Count('id', filter=Q(synced_at__isnull=True)),
                last_synced=Max('synced_at'),
            )
            total = counts['total']
            synced = counts['synced']
            unsynced = counts['unsynced']
            last_synced = counts['last_synced']

            models_status[name] = {
                'total': total,
                'synced': synced,
                'unsynced': unsynced,
                'last_synced': last_synced.isoformat() if last_synced else None,
            }

        status_data = SyncStatus.get()
        return {
            'success': True,
            'branch_id': branch,
            'last_push': status_data.get('last_sync'),
            'last_pull': status_data.get('last_pull'),
            'models': models_status,
        }

    @classmethod
    def resolve_conflicts(cls, local_record, remote_record):
        local_v = local_record.get('sync_version', 0)
        remote_v = remote_record.get('sync_version', 0)
        if remote_v > local_v:
            return 'remote'
        if local_v > remote_v:
            return 'local'
        return 'conflict'

    @classmethod
    def _reconcile_unsynced(cls):
        """Re-queue any unsynced row that isn't already in the sync queue.

        Backstop for the on_commit enqueue path: if _queue_for_sync ever fails
        (and it swallows the exception), the row is saved with synced_at=NULL
        but never enqueued. This sweep, run at the top of push(), makes the
        queue self-healing without a separate cron. Bounded work after the first
        run because push() now stamps synced_at on confirmed records.
        """
        branch = get_branch_id()
        models = get_all_models()
        requeued = 0
        for name in SYNC_ORDER:
            model_class = models.get(name)
            if not model_class:
                continue
            try:
                qs = model_class.objects.unsynced()
                if branch:
                    qs = qs.filter(branch_id=branch)
                queued = SyncQueue.queued_uuids_for_model(name)
                for obj in qs.iterator():
                    if str(obj.uuid) in queued:
                        continue
                    SyncQueue.add(name, str(obj.uuid), obj.to_sync_dict())
                    requeued += 1
            except Exception as e:
                logger.warning('reconcile unsynced failed for %s: %s', name, e)
        if requeued:
            logger.info('Sync reconcile: re-queued %d orphaned record(s)', requeued)
        return requeued

    @classmethod
    def _apply_records(cls, model_class, records, source_branch=None):
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

    @classmethod
    def _acquire_lock(cls, name):
        return safe_add(f'sync:lock:{name}', True, LOCK_TTL)

    @classmethod
    def _release_lock(cls, name):
        safe_delete(f'sync:lock:{name}')

    @classmethod
    def _notify_success(cls, count):
        try:
            from base.notifications.config import NotificationConfig
            if not NotificationConfig.is_enabled():
                return
            from base.notifications.telegram import TelegramAPI
            from base.notifications.helpers import format_datetime
            _, time_str = format_datetime()
            text = (
                f'<b>SYNC MUVAFFAQIYATLI</b>\n\n'
                f'Yuborildi: <b>{count}</b> ta yozuv\n'
                f'Branch: {get_branch_id()}\n'
                f'Vaqt: {time_str}'
            )
            TelegramAPI.send_message(text)
        except Exception as e:
            logger.debug(f'Sync notification skipped: {e}')

    @classmethod
    def _notify_pull_success(cls, created, updated):
        try:
            from base.notifications.config import NotificationConfig
            if not NotificationConfig.is_enabled():
                return
            from base.notifications.telegram import TelegramAPI
            from base.notifications.helpers import format_datetime
            _, time_str = format_datetime()
            text = (
                f'<b>SYNC QABUL QILINDI</b>\n\n'
                f'Yangi: <b>{created}</b> ta\n'
                f'Yangilangan: <b>{updated}</b> ta\n'
                f'Branch: {get_branch_id()}\n'
                f'Vaqt: {time_str}'
            )
            TelegramAPI.send_message(text)
        except Exception as e:
            logger.debug(f'Pull notification skipped: {e}')

    @classmethod
    def _notify_error(cls, error):
        try:
            from base.notifications.config import NotificationConfig
            if not NotificationConfig.is_enabled():
                return
            from base.notifications.telegram import TelegramAPI
            from base.notifications.helpers import format_datetime
            _, time_str = format_datetime()
            text = (
                f'<b>SYNC XATOLIK</b>\n\n'
                f'Xato: {error}\n'
                f'Branch: {get_branch_id()}\n'
                f'Vaqt: {time_str}'
            )
            TelegramAPI.send_message(text)
        except Exception as e:
            logger.debug(f'Sync error notification skipped: {e}')
