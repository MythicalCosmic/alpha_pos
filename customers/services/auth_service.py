import secrets
from django.conf import settings
from django.utils import timezone
from base.repositories import UserRepository, SessionRepository
from base.security.hashing import verify_password, hash_password
from base.helpers.response import ServiceResponse
from base.models import User


class AuthService:
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
    def login(email, password, ip_address, user_agent):
        user = UserRepository.get_by_email(email)
        if not user:
            return ServiceResponse.unauthorized("Invalid credentials")

        if not verify_password(password, user.password):
            return ServiceResponse.unauthorized("Invalid credentials")

        if user.status != User.UserStatus.ACTIVE:
            return ServiceResponse.forbidden("Account is suspended")

        if user.role == User.RoleChoices.ADMIN:
            return ServiceResponse.forbidden("Admin accounts cannot log in here")

        branch_id = getattr(settings, 'BRANCH_ID', '')
        if branch_id and user.branch_id and user.branch_id != branch_id:
            return ServiceResponse.forbidden("You are not authorized for this branch")

        session_key = secrets.token_hex(10)

        SessionRepository.create(
            user_id=user,
            ip_address=ip_address[:20],
            user_agent=user_agent[:30],
            payload=session_key,
        )

        user.last_login_at = timezone.now()
        user.last_login_api = ip_address[:20]
        user.save(update_fields=['last_login_at', 'last_login_api'])

        return ServiceResponse.success(
            data={
                'token': session_key,
                'user': AuthService._user_data(user),
            },
            message="Login successful",
        )

    @staticmethod
    def logout(session_key):
        session = SessionRepository.first(payload=session_key)
        if not session:
            return ServiceResponse.unauthorized("Invalid session")
        SessionRepository.delete(session)
        return ServiceResponse.success(message="Logged out")

    @staticmethod
    def logout_all(session_key):
        session = SessionRepository.first(payload=session_key)
        if not session:
            return ServiceResponse.unauthorized("Invalid session")
        SessionRepository.delete_by_user(session.user_id)
        return ServiceResponse.success(message="All sessions revoked")

    @staticmethod
    def me(session_key):
        session = SessionRepository.first(payload=session_key)
        if not session:
            return ServiceResponse.unauthorized("Invalid session")
        user = session.user_id
        if not user or user.is_deleted:
            return ServiceResponse.unauthorized("Invalid session")
        data = AuthService._user_data(user)
        data['last_login_at'] = user.last_login_at.isoformat() if user.last_login_at else None
        return ServiceResponse.success(data=data, message="User data retrieved")

    @staticmethod
    def change_password(session_key, current_password, new_password):
        session = SessionRepository.first(payload=session_key)
        if not session:
            return ServiceResponse.unauthorized("Invalid session")
        user = session.user_id
        if not user or user.is_deleted:
            return ServiceResponse.unauthorized("Invalid session")
        if not verify_password(current_password, user.password):
            return ServiceResponse.error("Current password is incorrect")
        if len(new_password) < 6:
            return ServiceResponse.validation_error(
                errors={"new_password": "Password must be at least 6 characters"},
                message="Validation failed",
            )
        user.password = hash_password(new_password)
        user.save(update_fields=['password'])
        return ServiceResponse.success(message="Password changed")

    @staticmethod
    def get_active_sessions(session_key):
        session = SessionRepository.first(payload=session_key)
        if not session:
            return ServiceResponse.unauthorized("Invalid session")
        sessions = SessionRepository.get_by_user(session.user_id)
        return ServiceResponse.success(
            data={
                'sessions': [
                    {
                        'id': s.id,
                        'ip_address': s.ip_address,
                        'user_agent': s.user_agent,
                        'last_activity': s.last_activity.isoformat() if s.last_activity else None,
                        'is_current': s.payload == session_key,
                    }
                    for s in sessions
                ],
            },
            message="Active sessions",
        )

    @staticmethod
    def revoke_session(session_key, target_session_id):
        session = SessionRepository.first(payload=session_key)
        if not session:
            return ServiceResponse.unauthorized("Invalid session")
        target = SessionRepository.get_by_id(target_session_id)
        if not target or target.user_id_id != session.user_id_id:
            return ServiceResponse.not_found("Session not found")
        if target.payload == session_key:
            return ServiceResponse.error("Cannot revoke current session, use logout instead")
        SessionRepository.delete(target)
        return ServiceResponse.success(message="Session revoked")
