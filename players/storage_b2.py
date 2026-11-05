"""Small Backblaze B2 helper (S3-compatible). boto3 is imported lazily so the
site still starts on a machine that has no B2 settings.

Environment variables: B2_KEY_ID, B2_APP_KEY, B2_BUCKET, B2_ENDPOINT, B2_REGION (optional).
"""
import json
import os

_client = None


def configured():
    return all(os.environ.get(k) for k in ("B2_KEY_ID", "B2_APP_KEY", "B2_BUCKET", "B2_ENDPOINT"))


def bucket():
    return os.environ["B2_BUCKET"]


def client():
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        endpoint = os.environ["B2_ENDPOINT"]
        # https://s3.us-east-005.backblazeb2.com -> us-east-005
        region = os.environ.get("B2_REGION") or endpoint.split("//")[-1].split(".")[1]
        _client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=os.environ["B2_KEY_ID"],
            aws_secret_access_key=os.environ["B2_APP_KEY"],
            config=Config(connect_timeout=5, read_timeout=120, retries={"max_attempts": 3}),
        )
    return _client


def list_objects(prefix):
    """Yield {'Key', 'LastModified', 'Size'} for every object under prefix."""
    paginator = client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket(), Prefix=prefix):
        yield from page.get("Contents", [])


def get_bytes(key):
    return client().get_object(Bucket=bucket(), Key=key)["Body"].read()


def get_json(key, default=None):
    from botocore.exceptions import ClientError

    try:
        return json.loads(get_bytes(key))
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return default
        raise


def put_json(key, data):
    client().put_object(
        Bucket=bucket(), Key=key,
        Body=json.dumps(data, indent=2).encode(), ContentType="application/json")
