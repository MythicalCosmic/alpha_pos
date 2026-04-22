from base.requests.base import validate_request


def create_employee_request(request):
    return validate_request(request, ['user_id', 'position', 'hire_date'])
