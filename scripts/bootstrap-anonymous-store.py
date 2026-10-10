"""Run explicitly while the backend is stopped; never called by runtime startup."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.anonymous_session import bootstrap  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--mount-path", default="")
    parser.add_argument("--mount-source", default="")
    args = parser.parse_args()
    print(
        bootstrap(
            Path(args.storage),
            Path(args.reference),
            development=args.development,
            mount_path=args.mount_path,
            mount_source=args.mount_source,
        )
    )
