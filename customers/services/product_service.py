from base.repositories import ProductRepository, CategoryRepository
from base.helpers.response import ServiceResponse


def _serialize_product(product):
    return {
        'id': product.id,
        'name': product.name,
        'description': product.description,
        'price': str(product.price),
        'colors': product.colors,
        'is_instant': product.is_instant,
        'category_id': product.category_id,
        'category': {
            'id': product.category.id,
            'name': product.category.name,
            'slug': product.category.slug,
        } if product.category else None,
        'is_deleted': product.is_deleted,
        'created_at': product.created_at.isoformat() if product.created_at else None,
        'updated_at': product.updated_at.isoformat() if product.updated_at else None,
    }


ALLOWED_ORDER_FIELDS = {
    'name', '-name', 'price', '-price',
    'created_at', '-created_at', 'updated_at', '-updated_at',
    'id', '-id', 'category__name', '-category__name',
}


class CustomerProductService:

    @staticmethod
    def get_all_products(page=1, per_page=20, search=None, category_ids=None,
                         order_by='-created_at', popular=True):
        queryset = ProductRepository.model.objects.select_related('category').filter(is_deleted=False)

        if search:
            queryset = ProductRepository.search(queryset, search)

        if category_ids:
            if isinstance(category_ids, str):
                category_ids = [int(x.strip()) for x in category_ids.split(',') if x.strip().isdigit()]
            if category_ids:
                queryset = queryset.filter(category_id__in=category_ids)

        if order_by not in ALLOWED_ORDER_FIELDS:
            order_by = '-created_at'
        if popular:
            # Top-selling first (default). Composes with the category/search
            # filters above. popular=False restores the plain order_by.
            from base.repositories.order_item import OrderItemRepository
            queryset = OrderItemRepository.apply_popularity_order(
                queryset, fallback_order_by=order_by)
        else:
            queryset = queryset.order_by(order_by)

        page_obj, paginator = ProductRepository.paginate(queryset, page, per_page)

        products = [_serialize_product(p) for p in page_obj.object_list]

        return ServiceResponse.success(data={
            'products': products,
            'pagination': {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'total_products': paginator.count,
                'per_page': per_page,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            },
        })

    @staticmethod
    def get_products_by_category(category_id):
        category = CategoryRepository.get_by_id(category_id)
        if not category:
            return ServiceResponse.not_found("Category not found")

        products = ProductRepository.get_by_category_id(category_id).select_related('category').order_by('name')
        return ServiceResponse.success(data={
            'products': [_serialize_product(p) for p in products],
            'category': {
                'id': category.id,
                'name': category.name,
                'slug': category.slug,
            },
        })

    @staticmethod
    def get_product_by_id(product_id):
        product = ProductRepository.get_by_id_cached(product_id)
        if not product:
            return ServiceResponse.not_found("Product not found")

        return ServiceResponse.success(data={'product': _serialize_product(product)})
