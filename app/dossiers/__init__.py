"""Dossiês de fabrico → necessidades de corte → cópia da macro MTG2."""


class DossierError(Exception):
    def __init__(self, message: str, status: int = 422, *, kind: str | None = None):
        super().__init__(message)
        self.status = status
        self.kind = kind
