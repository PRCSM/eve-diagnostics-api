from apps.common.exceptions import ConflictError, NotFoundError


class CentreNotFound(NotFoundError):
    code = "CENTRE_NOT_FOUND"
    default_message = "Diagnostic centre not found."


class DiagnosticTestNotFound(NotFoundError):
    code = "TEST_NOT_FOUND"
    default_message = "Diagnostic test not found."


class OfferingNotFound(NotFoundError):
    code = "OFFERING_NOT_FOUND"
    default_message = "This test is not available at this centre."


class DiagnosticTestCodeExists(ConflictError):
    code = "TEST_CODE_EXISTS"
    default_message = "A diagnostic test with this code already exists."


class OfferingExists(ConflictError):
    code = "OFFERING_EXISTS"
    default_message = (
        "This centre already offers this test. Update it with PATCH instead "
        "(including is_active=true to re-enable it)."
    )
