"""FR-UPL-3, NFR-8: ensure_bucket creates a private bucket and is idempotent.

Needs a running MinIO reachable at S3_ENDPOINT. Each test uses its own bucket,
removed afterwards, so the development bucket is never touched.
"""

import json
from collections.abc import Iterator
from io import StringIO
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings

from sift.storage.management.commands.ensure_bucket import storage_client

pytestmark = pytest.mark.integration


@pytest.fixture
def bucket() -> Iterator[str]:
    name = f"sift-test-{uuid4().hex[:12]}"
    with override_settings(S3_BUCKET=name):
        yield name
    client = storage_client()
    try:
        for item in client.list_objects_v2(Bucket=name).get("Contents", []):
            client.delete_object(Bucket=name, Key=item["Key"])
        client.delete_bucket(Bucket=name)
    except ClientError:
        pass


def run_ensure_bucket() -> str:
    out = StringIO()
    call_command("ensure_bucket", stdout=out)
    return out.getvalue()


def assert_no_policy(bucket: str) -> None:
    with pytest.raises(ClientError) as error:
        storage_client().get_bucket_policy(Bucket=bucket)
    assert error.value.response["Error"]["Code"] == "NoSuchBucketPolicy"


def test_creates_the_bucket_when_missing(bucket: str) -> None:
    assert "Created private bucket" in run_ensure_bucket()

    storage_client().head_bucket(Bucket=bucket)


def test_running_twice_is_not_an_error(bucket: str) -> None:
    run_ensure_bucket()

    assert "already exists" in run_ensure_bucket()


def test_new_bucket_has_no_policy(bucket: str) -> None:
    run_ensure_bucket()

    assert_no_policy(bucket)


def test_an_existing_public_policy_is_removed(bucket: str) -> None:
    run_ensure_bucket()
    public_read = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            }
        ],
    }
    storage_client().put_bucket_policy(Bucket=bucket, Policy=json.dumps(public_read))

    run_ensure_bucket()

    assert_no_policy(bucket)


def test_anonymous_reads_are_refused(bucket: str) -> None:
    run_ensure_bucket()
    storage_client().put_object(Bucket=bucket, Key="probe.csv", Body=b"sku\n")

    with pytest.raises(HTTPError) as error:
        urlopen(f"{settings.S3_ENDPOINT}/{bucket}/probe.csv", timeout=5)  # noqa: S310

    assert error.value.code == 403
