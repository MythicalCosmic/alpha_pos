from base.repositories import UserRepository, ShiftRepository
from base.helpers.response import ServiceResponse


def _serialize_staff(user, on_shift=False):
    return {
        'id': user.id,
        'uuid': str(user.uuid),
        'first_name': user.first_name,
        'last_name': user.last_name,
        'name': f"{user.first_name} {user.last_name}".strip(),
        # The login screen submits email + password to /auth-login, so the
        # list has to carry the email the frontend will log in with.
        'email': user.email,
        'role': user.role,
        # Lets the monoblock show "on shift" and offer resume vs. start.
        'on_shift': on_shift,
        'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
    }


class StaffService:
    @staticmethod
    def list_cashiers():
        """Active cashiers for the monoblock login screen (pre-auth).

        Returns only the fields the picker needs — never the password hash.
        Flags who already has an ACTIVE shift so the frontend can resume
        instead of starting a duplicate one (login auto-starts a shift).
        """
        cashiers = list(
            UserRepository.get_cashiers().order_by('first_name', 'last_name')
        )

        # Single query for the active-shift user ids instead of one per row.
        active_ids = set(
            ShiftRepository.filter_by_status('ACTIVE').values_list(
                'user_id', flat=True
            )
        )

        data = [
            _serialize_staff(u, on_shift=u.id in active_ids) for u in cashiers
        ]
        return ServiceResponse.success(
            data={'cashiers': data, 'total': len(data)},
            message="Cashiers retrieved",
        )
