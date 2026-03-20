import json


def create_order_request(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return None, ({"success": False, "message": "Invalid JSON"}, 400)

    if not isinstance(data, dict):
        return None, ({"success": False, "message": "Expected JSON object"}, 400)

    items = data.get('items')
    if not items or not isinstance(items, list) or len(items) == 0:
        return None, ({
            "success": False,
            "message": "Order must contain items",
            "errors": {"items": "At least one item is required"},
        }, 422)

    order_type = data.get('order_type', 'HALL')
    if order_type not in ['HALL', 'DELIVERY', 'PICKUP']:
        return None, ({
            "success": False,
            "message": "Invalid order type",
            "errors": {"order_type": "Must be HALL, DELIVERY, or PICKUP"},
        }, 422)

    for idx, item in enumerate(items):
        if 'product_id' not in item:
            return None, ({
                "success": False,
                "message": f"Item {idx} missing product_id",
                "errors": {f"items[{idx}].product_id": "product_id is required"},
            }, 422)
        qty = item.get('quantity', 1)
        if not isinstance(qty, int) or qty <= 0:
            return None, ({
                "success": False,
                "message": f"Invalid quantity for item {idx}",
                "errors": {f"items[{idx}].quantity": "quantity must be greater than 0"},
            }, 422)

    return data, None
