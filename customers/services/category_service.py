from base.repositories import CategoryRepository
from base.helpers.response import ServiceResponse


def _serialize_category(cat):
    return {
        'id': cat.id,
        'name': cat.name,
        'slug': cat.slug,
        'description': cat.description,
        'colors': cat.colors,
        'status': cat.status,
        'sort_order': cat.sort_order,
        'is_deleted': cat.is_deleted,
        'created_at': cat.created_at.isoformat() if cat.created_at else None,
        'updated_at': cat.updated_at.isoformat() if cat.updated_at else None,
    }


ALLOWED_ORDER_FIELDS = {
    'sort_order', '-sort_order', 'name', '-name',
    'created_at', '-created_at', 'updated_at', '-updated_at',
    'status', '-status', 'id', '-id',
}


class CustomerCategoryService:

    @staticmethod
    def get_all_categories(page=1, per_page=20, search=None, status=None,
                           order_by='sort_order'):
        queryset = CategoryRepository.model.objects.filter(is_deleted=False)

        if search:
            queryset = CategoryRepository.search(queryset, search)

        if status:
            queryset = queryset.filter(status=status)

        if order_by not in ALLOWED_ORDER_FIELDS:
            order_by = 'sort_order'
        queryset = queryset.order_by(order_by)

        page_obj, paginator = CategoryRepository.paginate(queryset, page, per_page)

        categories = [_serialize_category(cat) for cat in page_obj.object_list]

        return ServiceResponse.success(data={
            'categories': categories,
            'pagination': {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'total_categories': paginator.count,
                'per_page': per_page,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            },
        })

    @staticmethod
    def get_active_categories():
        categories = CategoryRepository.get_active()
        return ServiceResponse.success(data={'categories': list(categories)})

    @staticmethod
    def get_category_by_id(category_id):
        category = CategoryRepository.get_by_id_cached(category_id)
        if not category:
            return ServiceResponse.not_found("Category not found")

        return ServiceResponse.success(data={'category': _serialize_category(category)})

    @staticmethod
    def get_category_by_slug(slug):
        category = CategoryRepository.get_by_slug(slug)
        if not category:
            return ServiceResponse.not_found("Category not found")

        return ServiceResponse.success(data={
            'category': {
                'id': category.id,
                'name': category.name,
                'slug': category.slug,
                'description': category.description,
                'colors': category.colors,
                'sort_order': category.sort_order,
            }
        })
