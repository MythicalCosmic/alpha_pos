from base.repositories.base import BaseSyncRepository
from base.models import Category


class CategoryRepository(BaseSyncRepository):
    model = Category

    @classmethod
    def get_by_slug(cls, slug):
        try:
            return cls.model.objects.get(slug=slug, is_deleted=False)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_active(cls):
        return cls.model.objects.filter(is_deleted=False, status='ACTIVE')

    @classmethod
    def get_ordered(cls):
        return cls.model.objects.filter(is_deleted=False).order_by('sort_order')
