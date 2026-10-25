class DomainError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class LoginRequired(Exception):
    def __init__(self, next_path: str) -> None:
        super().__init__(next_path)
        self.next_path = next_path
