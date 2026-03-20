import logging
from decimal import Decimal
from django.apps import apps
from django.utils import timezone
from base.services.sync.config import FK_UUID_MAPPINGS, SYNC_ORDER

logger = logging.getLogger(__name__)


def _resolve_foreign_keys(data):
    resolved = {}
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
        except Exception as e:
            logger.error(f'FK resolve error {uuid_field}: {e}')
    return resolved


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


def _prepare_fields(model_class, data):
    model_fields = {}
    for f in model_class._meta.get_fields():
        if hasattr(f, 'column'):
            model_fields[f.name] = f

    cleaned = {}
    for key, value in data.items():
        if key not in model_fields:
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
                error_msg = f'{record_data.get("uuid", "?")}: {str(e)}'
                result['errors'].append(error_msg)
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
        incoming_branch = data.pop('branch_id', branch_id)

        resolved_fks = _resolve_foreign_keys(data)

        for uuid_field in FK_UUID_MAPPINGS:
            data.pop(uuid_field, None)

        cleaned = _prepare_fields(model_class, data)

        try:
            instance = model_class.objects.get(uuid=uuid_val)

            if sync_version < instance.sync_version:
                return instance, 'skipped'

            for key, value in cleaned.items():
                setattr(instance, key, value)

            for fk_field, fk_instance in resolved_fks.items():
                setattr(instance, fk_field, fk_instance)

            instance.sync_version = sync_version
            instance.is_deleted = is_deleted
            instance.synced_at = timezone.now()
            instance.branch_id = incoming_branch
            instance.save(_syncing=True)
            return instance, 'updated'

        except model_class.DoesNotExist:
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
            return instance, 'created'
