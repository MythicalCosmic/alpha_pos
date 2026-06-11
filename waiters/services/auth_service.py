import logging

logger = logging.getLogger(__name__)
import secrets
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from base.repositories import UserRepository, SessionRepository
from base.security.hashing import verify_password, verify_password_dummy, hash_password
from base.helpers.response import ServiceResponse
from notifications.handlers.shift import ShiftNotification
from base.models import User

SESSION_TTL_DAYS = 7


class WaiterAuthService:
    @staticmethod
    def _user_data(user):
        return {
            'id': user.id,
            'uuid': str(user.uuid),
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role,
            'status': user.status,
            'branch_id': user.branch_id,
        }

    @staticmethod
    def _get_session(session_key):
        return SessionRepository.get_by_session_key(session_key)

    @staticmethod
    def _get_session_user(session_key):
        session = SessionRepository.get_by_session_key(session_key)
        if not session:
            return None, None
        user = session.user_id
        if not user or user.is_deleted:
            return session, None
        return session, user

    @staticmethod
    def login(email, password, ip_address, user_agent):
        user = UserRepository.get_by_email(email)
        if not user:
            verify_password_dummy(password)
            return ServiceResponse.unauthorized("Invalid credentials")

        if not verify_password(password, user.password):
            return ServiceResponse.unauthorized("Invalid credentials")

        if user.status != User.UserStatus.ACTIVE:
            return ServiceResponse.forbidden("Account is suspended")

        if user.role != User.RoleChoices.WAITER:
            return ServiceResponse.forbidden("Only waiter accounts can log in here")

        branch_id = getattr(settings, 'BRANCH_ID', '')
        if branch_id and user.branch_id and user.branch_id != branch_id:
            return ServiceResponse.forbidden("You are not authorized for this branch")

        session_key = secrets.token_hex(32)

        SessionRepository.create(
            user_id=user,
            ip_address=ip_address[:45],
            user_agent=user_agent[:256],
            # Store only the hash — raw token goes to the client, never persisted.
            payload=SessionRepository.hash_token(session_key),
            expires_at=timezone.now() + timedelta(days=SESSION_TTL_DAYS),
        )

        user.last_login_at = timezone.now()
        user.last_login_api = ip_address[:20]
        user.save(update_fields=['last_login_at', 'last_login_api'])

        user_name = f'{user.first_name} {user.last_name}'.strip()
        ShiftNotification.on_cashier_login(user.id, user_name)

        # Shifts are manual: login no longer opens one. The waiter opens it
        # explicitly via POST /shifts/start.

        try:
            from hr.services import AttendanceService
            AttendanceService.auto_check_in(user.id)
        except Exception:
            logger.exception('auto_check_in failed during waiter login (user=%s)', user.id)

        return ServiceResponse.success(
            data={
                'token': session_key,
                'user': WaiterAuthService._user_data(user),
            },
            message="Login successful",
        )

    @staticmethod
    def logout(session_key):
        session = WaiterAuthService._get_session(session_key)
        if not session:
            return ServiceResponse.unauthorized("Invalid session")

        user = session.user_id
        if user and user.role == User.RoleChoices.WAITER:
            ShiftNotification.on_cashier_logout(user.id)

        # Shifts are manual now: logout no longer auto-ends an open shift. The
        # waiter ends it explicitly via POST /shifts/end, so a shift left open
        # at logout stays ACTIVE and can be resumed on the next login.

        if user:
            try:
                from hr.services import AttendanceService
                AttendanceService.auto_check_out(user.id)
            except Exception:
                logger.exception('auto_check_out failed during waiter logout (user=%s)', user.id)

        SessionRepository.invalidate_cache(session_key)
        SessionRepository.delete(session)
        return ServiceResponse.success(message="Logged out")

    @staticmethod
    def logout_all(session_key):
        session = WaiterAuthService._get_session(session_key)
        if not session:
            return ServiceResponse.unauthorized("Invalid session")
        SessionRepository.delete_by_user(session.user_id)
        return ServiceResponse.success(message="All sessions revoked")

    @staticmethod
    def me(session_key):
        session, user = WaiterAuthService._get_session_user(session_key)
        if not user:
            return ServiceResponse.unauthorized("Invalid session")
        data = WaiterAuthService._user_data(user)
        data['last_login_at'] = user.last_login_at.isoformat() if user.last_login_at else None
        return ServiceResponse.success(data=data, message="User data retrieved")

    @staticmethod
    def change_password(session_key, current_password, new_password):
        session, user = WaiterAuthService._get_session_user(session_key)
        if not user:
            return ServiceResponse.unauthorized("Invalid session")
        if not verify_password(current_password, user.password):
            return ServiceResponse.error("Current password is incorrect")
        try:
            validate_password(new_password, user=user)
        except ValidationError as exc:
            return ServiceResponse.validation_error(
                errors={"new_password": list(exc.messages)},
                message="Password does not meet requirements",
            )
        user.password = hash_password(new_password)
        user.save(update_fields=['password'])
        # Revoke any other live sessions so a leaked token can't survive
        # the user's own remediation. The current session stays.
        SessionRepository.delete_by_user_except(user, session_key)
        return ServiceResponse.success(message="Password changed")

    @staticmethod
    def get_active_sessions(session_key):
        session, user = WaiterAuthService._get_session_user(session_key)
        if not user:
            return ServiceResponse.unauthorized("Invalid session")
        sessions = SessionRepository.get_by_user(user)
        return ServiceResponse.success(
            data={
                'sessions': [
                    {
                        'id': s.id,
                        'ip_address': s.ip_address,
                        'user_agent': s.user_agent,
                        'last_activity': s.last_activity.isoformat() if s.last_activity else None,
                        'is_current': s.payload == SessionRepository.hash_token(session_key),
                    }
                    for s in sessions
                ],
            },
            message="Active sessions",
        )

    @staticmethod
    def revoke_session(session_key, target_session_id):
        session = WaiterAuthService._get_session(session_key)
        if not session:
            return ServiceResponse.unauthorized("Invalid session")
        target = SessionRepository.get_by_id(target_session_id)
        if not target or target.user_id_id != session.user_id_id:
            return ServiceResponse.not_found("Session not found")
        if target.payload == SessionRepository.hash_token(session_key):
            return ServiceResponse.error("Cannot revoke current session, use logout instead")
        # target.payload is the stored hash; deleting the row fires the
        # post_delete signal which drops session:{hash} from the cache.
        SessionRepository.delete(target)
        return ServiceResponse.success(message="Session revoked")
