"""Private local cache with optional S3 persistence. Keys never come from a browser path."""

from pathlib import Path

import boto3

from .config import settings


def local_path(key: str) -> Path:
    root = settings.data_dir.resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root) or path == root or "\\" in key:
        raise ValueError("Invalid storage key")
    return path


def client():
    return boto3.client("s3", endpoint_url=settings.s3_endpoint, region_name=settings.s3_region)


def publish(path: Path) -> str:
    key = path.resolve().relative_to(settings.data_dir.resolve()).as_posix()
    local_path(key)
    if settings.storage == "s3":
        client().upload_file(str(path), settings.s3_bucket, key)
    return key


def materialize(key: str) -> Path:
    path = local_path(key)
    if not path.is_file() and settings.storage == "s3":
        path.parent.mkdir(parents=True, exist_ok=True)
        client().download_file(settings.s3_bucket, key, str(path))
    return path


def signed_url(key: str) -> str:
    local_path(key)
    return client().generate_presigned_url(
        "get_object", Params={"Bucket": settings.s3_bucket, "Key": key}, ExpiresIn=60
    )


def erase(key: str) -> None:
    path = local_path(key)
    if settings.storage == "s3":
        client().delete_object(Bucket=settings.s3_bucket, Key=key)
    path.unlink(missing_ok=True)


def list_keys(prefix: str) -> list[str]:
    folder = local_path(prefix)
    keys = {
        p.resolve().relative_to(settings.data_dir.resolve()).as_posix()
        for p in folder.rglob("*")
        if p.is_file()
    }
    if settings.storage == "s3":
        for page in (
            client().get_paginator("list_objects_v2").paginate(Bucket=settings.s3_bucket, Prefix=prefix)
        ):
            keys.update(obj["Key"] for obj in page.get("Contents", []))
    return sorted(keys)


def aged_keys(prefix: str, cutoff):
    if settings.storage == "s3":
        for page in (
            client().get_paginator("list_objects_v2").paginate(Bucket=settings.s3_bucket, Prefix=prefix)
        ):
            for obj in page.get("Contents", []):
                if obj["LastModified"].replace(tzinfo=None) < cutoff:
                    yield obj["Key"]
    else:
        import datetime as dt

        folder = local_path(prefix)
        for path in folder.rglob("*"):
            if (
                path.is_file()
                and dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).replace(tzinfo=None) < cutoff
            ):
                yield path.resolve().relative_to(settings.data_dir.resolve()).as_posix()
