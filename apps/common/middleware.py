import logging
import re
import time
import uuid

from apps.common.request_context import request_id_var

access_logger = logging.getLogger("apps.access")

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestIdMiddleware:
    """Assign (or propagate) a request ID, expose it in responses and write one access-log line.

    The query string is deliberately not logged: search terms can contain health data.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = self.get_response(request)
            response[REQUEST_ID_HEADER] = request_id
            self._log(request, response.status_code, started)
            return response
        finally:
            request_id_var.reset(token)

    @staticmethod
    def _log(request, status_code: int, started: float) -> None:
        user = getattr(request, "user", None)
        user_id = str(user.pk) if user is not None and user.is_authenticated else None
        match = getattr(request, "resolver_match", None)
        level = logging.ERROR if status_code >= 500 else logging.INFO
        access_logger.log(
            level,
            "http_request",
            extra={
                "method": request.method,
                "path": request.path,
                "route": match.route if match else None,
                "status": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "user_id": user_id,
            },
        )
