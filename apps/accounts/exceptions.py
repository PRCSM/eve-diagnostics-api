from apps.common.exceptions import AuthenticationError, ConflictError


class EmailAlreadyRegistered(ConflictError):
    code = "EMAIL_ALREADY_REGISTERED"
    default_message = "An account with this email already exists."


class InvalidCredentials(AuthenticationError):
    code = "INVALID_CREDENTIALS"
    default_message = "Invalid email or password."


class InvalidToken(AuthenticationError):
    code = "TOKEN_INVALID"
    default_message = "Token is invalid or expired."
