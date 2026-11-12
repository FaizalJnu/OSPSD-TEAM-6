"""Storage backend for any S3-compatible service.

Tested with OCI Object Storage (through its S3 compatibility API), AWS S3, and
Google Cloud Storage (through its XML API). Only the endpoint URL, the region,
and the credentials change.

This is the only module that imports boto3. Every boto3 error is translated
into one of our own errors before it leaves this file.
"""

import base64
import binascii
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, BinaryIO, Self

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.response import StreamingBody

from storage_service.errors import (
    AccessDenied,
    FileNotFound,
    InvalidInput,
    ProviderError,
    ProviderUnavailable,
    StorageError,
)
from storage_service.models import FileDownload, FileInfo, FilePage

# How much to read from the provider at a time while streaming a download.
DOWNLOAD_CHUNK_BYTES = 1024 * 1024

# Error codes S3-compatible providers use for "this key does not exist".
_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
# HEAD cannot distinguish a missing key from a missing/inaccessible bucket.
_AMBIGUOUS_HEAD_NOT_FOUND_CODES = {"404", "NotFound"}
# Error codes HeadBucket returns when the configured bucket does not exist.
_MISSING_BUCKET_CODES = {"404", "NotFound", "NoSuchBucket"}
# Error codes for refused credentials or permissions. Any HTTP 403 counts too: a HEAD
# response has no body, so its code is only the status, "403".
_ACCESS_DENIED_CODES = {
    "AccessDenied",
    "AllAccessDisabled",
    "Forbidden",
    "InvalidAccessKeyId",
    "SignatureDoesNotMatch",
}


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
                # Since 1.36, boto3 sends a checksum with every upload using the
                # aws-chunked transfer encoding, which OCI rejects. Send checksums
                # only for operations that require them. These settings override
                # the AWS_*_CHECKSUM_* environment variables.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
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
            chunks=_ChunkReader(response["Body"]),
        )

    def stat(self, key: str) -> FileInfo:
        with _translate_errors(key):
            try:
                response = self._client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as err:
                # A HEAD error has no body: 404/NotFound may mean the bucket,
                # not the key. Only report a missing file if the bucket is
                # accessible. Never expose the bucket name or raw probe code.
                if _error_code(err) in _AMBIGUOUS_HEAD_NOT_FOUND_CODES:
                    try:
                        self._client.head_bucket(Bucket=self._bucket)
                    except ClientError as bucket_err:
                        if _is_access_denied(bucket_err):
                            raise AccessDenied(
                                "the storage provider denied access to the configured bucket",
                                provider_code=_error_code(bucket_err),
                            ) from bucket_err
                        raise ProviderError(
                            "the configured bucket does not exist or is not accessible",
                            provider_code=_error_code(bucket_err),
                        ) from bucket_err
                raise
        return _info_from_response(key, response)

    def check_health(self) -> None:
        with _translate_errors():
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except ClientError as err:
                # Never expose the bucket name or the raw provider code.
                if _error_code(err) in _MISSING_BUCKET_CODES:
                    raise ProviderError(
                        "the configured bucket does not exist or is not accessible",
                        provider_code=_error_code(err),
                    ) from err
                raise

    def list_files(
        self, prefix: str, limit: int, cursor: str | None, delimiter: str | None = None
    ) -> FilePage:
        request: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix, "MaxKeys": limit}
        if delimiter is not None:
            request["Delimiter"] = delimiter
        if cursor is not None:
            request["ContinuationToken"] = _decode_cursor(cursor, prefix)
        with _translate_errors():
            try:
                response = self._client.list_objects_v2(**request)
            except ClientError as err:
                # The service has already checked prefix and limit, so when a cursor
                # was sent, a rejected argument means the cursor is not one we made.
                code = _error_code(err)
                if cursor is not None and code == "InvalidArgument":
                    raise InvalidInput(_INVALID_CURSOR, provider_code=code) from err
                raise
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
        token = response.get("NextContinuationToken")
        next_cursor = None if token is None else _encode_cursor(prefix, token)
        folders = [item["Prefix"] for item in response.get("CommonPrefixes", [])]
        return FilePage(files=files, next_cursor=next_cursor, folders=folders)

    def copy(self, source_key: str, dest_key: str) -> FileInfo:
        # CopyObject copies inside the provider, so the contents never pass through this
        # service. It keeps the source's content type. AWS documents a limit of 5 GB per
        # CopyObject call; whether OCI has the same limit is not verified.
        with _translate_errors(source_key):
            self._client.copy_object(
                Bucket=self._bucket,
                Key=dest_key,
                CopySource={"Bucket": self._bucket, "Key": source_key},
            )
        return self.stat(dest_key)

    def delete(self, key: str) -> None:
        with _translate_errors():
            self._client.delete_object(Bucket=self._bucket, Key=key)

    def delete_many(self, keys: Sequence[str]) -> list[str]:
        # Quiet: the response lists only the keys that failed. DeleteObjects answers
        # 200 even when some of them did, so the list has to be read.
        # DeleteObjects requires a checksum, and OCI rejects boto3's default, CRC32.
        with _translate_errors():
            response = self._client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
                ChecksumAlgorithm="SHA256",
            )
        return [error["Key"] for error in response.get("Errors", [])]


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


class _ChunkReader:
    """Yield a download piece by piece, and always release the connection afterwards.

    Not a generator: a generator's cleanup only runs once iteration has started, so
    a download dropped before its first chunk would keep the connection open.
    """

    def __init__(self, body: StreamingBody) -> None:
        self._body = body
        self._chunks: Iterator[bytes] = body.iter_chunks(DOWNLOAD_CHUNK_BYTES)

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> bytes:
        try:
            # A connection that drops mid-read raises botocore's ResponseStreamingError
            # or ReadTimeoutError here, long after get() returned.
            with _translate_errors():
                return next(self._chunks)
        except BaseException:  # the last chunk was read, or reading failed
            self.close()
            raise

    def close(self) -> None:
        self._body.close()


# A cursor wraps the provider's continuation token with the prefix it was made for.
# Providers do not all reject a token sent with another prefix (OCI continues from the
# token's position), so this backend checks the prefix itself, as the in-memory
# backend does.
_CURSOR_MARK = "s3v1."
_INVALID_CURSOR = "cursor is not a next_cursor this API returned for this prefix"


def _encode_cursor(prefix: str, token: str) -> str:
    payload = json.dumps({"prefix": prefix, "token": token}).encode()
    return _CURSOR_MARK + base64.urlsafe_b64encode(payload).decode()


def _decode_cursor(cursor: str, prefix: str) -> str:
    """Return the provider's token inside the cursor, or raise ``InvalidInput``."""
    if not cursor.startswith(_CURSOR_MARK):
        raise InvalidInput(_INVALID_CURSOR)
    try:
        fields = json.loads(base64.urlsafe_b64decode(cursor[len(_CURSOR_MARK) :]))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidInput(_INVALID_CURSOR) from None
    if not isinstance(fields, dict) or fields.get("prefix") != prefix:
        raise InvalidInput(_INVALID_CURSOR)
    token = fields.get("token")
    if not isinstance(token, str) or not token:
        raise InvalidInput(_INVALID_CURSOR)
    return token


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
        code = _error_code(err)
        if key is not None and code in _NOT_FOUND_CODES:
            raise FileNotFound(f"no file named {key!r}", provider_code=code) from err
        raise _rejection(err) from err
    except BotoCoreError as err:
        raise ProviderUnavailable(
            "could not reach the storage provider", provider_code=type(err).__name__
        ) from err


def _rejection(err: ClientError) -> StorageError:
    """Our error for a provider rejection that does not mean a missing file.

    The provider's code goes to ``provider_code`` for the logs, not into the message:
    callers should not depend on one provider's error names.
    """
    code = _error_code(err)
    if _is_access_denied(err):
        return AccessDenied("the storage provider denied access", provider_code=code)
    return ProviderError("the storage provider rejected the request", provider_code=code)


def _is_access_denied(err: ClientError) -> bool:
    status = err.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return status == 403 or _error_code(err) in _ACCESS_DENIED_CODES


def _error_code(err: ClientError) -> str:
    return str(err.response.get("Error", {}).get("Code", "unknown"))
