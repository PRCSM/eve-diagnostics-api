from django.db import IntegrityError


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the PostgreSQL constraint behind an IntegrityError, if available.

    Lets services translate a specific constraint violation (e.g. a race on a unique index)
    into a domain error while letting unexpected integrity errors surface as bugs.
    """
    diag = getattr(exc.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None)
