from base.requests.base import validate_request


def create_review_request(request):
    return validate_request(request, ['employee_id', 'review_period_start', 'review_period_end'])


def create_goal_request(request):
    return validate_request(request, ['employee_id', 'title'])
