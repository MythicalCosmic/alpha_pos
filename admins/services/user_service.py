import logging

from django.db.models import Q

from base.models import User
from base.security.hashing import hash_password
from base.helpers.response import ServiceResponse

logger = logging.getLogger(__name__)


class AdminUserService:

    @staticmethod
    def list_users(page=1, per_page=20, search=None, status=None, role=None):
        qs = User.objects.filter(is_deleted=False).order_by('-id')

        if search:
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )
        if status:
            qs = qs.filter(status=status)
        if role:
            qs = qs.filter(role=role)

        total = qs.count()
        total_pages = (total + per_page - 1) // per_page
        items = qs[(page - 1) * per_page: page * per_page]

        users = [_serialize_user(u) for u in items]

        return ServiceResponse.success(data={
            'users': users,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_users': total,
                'total_pages': total_pages,
                'has_next': page * per_page < total,
                'has_previous': page > 1,
            },
        })

    @staticmethod
    def get_user(user_id):
        try:
            user = User.objects.get(pk=user_id, is_deleted=False)
        except User.DoesNotExist:
            return ServiceResponse.not_found('User not found')
        return ServiceResponse.success(data={'user': _serialize_user(user)})

    @staticmethod
    def create_user(first_name, last_name, role='CASHIER', password=None, email=None):
        if not first_name or not last_name:
            return ServiceResponse.validation_error(
                errors={'name': 'first_name and last_name are required'},
                message='Validation failed',
            )

        # POS staff sign in with a 4-digit PIN, not a full password.
        pin = str(password or '').strip()
        if not pin.isdigit() or len(pin) != 4:
            return ServiceResponse.validation_error(
                errors={'password': 'PIN must be exactly 4 digits'},
                message='Validation failed',
            )
        password = pin

        if role not in User.RoleChoices.values:
            return ServiceResponse.validation_error(
                errors={'role': f"Must be one of {list(User.RoleChoices.values)}"},
                message='Invalid role',
            )

        if not email:
            base = f"{first_name.lower().strip()}.{last_name.lower().strip()}"
            email = f"{base}@local"
            counter = 1
            while User.objects.filter(email=email, is_deleted=False).exists():
                email = f"{base}{counter}@local"
                counter += 1

        if User.objects.filter(email=email, is_deleted=False).exists():
            return ServiceResponse.error(f"User with email {email} already exists")

        user = User.objects.create(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            email=email,
            password=hash_password(str(password)),
            role=role,
            status='ACTIVE',
        )

        return ServiceResponse.created(
            data={'user': _serialize_user(user)},
            message='User created',
        )

    @staticmethod
    def update_user(user_id, **kwargs):
        try:
            user = User.objects.get(pk=user_id, is_deleted=False)
        except User.DoesNotExist:
            return ServiceResponse.not_found('User not found')

        if 'role' in kwargs and kwargs['role'] is not None:
            if kwargs['role'] not in User.RoleChoices.values:
                return ServiceResponse.validation_error(
                    errors={'role': f"Must be one of {list(User.RoleChoices.values)}"},
                    message='Invalid role',
                )

        if 'status' in kwargs and kwargs['status'] is not None:
            if kwargs['status'] not in User.UserStatus.values:
                return ServiceResponse.validation_error(
                    errors={'status': f"Must be one of {list(User.UserStatus.values)}"},
                    message='Invalid status',
                )

        for field in ('first_name', 'last_name', 'role', 'status', 'email'):
            if field in kwargs and kwargs[field] is not None:
                setattr(user, field, kwargs[field])

        # Fine-grained permissions (JSON list, consumed by @permission_required).
        # Previously dropped silently here: the view audited a permissions change
        # as succeeded while the grant/revoke was a no-op. Validate the shape so
        # a stray non-list can't be stored (the decorator would then ignore it),
        # then apply it.
        if 'permissions' in kwargs and kwargs['permissions'] is not None:
            perms = kwargs['permissions']
            if not isinstance(perms, list) or not all(isinstance(p, str) for p in perms):
                return ServiceResponse.validation_error(
                    errors={'permissions': 'Must be a list of permission strings'},
                    message='Invalid permissions',
                )
            user.permissions = perms

        if kwargs.get('password'):
            user.password = hash_password(str(kwargs['password']))

        user.save()
        return ServiceResponse.success(
            data={'user': _serialize_user(user)},
            message='User updated',
        )

    @staticmethod
    def delete_user(user_id):
        try:
            user = User.objects.get(pk=user_id, is_deleted=False)
        except User.DoesNotExist:
            return ServiceResponse.not_found('User not found')

        user.status = 'SUSPENDED'
        user.is_deleted = True
        user.save(update_fields=['status', 'is_deleted', 'synced_at', 'sync_version'])
        return ServiceResponse.success(message='User deleted')


def _serialize_user(user):
    return {
        'id': user.id,
        'uuid': str(user.uuid),
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'role': user.role,
        'status': user.status,
        'permissions': user.permissions or [],
        'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
        'created_at': user.created_at.isoformat() if hasattr(user, 'created_at') and user.created_at else None,
    }
