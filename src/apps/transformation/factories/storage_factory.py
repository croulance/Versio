from apps.transformation.interfaces.storage import StorageInterface
from apps.transformation.storage.storage_adapter import StorageAdapter
from infrastructure.storage.s3_client import S3Client


class StorageFactory:
    @staticmethod
    def create() -> StorageInterface:
        return StorageAdapter(S3Client())
