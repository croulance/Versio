import binascii
import os

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone


class TransformationSupplier(models.Model):
    """Read-only view of the transformation supplier table — unmanaged, no migration generated."""

    name = models.CharField(max_length=255)
    supplier_account_id = models.IntegerField()

    class Meta:
        managed = False
        db_table = "supplier"
        app_label = "supplier_auth"


class Permission(models.Model):
    """Atomic right that can be assigned to a group."""

    codename = models.CharField(
        max_length=100, unique=True, help_text="e.g. mapping.edit"
    )
    label = models.CharField(max_length=255)

    class Meta:
        db_table = "supplier_permission"
        app_label = "supplier_auth"
        ordering = ["codename"]

    def __str__(self):
        return f"{self.codename} — {self.label}"


class SupplierGroup(models.Model):
    """Named collection of permissions assigned to one or more suppliers."""

    name = models.CharField(max_length=150, unique=True)
    permissions = models.ManyToManyField(
        Permission,
        blank=True,
        related_name="groups",
        help_text="Rights granted to members of this group.",
    )

    class Meta:
        db_table = "supplier_group"
        app_label = "supplier_auth"
        ordering = ["name"]

    def __str__(self):
        return self.name


class SupplierAuth(models.Model):
    """
    Lightweight auth entity for a supplier user.
    Not a Django user — no session framework, no contrib.auth dependency.
    supplier_id is a soft FK to transformation.Supplier (same DB, no constraint).
    """

    supplier_id = models.IntegerField(
        db_index=True,
        help_text="Soft FK to transformation.Supplier — same DB, no DB constraint.",
    )
    email = models.EmailField(unique=True)
    password = models.CharField(
        max_length=255, help_text="Django PBKDF2 hash via make_password."
    )
    is_active = models.BooleanField(default=True)
    groups = models.ManyToManyField(SupplierGroup, blank=True, related_name="members")
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "supplier_auth"
        app_label = "supplier_auth"

    def __str__(self):
        return self.email

    def set_password(self, raw_password: str) -> None:
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.password)

    @property
    def permission_codenames(self) -> set[str]:
        return {
            p.codename
            for g in self.groups.prefetch_related("permissions")
            for p in g.permissions.all()
        }


class SupplierAuthToken(models.Model):
    """
    Token-based authentication mapping for SupplierAuth entities.
    Mimics standard DRF tokens but is completely decoupled from django.contrib.auth.
    Opaque, DB-backed, and revocable — the dashboard session carries this key,
    never the underlying credentials.
    """

    key = models.CharField(max_length=40, primary_key=True)
    supplier_auth = models.ForeignKey(
        "SupplierAuth",  # Links directly to your custom model
        on_delete=models.CASCADE,
        related_name="auth_tokens",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "supplier_auth_token"
        app_label = "supplier_auth"

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = self.generate_key()
        return super().save(*args, **kwargs)

    @classmethod
    def generate_key(cls) -> str:
        """Generates a secure, random 40-character hex string."""
        return binascii.hexlify(os.urandom(20)).decode()

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def __str__(self):
        return f"Token for {self.supplier_auth.email}"
