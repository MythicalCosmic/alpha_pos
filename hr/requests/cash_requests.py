from base.requests.base import validate_request


def deposit_request(request):
    return validate_request(request, ['amount'])


def withdraw_request(request):
    return validate_request(request, ['amount'])
