from apps.transformation.interfaces.repository import \
    SupplierRepositoryInterface
from apps.transformation.models import Supplier


class SupplierRepository(SupplierRepositoryInterface):

    def get_all(self) -> list:
        return list(Supplier.objects.all())

    def get_or_create(self, supplier_account_id: int, name: str) -> tuple:
        return Supplier.objects.get_or_create(
            supplier_account_id=supplier_account_id,
            defaults={"name": name},
        )

    def get_by_account_id(self, supplier_account_id: int) -> Supplier | None:
        try:
            return Supplier.objects.get(supplier_account_id=supplier_account_id)
        except Supplier.DoesNotExist:
            return None
