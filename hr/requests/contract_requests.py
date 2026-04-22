from base.requests.base import validate_request


def create_contract_request(request):
    return validate_request(request, ['employee_id', 'start_date'])


def terminate_request(request):
    return validate_request(request, ['termination_date'])


def renew_request(request):
    return validate_request(request, ['new_start_date', 'new_end_date'])
