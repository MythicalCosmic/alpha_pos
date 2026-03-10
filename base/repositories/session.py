from base.repositories.base import BaseRepository
from base.models import Session


class SessionRepository(BaseRepository):
    model = Session

    @classmethod
    def get_by_user(cls, user):
        return cls.model.objects.filter(user_id=user)

    @classmethod
    def get_latest_by_user(cls, user):
        return cls.model.objects.filter(user_id=user).order_by('-last_activity').first()

    @classmethod
    def delete_by_user(cls, user):
        cls.model.objects.filter(user_id=user).delete()
