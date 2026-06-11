from base.repositories import UserRepository, ShiftRepository
from base.helpers.response import ServiceResponse


def _serialize_staff(user, on_shift=False):
    # PUBLIC pre-auth payload: shown on the login picker before anyone logs in.
    # Only the fields the monoblock needs to render the picker — never email,
    # permissions, or last_login_at, which would leak the staff roster and
    # account metadata to any unauthenticated caller.
    return {
        'id': user.id,
        'uuid': str(user.uuid),
        'first_name': user.first_name,
        'last_name': user.last_name,
        'name': f"{user.first_name} {user.last_name}".strip(),
        'role': user.role,
        # Managers share the cashier login tier but unlock settings in the UI.
        # The frontend gates the settings menu on this flag.
        'is_manager': user.role == 'MANAGER',
        # Lets the monoblock show "on shift" and offer resume vs. start.
        'on_shift': on_shift,
    }


class StaffService:
    @staticmethod
    def list_cashiers():
        """Active POS staff (cashiers + managers) for the monoblock login screen.

        Pre-auth: shown before anyone logs in. Returns only the fields the
        picker needs — never the password hash. Flags who already has an
        ACTIVE shift so the frontend can resume instead of starting a
        duplicate one (shifts are started manually via POST /shifts/start),
        and flags managers so the UI can surface their settings access.
        """
        cashiers = list(
            UserRepository.get_pos_staff().order_by('first_name', 'last_name')
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
