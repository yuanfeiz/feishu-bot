class RequestError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class TokenExpiredError(RequestError):
    """
    Raised on token expires, refresh the token should be
    able to resolve this.
    """