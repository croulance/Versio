from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IssuedToken:
    """Framework-free view of a SupplierAuthToken, returned after login/refresh
    so services never touch the ORM instance directly."""

    key: str
    expires_at: datetime


@dataclass(frozen=True)
class SupplierIdentity:
    """Framework-free view of the identity carried by a still-valid token."""

    supplier_id: int
    supplier_account_id: int | None
    email: str
    groups: list[str]
    permissions: list[str]
    expires_at: datetime
