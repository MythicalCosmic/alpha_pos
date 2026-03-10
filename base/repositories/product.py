from base.repositories.base import BaseSyncRepository
from base.models import Product


class ProductRepository(BaseSyncRepository):
    model = Product

    @classmethod
    def get_by_category(cls, category):
        return cls.model.objects.filter(is_deleted=False, category=category)

    @classmethod
    def get_by_category_id(cls, category_id):
        return cls.model.objects.filter(is_deleted=False, category_id=category_id)

    @classmethod
    def search_by_name(cls, name):
        return cls.model.objects.filter(is_deleted=False, name__icontains=name)
