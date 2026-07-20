from typing import BinaryIO

from botocore.exceptions import ClientError

from apps.transformation.interfaces.storage import (ObjectNotFoundError,
                                                    StorageInterface)
from infrastructure.storage.s3_client import S3Client


class StorageAdapter(StorageInterface):
    """
    Application-layer adapter over S3Client.
    Business code depends on this interface, never on boto3/S3 directly.
    """

    def __init__(self, client: S3Client):
        self._client = client

    def get_object(self, key: str) -> BinaryIO:
        try:
            return self._client.get_object(key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                raise ObjectNotFoundError(key) from exc
            raise

    def put_object(self, key: str, body: bytes) -> None:
        self._client.put_object(key, body)

    def upload_stream(self, key: str, file_stream: BinaryIO) -> None:
        self._client.upload_stream(key, file_stream)

    def list_keys(self, prefix: str) -> list[str]:
        return self._client.list_keys(prefix)

    def exists(self, key: str) -> bool:
        return self._client.exists(key)
