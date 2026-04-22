from base.requests.base import validate_request


def check_in_request(request):
    return validate_request(request, ['employee_id'])


def create_attendance_request(request):
    return validate_request(request, ['employee_id', 'date'])
