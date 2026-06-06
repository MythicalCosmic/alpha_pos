from base.requests.base import validate_request


def login_request(request):
    # The monoblock picker logs cashiers/managers in by user_id + 4-digit PIN
    # (non-managers have no real email — it's an auto-generated placeholder).
    # Email + password is still accepted. Require the PIN plus one identifier.
    data, error = validate_request(request, ['password'])
    if error:
        return None, error
    if not data.get('email') and not data.get('user_id'):
        return None, (
            {
                "success": False,
                "message": "Provide email or user_id",
                "errors": {"identifier": "email or user_id is required"},
            },
            422,
        )
    return data, None


def change_password_request(request):
    return validate_request(request, ['current_password', 'new_password'])


def revoke_session_request(request):
    return validate_request(request, ['session_id'])
