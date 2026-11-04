"""The shared error body (memo, "Errors", and unified issue #4).

Every error is ``{"error": {"code": "...", "message": "..."}}``. Callers branch on the
status and the code, never on the message.
"""


class ContractError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def body(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": self.message}}


def not_found(path: str) -> ContractError:
    return ContractError(404, "not_found", f"nothing exists at {path}")


def conflict(path: str) -> ContractError:
    return ContractError(409, "conflict", f"something already exists at {path}")


def invalid_operation(message: str) -> ContractError:
    return ContractError(422, "invalid_operation", message)
