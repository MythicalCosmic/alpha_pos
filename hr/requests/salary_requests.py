from base.requests.base import validate_request


def create_salary_request(request):
    return validate_request(request, ['employee_id', 'period_year', 'period_month', 'base_amount'])


def generate_payroll_request(request):
    return validate_request(request, ['period_year', 'period_month'])
