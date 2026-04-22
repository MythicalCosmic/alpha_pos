from base.requests.base import validate_request


def create_document_request(request):
    return validate_request(request, ['employee_id', 'title'])
