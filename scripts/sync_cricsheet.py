"""Download the latest Cricsheet data and sync it to a Backblaze B2 bucket.

Usage:
    python scripts/sync_cricsheet.py recent   # last 7 days of matches (daily run)
    python scripts/sync_cricsheet.py all      # full all_json.zip (first run / weekly)

Required environment variables:
    B2_KEY_ID, B2_APP_KEY, B2_BUCKET, B2_ENDPOINT, B2_REGION
"""
import hashlib
import io
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timezone

import boto3
import requests
from botocore.exceptions import ClientError

BASE_URL = "https://cricsheet.org/downloads/"
MODES = {
    "recent": "recently_added_7_json.zip",
    "all": "all_json.zip",
}
HEADERS = {"User-Agent": "CricValue-updater/1.0 (personal project)"}

COMPETITIONS = {
    "indian premier league": "ipl",
    "big bash league": "bbl",
    "pakistan super league": "psl",
}
MATCH_TYPES = {
    "T20": "t20",
    "IT20": "t20",
    "ODI": "odi",
    "ODM": "odi",
    "Test": "test",
    "MDM": "test",
}


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["B2_ENDPOINT"],
        region_name=os.environ["B2_REGION"],
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APP_KEY"],
    )


def download(url, retries=3):
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=300)
            r.raise_for_status()
            return r.content
        except requests.RequestException as exc:
            print(f"Download attempt {attempt} failed: {exc}")
            if attempt == retries:
                raise
            time.sleep(5 * attempt)


def read_json(s3, bucket, key, default):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read())
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return default
        raise


def put_json(s3, bucket, key, data):
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, indent=2).encode(),
        ContentType="application/json",
    )


def existing_match_files(s3, bucket):
    """One paginated listing is cheaper than a HEAD request per file."""
    names = set()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="matches/"):
        for item in page.get("Contents", []):
            names.add(item["Key"].rsplit("/", 1)[-1])
    return names


def folder_for(info):
    event = (info.get("event") or {}).get("name", "").lower()
    for needle, folder in COMPETITIONS.items():
        if needle in event:
            return folder
    return MATCH_TYPES.get(info.get("match_type"), "other")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "recent"
    if mode not in MODES:
        sys.exit(f"Unknown mode '{mode}'. Use: {', '.join(MODES)}")

    bucket = os.environ["B2_BUCKET"]
    s3 = s3_client()
    filename = MODES[mode]
    now = datetime.now(timezone.utc)

    print(f"Downloading {filename} ...")
    data = download(BASE_URL + filename)
    digest = hashlib.sha256(data).hexdigest()
    print(f"Downloaded {len(data) / 1_000_000:.1f} MB, sha256 {digest[:12]}")

    last_sync = read_json(s3, bucket, "metadata/last_sync.json", {})
    if last_sync.get(f"sha256_{mode}") == digest:
        print("No change since last sync. Nothing to upload.")
        return

    # 1. Keep the raw archive.
    if mode == "all":
        archive_key = "raw/cricsheet/all_json.zip"
    else:
        archive_key = f"raw/cricsheet/updates/{now:%Y-%m-%d}_{filename}"
    s3.put_object(Bucket=bucket, Key=archive_key, Body=data)
    print(f"Uploaded archive -> {archive_key}")

    # 2. Upload only new match files, sorted into folders.
    known = existing_match_files(s3, bucket)
    new_files, skipped, failed = 0, 0, 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            base = name.rsplit("/", 1)[-1]
            if base in known:
                skipped += 1
                continue
            try:
                raw = zf.read(name)
                folder = folder_for(json.loads(raw).get("info", {}))
                s3.put_object(
                    Bucket=bucket,
                    Key=f"matches/{folder}/{base}",
                    Body=raw,
                    ContentType="application/json",
                )
                new_files += 1
            except Exception as exc:  # keep going; report at the end
                failed += 1
                print(f"Failed {name}: {exc}")

    print(f"New: {new_files}, already stored: {skipped}, failed: {failed}")

    # 3. Manifests and status.
    manifest = {
        "synced_at": now.isoformat(),
        "mode": mode,
        "source": BASE_URL + filename,
        "sha256": digest,
        "archive_key": archive_key,
        "new_match_files": new_files,
        "already_stored": skipped,
        "failed": failed,
    }
    put_json(s3, bucket, "manifests/latest.json", manifest)
    put_json(s3, bucket, f"manifests/history/{now:%Y%m%dT%H%M%SZ}_{mode}.json", manifest)

    last_sync[f"sha256_{mode}"] = digest
    last_sync["last_sync"] = now.isoformat()
    last_sync["last_mode"] = mode
    put_json(s3, bucket, "metadata/last_sync.json", last_sync)

    if failed:
        sys.exit(1)  # make the GitHub Actions run show as failed


if __name__ == "__main__":
    main()
