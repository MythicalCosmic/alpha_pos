from base.requests.base import validate_request


def create_expense_request(request):
    return validate_request(request, ['amount', 'expense_date'])
