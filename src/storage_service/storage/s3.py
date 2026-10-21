"""Storage backend for any S3-compatible service.

Works with OCI Object Storage (through its S3 compatibility API), AWS S3,
Garage, MinIO, Cloudflare R2, and similar services. Only the endpoint URL and
the credentials change.

This is the only module that imports boto3. Every boto3 error is translated
into one of our own errors before it leaves this file.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.response import StreamingBody

from storage_service.errors import FileNotFound, ProviderError, ProviderUnavailable
from storage_service.models import FileDownload, FileInfo, FilePage

# How much to read from the provider at a time while streaming a download.
DOWNLOAD_CHUNK_BYTES = 1024 * 1024

# Error codes S3-compatible providers use for "this key does not exist".
_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
# HEAD cannot distinguish a missing key from a missing/inaccessible bucket.
_AMBIGUOUS_HEAD_NOT_FOUND_CODES = {"404", "NotFound"}


class S3Storage:
    def __init__(
        self,
        *,
        endpoint: str,
        region: str,
        bucket: str,
        access_key: str,
        secret_key: str,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                # Put the bucket in the URL path (https://host/bucket/key) instead
                # of the hostname. Every S3-compatible provider supports this style.
                s3={"addressing_style": "path"},
                retries={"mode": "standard", "max_attempts": 3},
                connect_timeout=5,
                read_timeout=60,
            ),
        )

    def put(self, key: str, stream: BinaryIO, content_type: str) -> FileInfo:
        # upload_fileobj reads the stream in parts (8 MB by default) and switches
        # to a multipart upload for large files, so memory use stays flat.
        with _translate_errors():
            self._client.upload_fileobj(
                stream, self._bucket, key, ExtraArgs={"ContentType": content_type}
            )
        return self.stat(key)

    def get(self, key: str) -> FileDownload:
        with _translate_errors(key):
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        return FileDownload(
            info=_info_from_response(key, response),
            chunks=_read_in_chunks(response["Body"]),
        )

    def stat(self, key: str) -> FileInfo:
        with _translate_errors(key):
            try:
                response = self._client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as err:
                # A HEAD error has no body: 404/NotFound may mean the bucket,
                # not the key. Only report a missing file if the bucket is
                # accessible. Never expose the bucket name or raw probe code.
                if err.response.get("Error", {}).get("Code") in _AMBIGUOUS_HEAD_NOT_FOUND_CODES:
                    try:
                        self._client.head_bucket(Bucket=self._bucket)
                    except ClientError as bucket_err:
                        raise ProviderError(
                            "the configured bucket does not exist or is not accessible"
                        ) from bucket_err
                raise
        return _info_from_response(key, response)

    def list_files(self, prefix: str, limit: int, cursor: str | None) -> FilePage:
        request: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix, "MaxKeys": limit}
        if cursor is not None:
            request["ContinuationToken"] = cursor
        with _translate_errors():
            response = self._client.list_objects_v2(**request)
        files = [
            FileInfo(
                key=item["Key"],
                size=item["Size"],
                content_type=None,  # list_objects_v2 does not return it
                etag=_clean_etag(item["ETag"]),
                last_modified=item["LastModified"],
            )
            for item in response.get("Contents", [])
        ]
        return FilePage(files=files, next_cursor=response.get("NextContinuationToken"))

    def delete(self, key: str) -> None:
        with _translate_errors():
            self._client.delete_object(Bucket=self._bucket, Key=key)


def _info_from_response(key: str, response: dict[str, Any]) -> FileInfo:
    """Build a FileInfo from a head_object or get_object response."""
    return FileInfo(
        key=key,
        size=response["ContentLength"],
        content_type=response.get("ContentType"),
        etag=_clean_etag(response["ETag"]),
        last_modified=response["LastModified"],
    )


def _clean_etag(etag: str) -> str:
    """S3 wraps ETags in double quotes; strip them."""
    return etag.strip('"')


def _read_in_chunks(body: StreamingBody) -> Iterator[bytes]:
    """Yield a download piece by piece, and always release the connection afterwards."""
    try:
        yield from body.iter_chunks(DOWNLOAD_CHUNK_BYTES)
    finally:
        body.close()


@contextmanager
def _translate_errors(key: str | None = None) -> Iterator[None]:
    """Turn boto3 exceptions raised inside the ``with`` block into our own errors.

    Pass ``key`` when "not found" from the provider means the file is missing.
    Without it, "not found" is treated as a provider problem (for example, a
    bucket that does not exist).
    """
    try:
        yield
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "unknown")
        if key is not None and code in _NOT_FOUND_CODES:
            raise FileNotFound(f"no file named {key!r}") from err
        raise ProviderError(f"storage provider rejected the request ({code})") from err
    except BotoCoreError as err:
        raise ProviderUnavailable("could not reach the storage provider") from err
