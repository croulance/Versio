import datetime

from django.db import transaction
from django.db.models import OuterRef, Q, QuerySet, Subquery
from django.utils import timezone

from apps.supplier_auth.dtos.auth import IssuedToken, SupplierIdentity
from apps.supplier_auth.models import (SupplierAuth, SupplierAuthToken,
                                       TransformationSupplier)


class AuthRepository:
    def login(
        self, email: str, password: str, ttl: datetime.timedelta
    ) -> IssuedToken | None:
        """Verifies credentials, touches last_login, and issues a fresh token — or
        None if the email is unknown/inactive or the password doesn't match."""
        auth = self._get_active_by_email(email)
        if auth is None or not auth.check_password(password):
            return None
        auth.last_login = timezone.now()
        auth.save(update_fields=["last_login"])
        return self._issue_token(auth.id, ttl)

    def refresh(self, token_key: str, ttl: datetime.timedelta) -> IssuedToken | None:
        """Exchanges a still-valid token for a new one, or None if it's unknown/expired."""
        existing = self._find_by_token_key(token_key)
        if existing is None or existing.is_expired():
            return None
        return self._issue_token(existing.supplier_auth_id, ttl)

    def introspect(self, token_key: str) -> SupplierIdentity | None:
        """Resolves a still-valid token to the identity it carries, or None."""
        existing = self._find_by_token_key(token_key)
        if existing is None or existing.is_expired():
            return None
        auth = existing.supplier_auth
        return SupplierIdentity(
            supplier_id=auth.supplier_id,
            supplier_account_id=self.get_supplier_account_id(auth.supplier_id),
            email=auth.email,
            groups=self.get_group_names(auth),
            permissions=sorted(auth.permission_codenames),
            expires_at=existing.expires_at,
        )

    def annotate_supplier_name(self, queryset: QuerySet) -> QuerySet:
        name_sq = TransformationSupplier.objects.filter(
            id=OuterRef("supplier_id")
        ).values("name")[:1]
        return queryset.annotate(_supplier_name=Subquery(name_sq))

    def get_supplier_ids_by_name(self, name: str) -> list[int]:
        return list(
            TransformationSupplier.objects.filter(name__icontains=name).values_list(
                "id", flat=True
            )
        )

    @staticmethod
    def get_group_names(auth: SupplierAuth) -> list[str]:
        return [g.name for g in auth.groups.all()]

    def get_supplier_account_id(self, supplier_id: int) -> int | None:
        try:
            return TransformationSupplier.objects.values_list(
                "supplier_account_id", flat=True
            ).get(pk=supplier_id)
        except TransformationSupplier.DoesNotExist:
            return None

    def search_suppliers_by_name(self, term: str, limit: int = 20) -> QuerySet:
        return TransformationSupplier.objects.filter(name__icontains=term).order_by(
            "name"
        )[:limit]

    def search_by_email_or_supplier_ids(
        self, queryset: QuerySet, term: str, supplier_ids: list[int]
    ) -> QuerySet:
        q = Q(email__icontains=term)
        if supplier_ids:
            q |= Q(supplier_id__in=supplier_ids)
        return queryset.filter(q)

    # ── private: ORM access stays here, never leaks past this class ─────────────

    @staticmethod
    def _get_active_by_email(email: str) -> SupplierAuth | None:
        try:
            return SupplierAuth.objects.prefetch_related("groups__permissions").get(
                email=email, is_active=True
            )
        except SupplierAuth.DoesNotExist:
            return None

    @staticmethod
    def _issue_token(supplier_auth_id: int, ttl: datetime.timedelta) -> IssuedToken:
        """
        Force-rotates a token by deleting any existing ones and issuing a brand new one.
        Single active token per supplier — logging in elsewhere invalidates prior sessions.
        Wrapped in a transaction to guarantee atomic execution.
        """
        with transaction.atomic():
            SupplierAuthToken.objects.filter(supplier_auth_id=supplier_auth_id).delete()
            token = SupplierAuthToken.objects.create(
                supplier_auth_id=supplier_auth_id,
                expires_at=timezone.now() + ttl,
            )
        return IssuedToken(key=token.key, expires_at=token.expires_at)

    @staticmethod
    def _find_by_token_key(key: str) -> SupplierAuthToken | None:
        """
        Fetches a token and pre-fetches the attached supplier plus its groups/permissions.
        """
        try:
            return (
                SupplierAuthToken.objects.select_related("supplier_auth")
                .prefetch_related("supplier_auth__groups__permissions")
                .get(key=key)
            )
        except SupplierAuthToken.DoesNotExist:
            return None
