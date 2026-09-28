import logging

from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from django.db import IntegrityError, transaction
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.exceptions import EmailAlreadyRegistered, InvalidCredentials, InvalidToken
from apps.accounts.models import User
from apps.common.db import violated_constraint

logger = logging.getLogger(__name__)


def register_user(*, email: str, password: str, full_name: str, phone: str = "") -> User:
    """Create a regular (non-staff) account. Admins are only created via `createsuperuser`."""
    if User.objects.filter(email=email).exists():
        raise EmailAlreadyRegistered()
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=email, password=password, full_name=full_name, phone=phone
            )
    except IntegrityError as exc:
        # Two concurrent signups with the same email: the unique constraint decides.
        if violated_constraint(exc) == "accounts_user_email_unique":
            raise EmailAlreadyRegistered() from exc
        raise
    logger.info("user.registered", extra={"user_id": str(user.id)})
    return user


def login(*, email: str, password: str, request=None) -> tuple[User, RefreshToken]:
    """Verify credentials and issue a token pair.

    Unknown email, wrong password and inactive account all produce the same error so the
    endpoint can't be used to discover which emails are registered.
    """
    user = authenticate(request=request, email=email, password=password)
    if user is None:
        logger.info("user.login_failed")
        raise InvalidCredentials()
    update_last_login(None, user)
    logger.info("user.logged_in", extra={"user_id": str(user.id)})
    return user, RefreshToken.for_user(user)


def logout(*, user: User, refresh_token: str) -> None:
    """Blacklist the caller's refresh token. The short-lived access token simply expires."""
    try:
        token = RefreshToken(refresh_token)
    except TokenError as exc:
        raise InvalidToken() from exc
    if token.get("user_id") != str(user.id):
        raise InvalidToken()
    token.blacklist()
    logger.info("user.logged_out", extra={"user_id": str(user.id)})
