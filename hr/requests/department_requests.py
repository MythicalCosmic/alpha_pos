from base.requests.base import validate_request


def create_department_request(request):
    return validate_request(request, ['name'])
