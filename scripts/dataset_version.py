"""DVC-compatible directory pointer generation/verification without pickle/cache dependencies.

This supports local directory pointers only, not DVC remote checkout/push.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

import yaml


def snapshot(directory: Path) -> tuple[str, int, list]:
    rows, size = [], 0
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not accepted in versioned datasets")
        if path.is_file():
            data = path.read_bytes()
            size += len(data)
            rows.append(
                {
                    "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(),
                    "relpath": path.relative_to(directory).as_posix(),
                }
            )
    digest = (
        hashlib.md5(json.dumps(rows, sort_keys=True).encode(), usedforsecurity=False).hexdigest() + ".dir"
    )
    return digest, size, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pointer", type=Path)
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    if args.directory:
        digest, size, rows = snapshot(args.directory)
        relative = os.path.relpath(args.directory, args.pointer.parent).replace("\\", "/")
        args.pointer.write_text(
            yaml.safe_dump(
                {
                    "outs": [
                        {"md5": digest, "size": size, "nfiles": len(rows), "hash": "md5", "path": relative}
                    ]
                }
            )
        )
        print(f"Wrote {args.pointer} ({len(rows)} files). No data or pickle cache copied.")
    else:
        record = yaml.safe_load(args.pointer.read_text())["outs"][0]
        digest, size, rows = snapshot(args.pointer.parent / record["path"])
        if digest != record["md5"] or size != record["size"] or len(rows) != record["nfiles"]:
            raise SystemExit("Dataset differs from the recorded pointer")
        print(f"Verified {args.pointer}: {len(rows)} files")


if __name__ == "__main__":
    main()
