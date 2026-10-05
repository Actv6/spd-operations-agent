from .models import uid


class AppError(Exception):
    def __init__(self, code, message, status=400, retryable=False):
        self.status = status
        self.body = {"code": code, "message": message, "details": {}, "trace_id": uid(), "retryable": retryable}
        super().__init__(message)
