"""Create the private storage bucket if it does not exist (FR-UPL-3, NFR-8).

Runs on every start of the one-shot ``migrate`` service, so it must be
idempotent: an existing bucket is not an error. It also removes any bucket
policy, because the bucket must never allow anonymous access; objects are read
only by the worker and through short-lived presigned URLs.

This replaces the ``minio-init`` service with ``mc mb`` from the SDD (H14): the
``minio/mc`` image is no longer published and the Chainguard MinIO image has no
shell. A Django command is testable and independent of the storage vendor.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from botocore.exceptions import ConnectionError as BotoConnectionError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_ALREADY_EXISTS = frozenset({"BucketAlreadyOwnedByYou", "BucketAlreadyExists"})
_NO_POLICY = frozenset({"NoSuchBucketPolicy"})


def storage_client() -> S3Client:
    """S3 client for the internal endpoint (the one containers can reach)."""
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _error_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


def wait_for_storage(client: S3Client, timeout_s: float, interval_s: float = 1.0) -> None:
    """Block until storage answers, or raise ``CommandError`` after ``timeout_s``.

    The MinIO image has no shell or curl, so compose cannot healthcheck it;
    the one-shot ``migrate`` service waits here instead.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            client.list_buckets()
            return
        except (BotoConnectionError, ClientError) as error:
            if isinstance(error, ClientError) and _status(error) < 500:
                raise
            if time.monotonic() >= deadline:
                raise CommandError(
                    f"Storage not reachable at {settings.S3_ENDPOINT} after {timeout_s:g} s."
                ) from error
            time.sleep(interval_s)


def _status(error: ClientError) -> int:
    return int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))


def ensure_bucket(client: S3Client, bucket: str) -> bool:
    """Create ``bucket`` unless it exists and strip any policy. Return True if created."""
    created = True
    try:
        client.create_bucket(Bucket=bucket)
    except ClientError as error:
        if _error_code(error) not in _ALREADY_EXISTS:
            raise
        created = False

    try:
        client.delete_bucket_policy(Bucket=bucket)
    except ClientError as error:
        if _error_code(error) not in _NO_POLICY:
            raise
    return created


class Command(BaseCommand):
    help = "Create the private storage bucket if it does not exist (idempotent)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--wait",
            type=float,
            default=0,
            help="Seconds to keep retrying while storage is starting (default: 0, no retry).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        bucket = settings.S3_BUCKET
        client = storage_client()
        wait_for_storage(client, options["wait"])
        created = ensure_bucket(client, bucket)
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created private bucket '{bucket}'."))
        else:
            self.stdout.write(f"Bucket '{bucket}' already exists; policy cleared.")
