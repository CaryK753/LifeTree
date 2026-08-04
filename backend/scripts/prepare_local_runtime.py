"""Prepare and report the future desktop local-runtime directories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.local_storage import prepare_local_storage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args()

    paths = prepare_local_storage(args.data_dir)
    print(
        json.dumps(
            {
                "storage_foundation": "ready",
                "paths": paths.as_serializable_dict(),
                "adapters": {
                    "database": "ready_sqlite_migrations_encrypted",
                    "objects": "ready_filesystem_adapter",
                    "graph": "ready_sqlite_edges",
                    "jobs": "ready_in_process_runner",
                    "vectors": "ready_in_process_cosine",
                    "desktop_bundle": "ready_sidecar_static_ui",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
