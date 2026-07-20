from rest_framework.request import Request
from rest_framework.response import Response

from apps.transformation.repositories.supplier_repository import \
    SupplierRepository
from apps.transformation.views.base import InternalAPIView


class SupplierListView(InternalAPIView):
    def get(self, request: Request) -> Response:
        suppliers = SupplierRepository().get_all()
        return Response(
            [
                {
                    "id": s.id,
                    "name": s.name,
                    "supplier_account_id": s.supplier_account_id,
                }
                for s in suppliers
            ]
        )
