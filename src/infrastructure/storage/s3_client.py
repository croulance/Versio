import boto3
from boto3.s3.transfer import TransferConfig
from django.conf import settings

# Single-request uploads shouldn't spawn their own thread pool on top of the
# request-handling thread — under concurrent submissions that compounds into
# far more threads than the process can usefully run at once.
_UPLOAD_CONFIG = TransferConfig(use_threads=False)


class S3Client:
    """
    Generic S3 infrastructure client.
    Knows nothing about the domain — only keys, bytes, and streams.
    """

    def __init__(self):
        kwargs = dict(
            region_name=settings.AWS_S3_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        if settings.AWS_S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL
        self._client = boto3.client("s3", **kwargs)
        self._bucket = settings.AWS_S3_BUCKET

    def get_object(self, key: str):
        return self._client.get_object(Bucket=self._bucket, Key=key)["Body"]

    def put_object(self, key: str, body: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=body)

    def upload_stream(self, key: str, file_stream) -> None:
        self._client.upload_fileobj(
            file_stream, self._bucket, key, Config=_UPLOAD_CONFIG
        )

    def list_keys(self, prefix: str) -> list[str]:
        # list_objects_v2 caps a single response at 1000 keys -- a bare call
        # silently truncates anything past that (no error, no warning), which
        # for MergeService means a large job's merge silently drops chunks
        # instead of failing loudly. The built-in paginator follows
        # ContinuationToken/IsTruncated so every key is returned regardless
        # of how many pages that takes.
        paginator = self._client.get_paginator("list_objects_v2")
        return [
            obj["Key"]
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix)
            for obj in page.get("Contents", [])
        ]

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except self._client.exceptions.ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise
