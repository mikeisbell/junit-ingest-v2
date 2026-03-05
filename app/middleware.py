import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .logging_config import trace_id_var


class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
        trace_id_var.set(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
