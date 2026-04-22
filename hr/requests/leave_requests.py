from base.requests.base import validate_request


def create_leave_type_request(request):
    return validate_request(request, ['name'])


def create_leave_request(request):
    return validate_request(request, ['employee_id', 'leave_type_id', 'start_date', 'end_date'])
