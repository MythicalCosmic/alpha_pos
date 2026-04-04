from django.conf import settings
from base.services.sync.cache import safe_get, safe_set


CACHE_PREFIX = 'sync'

SYNC_ORDER = [
    'user', 'category', 'deliveryperson', 'product',
    'order', 'orderitem', 'cashregister', 'inkassa',
]

MODEL_MAP = {
    'user': 'base.User',
    'category': 'base.Category',
    'deliveryperson': 'base.DeliveryPerson',
    'product': 'base.Product',
    'order': 'base.Order',
    'orderitem': 'base.OrderItem',
    'cashregister': 'base.CashRegister',
    'inkassa': 'base.Inkassa',
}

FK_UUID_MAPPINGS = {
    'user_uuid': ('base', 'User', 'user'),
    'cashier_uuid': ('base', 'User', 'cashier'),
    'delivery_person_uuid': ('base', 'DeliveryPerson', 'delivery_person'),
    'category_uuid': ('base', 'Category', 'category'),
    'order_uuid': ('base', 'Order', 'order'),
    'product_uuid': ('base', 'Product', 'product'),
}


def get_branch_id():
    return getattr(settings, 'BRANCH_ID', '')


def get_deployment_mode():
    return getattr(settings, 'DEPLOYMENT_MODE', 'local')


def get_cloud_url():
    return getattr(settings, 'CLOUD_SYNC_URL', '').rstrip('/')


def get_cloud_token():
    return getattr(settings, 'CLOUD_SYNC_TOKEN', '')


def get_sync_interval():
    return getattr(settings, 'SYNC_INTERVAL', 30)


def get_sync_retry_interval():
    return getattr(settings, 'SYNC_RETRY_INTERVAL', 60)


def get_sync_timeout():
    return getattr(settings, 'SYNC_TIMEOUT', 30)


def get_sync_max_retries():
    return getattr(settings, 'SYNC_MAX_RETRIES', 5)


def get_sync_batch_size():
    return getattr(settings, 'SYNC_BATCH_SIZE', 500)


def get_pull_enabled():
    return getattr(settings, 'SYNC_PULL_ENABLED', True)


def is_local_mode():
    return get_deployment_mode() == 'local'


def resolve_model(name):
    from django.apps import apps
    dotted = MODEL_MAP.get(name.lower())
    if not dotted:
        return None
    app_label, model_name = dotted.split('.')
    return apps.get_model(app_label, model_name)


def get_all_models():
    return {name: resolve_model(name) for name in SYNC_ORDER}


class SyncConfig:

    @classmethod
    def _key(cls, part):
        return f'{CACHE_PREFIX}:config:{part}'

    @classmethod
    def is_enabled(cls):
        override = safe_get(cls._key('enabled'))
        if override is not None:
            return override
        return getattr(settings, 'SYNC_ENABLED', False)

    @classmethod
    def enable(cls):
        safe_set(cls._key('enabled'), True, None)

    @classmethod
    def disable(cls):
        safe_set(cls._key('enabled'), False, None)

    @classmethod
    def get_status(cls):
        return {
            'enabled': cls.is_enabled(),
            'mode': get_deployment_mode(),
            'branch_id': get_branch_id(),
            'cloud_url': get_cloud_url(),
            'interval': get_sync_interval(),
            'batch_size': get_sync_batch_size(),
            'max_retries': get_sync_max_retries(),
            'pull_enabled': get_pull_enabled(),
        }
