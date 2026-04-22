from base.requests.base import validate_request


def create_event_request(request):
    return validate_request(request, ['employee_id', 'event_type', 'event_date'])
