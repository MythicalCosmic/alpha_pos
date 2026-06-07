import logging
from decimal import Decimal
from django.apps import apps
from django.db import transaction
from django.utils import timezone
from base.services.sync.config import FK_UUID_MAPPINGS

logger = logging.getLogger(__name__)


def _resolve_foreign_keys(data):
    """Resolve UUID-keyed FK references to local PKs.

    Returns (resolved, missing) where:
      resolved: {fk_field: instance} for FKs successfully looked up
      missing:  [(uuid_field, uuid_value)] for FKs that referenced an unknown
                UUID. The caller decides whether to defer the record (for
                non-nullable FKs the row is incomplete) or persist with NULL
                (the legacy behavior — kept for nullable FKs).
    """
    resolved = {}
    missing = []
    for uuid_field, (app_label, model_name, fk_field) in FK_UUID_MAPPINGS.items():
        uuid_value = data.get(uuid_field)
        if not uuid_value:
            continue
        try:
            related_model = apps.get_model(app_label, model_name)
            instance = related_model.objects.filter(uuid=uuid_value).first()
            if instance:
                resolved[fk_field] = instance
            else:
                logger.warning(f'FK not found: {model_name} uuid={uuid_value}')
                missing.append((uuid_field, uuid_value))
        except Exception as e:
            logger.error(f'FK resolve error {uuid_field}: {e}')
            missing.append((uuid_field, uuid_value))
    return resolved, missing


def _clean_field_value(field, value):
    if value is None:
        return None

    field_type = field.get_internal_type()

    if field_type == 'DecimalField':
        return Decimal(str(value)) if value else Decimal('0')

    if field_type in ('DateTimeField', 'DateField'):
        if isinstance(value, str) and value:
            from dateutil import parser as date_parser
            return date_parser.parse(value)
        return value

    if field_type == 'ForeignKey':
        return None

    if field_type == 'BooleanField':
        return bool(value)

    if field_type in ('IntegerField', 'PositiveIntegerField'):
        return int(value) if value is not None else None

    return value


# Per-model write denylist for incoming sync records. Models opt into rules by
# setting a SYNC_WRITE_DENYLIST class attribute (preferred — keeps the policy
# next to the model); the dict below is a fallback for models that don't.
# Every SyncMixin model declares the attribute (empty by default), so the
# fallback is rarely consulted. User intentionally syncs fully (credentials +
# role) for central user management — see User.SYNC_WRITE_DENYLIST.
WRITE_DENYLIST = {}


def _denylist_for(model_class):
    declared = getattr(model_class, 'SYNC_WRITE_DENYLIST', None)
    if declared is not None:
        return set(declared)
    label = f'{model_class._meta.app_label}.{model_class.__name__}'
    return WRITE_DENYLIST.get(label, set())


def _prepare_fields(model_class, data):
    model_fields = {}
    for f in model_class._meta.get_fields():
        if hasattr(f, 'column'):
            model_fields[f.name] = f

    denied = _denylist_for(model_class)

    cleaned = {}
    for key, value in data.items():
        if key not in model_fields:
            continue
        if key in denied:
            logger.warning(
                'sync receive: dropping denylisted field %s on %s',
                key, model_class.__name__,
            )
            continue
        field = model_fields[key]
        if field.get_internal_type() == 'ForeignKey':
            continue
        try:
            cleaned[key] = _clean_field_value(field, value)
        except Exception as e:
            logger.warning(f'Field {key} clean error: {e}')
            cleaned[key] = value

    return cleaned


def _preserve_updated_at(model_class, instance, incoming_updated):
    # .update() bypasses auto_now so the source-of-truth updated_at survives
    # the receive write and the _should_replace tiebreaker stays meaningful.
    if incoming_updated is None or not hasattr(instance, 'updated_at'):
        return
    model_class.objects.filter(pk=instance.pk).update(updated_at=incoming_updated)
    instance.updated_at = incoming_updated


class CloudReceiver:

    @classmethod
    def is_branch_authorized(cls, branch_token):
        from django.conf import settings
        allowed = getattr(settings, 'ALLOWED_BRANCH_TOKENS', [])
        return branch_token in allowed

    @classmethod
    def receive_batch(cls, model_name, branch_id, records):
        result = {
            'success': True,
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'errors': [],
            # UUIDs of records that raised during apply. Surfaced to the pusher
            # so it removes ONLY confirmed records from its durable queue and
            # re-queues the failures — otherwise a partial-failure batch was
            # purged wholesale on the HTTP-200, silently losing the bad rows.
            'failed_uuids': [],
        }

        try:
            parts = model_name.split('.')
            if len(parts) == 2:
                app_label, model = parts
            else:
                app_label, model = 'base', model_name
            model_class = apps.get_model(app_label, model)
        except Exception as e:
            return {'success': False, 'created': 0, 'updated': 0, 'skipped': 0, 'errors': [str(e)]}

        # Per-model opt-out: AuditLog (and any future write-once-from-local
        # model) sets `_sync_ingest_disabled = True` so a peer can't push
        # forged rows. Push-side is unaffected — local writes still queue
        # outbound for the cloud.
        if getattr(model_class, '_sync_ingest_disabled', False):
            logger.info(
                'sync receive: ingest disabled for %s — skipping %d record(s)',
                model_class.__name__, len(records),
            )
            result['skipped'] = len(records)
            return result

        for record_data in records:
            try:
                _, action = cls._create_or_update(model_class, record_data, branch_id)
                if action == 'created':
                    result['created'] += 1
                elif action == 'updated':
                    result['updated'] += 1
                else:
                    result['skipped'] += 1
            except Exception as e:
                rec_uuid = record_data.get("uuid")
                error_msg = f'{rec_uuid or "?"}: {str(e)}'
                result['errors'].append(error_msg)
                if rec_uuid:
                    result['failed_uuids'].append(rec_uuid)
                logger.error(f'Receive error: {error_msg}')

        return result

    @classmethod
    def _create_or_update(cls, model_class, data, branch_id):
        data = data.copy()

        uuid_val = data.pop('uuid', None)
        if not uuid_val:
            raise ValueError('Record missing UUID')

        sync_version = data.pop('sync_version', 1)
        is_deleted = data.pop('is_deleted', False)
        # Ignore any branch_id in the payload — the receive endpoint binds
        # the auth token to one branch (BRANCH_TOKEN_MAP), so honoring a
        # per-record branch_id would let a branch-token holder write records
        # claiming any other branch's ID. Pull-from-cloud is the only path
        # where the payload branch_id is trusted (cloud is multi-tenant).
        payload_branch = data.pop('branch_id', None)
        if payload_branch and payload_branch != branch_id:
            logger.warning(
                'sync receive: dropping spoofed branch_id=%s (auth=%s) on %s',
                payload_branch, branch_id, model_class.__name__,
            )
        incoming_branch = branch_id

        resolved_fks, missing_fks = _resolve_foreign_keys(data)

        # If any *non-nullable* FK couldn't be resolved (the related model's
        # UUID hasn't synced yet), refuse to materialize the row. The
        # previous behavior was to silently persist with the FK as NULL,
        # permanently losing the association even when the parent later
        # arrived — or DB-rejecting with a NOT NULL violation. Surface as
        # an error so the caller's retry path can re-deliver after the
        # parent batch lands. Nullable FKs fall through to NULL, which is
        # what the model's `null=True` already permits.
        for uuid_field, uuid_value in missing_fks:
            fk_field_name = FK_UUID_MAPPINGS[uuid_field][2]
            try:
                fk_field = model_class._meta.get_field(fk_field_name)
                if not fk_field.null:
                    raise ValueError(
                        f'Unresolved required FK on {model_class.__name__}: '
                        f'{fk_field_name}={uuid_value}. Parent record has not '
                        'synced yet — retry after the parent batch lands.'
                    )
            except Exception as exc:
                if isinstance(exc, ValueError):
                    raise
                # Field lookup failure (mapping points to a field that no
                # longer exists). Log and move on so a stale FK_UUID_MAPPINGS
                # entry can't blow up the whole receive loop.
                logger.warning(
                    'sync receive: FK field %s missing on %s: %s',
                    fk_field_name, model_class.__name__, exc,
                )

        for uuid_field in FK_UUID_MAPPINGS:
            data.pop(uuid_field, None)

        cleaned = _prepare_fields(model_class, data)

        # Per-record atomic + row lock. Without this the get → _should_replace →
        # save sequence is a read-modify-write with no isolation: two concurrent
        # receives of the same UUID both pass _should_replace against the *old*
        # version and the later writer clobbers the earlier one, defeating the
        # deterministic tiebreaker. The caller loops per record and catches
        # exceptions, so each record owns its own transaction; a rollback here
        # leaves the row untouched and the UUID is re-queued via failed_uuids.
        with transaction.atomic():
            try:
                instance = model_class.objects.select_for_update().get(uuid=uuid_val)

                # Route through SyncMixin._should_replace so the deterministic
                # tiebreaker (updated_at then branch_id) applies on equal
                # sync_version. Without this, two branches that landed at the
                # same version silently let whichever batch arrived second win.
                if hasattr(model_class, '_should_replace'):
                    if not model_class._should_replace(
                        instance, sync_version, cleaned, incoming_branch,
                    ):
                        return instance, 'skipped'
                elif sync_version < instance.sync_version:
                    return instance, 'skipped'

                # A locally-tombstoned row is terminal: never let a stale
                # incoming record that won the version/tiebreaker resurrect it
                # by clearing is_deleted (FS7). Deletes only propagate forward.
                if instance.is_deleted and not is_deleted:
                    return instance, 'skipped'

                # Preserve source-of-truth updated_at across save(): every SyncMixin
                # model declares updated_at with auto_now=True, so save() would stamp
                # the receiver's local clock and defeat the _should_replace tiebreaker
                # on every subsequent compare. Pop it and re-apply via .update(),
                # which bypasses auto_now (same approach as SyncMixin.from_sync_dict).
                incoming_updated = cleaned.pop('updated_at', None)

                for key, value in cleaned.items():
                    setattr(instance, key, value)

                for fk_field, fk_instance in resolved_fks.items():
                    setattr(instance, fk_field, fk_instance)

                instance.sync_version = sync_version
                instance.is_deleted = is_deleted
                instance.synced_at = timezone.now()
                instance.branch_id = incoming_branch
                instance.save(_syncing=True)
                _preserve_updated_at(model_class, instance, incoming_updated)
                return instance, 'updated'

            except model_class.DoesNotExist:
                incoming_updated = cleaned.pop('updated_at', None)

                # Reconcile onto an existing row that already owns this model's
                # natural key (e.g. User.email) instead of INSERTing a duplicate
                # that trips the unique constraint and gets dropped + re-queued
                # forever. Converge on the incoming uuid.
                natural = None
                if hasattr(model_class, '_find_by_natural_key'):
                    natural = model_class._find_by_natural_key(cleaned)
                if natural is not None:
                    instance = natural
                    instance.uuid = uuid_val
                    for key, value in cleaned.items():
                        setattr(instance, key, value)
                    for fk_field, fk_instance in resolved_fks.items():
                        setattr(instance, fk_field, fk_instance)
                    instance.sync_version = sync_version
                    instance.is_deleted = is_deleted
                    instance.synced_at = timezone.now()
                    instance.branch_id = incoming_branch
                    instance.save(_syncing=True)
                    _preserve_updated_at(model_class, instance, incoming_updated)
                    return instance, 'updated'

                instance = model_class(
                    uuid=uuid_val,
                    sync_version=sync_version,
                    is_deleted=is_deleted,
                    branch_id=incoming_branch,
                    synced_at=timezone.now(),
                )

                for key, value in cleaned.items():
                    setattr(instance, key, value)

                for fk_field, fk_instance in resolved_fks.items():
                    setattr(instance, fk_field, fk_instance)

                instance.save(_syncing=True)
                _preserve_updated_at(model_class, instance, incoming_updated)
                return instance, 'created'
