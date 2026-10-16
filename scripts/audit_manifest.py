"""Export or verify a signed audit manifest using the configured application secret."""

import argparse
from pathlib import Path

from sentinel.audit import export_manifest, verify_manifest

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "verify"])
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if args.action == "export":
        if args.manifest.exists():
            parser.error("Use a new destination to preserve the previous anchor")
        export_manifest(args.manifest)
        print("Manifest exported; preserve it in separately protected storage")
    else:
        print(verify_manifest(args.manifest), "audit files verified")
