from base.repositories.base import BaseSyncRepository
from base.models import User


class UserRepository(BaseSyncRepository):
    model = User

    @classmethod
    def get_by_email(cls, email):
        try:
            return cls.model.objects.get(email=email, is_deleted=False)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_by_role(cls, role):
        return cls.model.objects.filter(is_deleted=False, role=role)

    @classmethod
    def get_active(cls):
        return cls.model.objects.filter(
            is_deleted=False,
            status=User.UserStatus.ACTIVE,
        )

    @classmethod
    def get_cashiers(cls):
        return cls.model.objects.filter(
            is_deleted=False,
            role=User.RoleChoices.CASHIER,
            status=User.UserStatus.ACTIVE,
        )

    @classmethod
    def get_admins(cls):
        return cls.model.objects.filter(
            is_deleted=False,
            role=User.RoleChoices.ADMIN,
            status=User.UserStatus.ACTIVE,
        )
