from __future__ import annotations

import argparse

from .coordinator_api import create_coordinator_server
from .regional_api import create_regional_server


def run_coordinator(args: argparse.Namespace) -> None:
    regions = [region.strip() for region in args.regions.split(",") if region.strip()]
    server, ledger = create_coordinator_server(
        host=args.host,
        port=args.port,
        database_path=args.db,
        regions=regions,
    )
    print(f"Coordinator listening on http://{args.host}:{args.port} with db={args.db}")
    print(f"Regions: {', '.join(regions)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ledger.close()
        server.server_close()


def run_regional(args: argparse.Namespace) -> None:
    server = create_regional_server(
        host=args.host,
        port=args.port,
        region=args.region,
        coordinator_url=args.coordinator,
    )
    print(
        f"Regional node '{args.region}' listening on http://{args.host}:{args.port} "
        f"and forwarding to {args.coordinator}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run distributed mobile money services")
    parser.add_argument(
        "--mode",
        choices=["coordinator", "regional"],
        default="coordinator",
        help="Service mode to run",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8081, type=int)
    parser.add_argument("--db", default="ledger.sqlite3", help="SQLite db path for coordinator mode")
    parser.add_argument(
        "--regions",
        default="kampala,mbarara,gulu,jinja",
        help="Comma-separated region list for coordinator mode",
    )
    parser.add_argument("--region", default="kampala", help="Region name for regional mode")
    parser.add_argument(
        "--coordinator",
        default="http://127.0.0.1:8081",
        help="Coordinator base URL for regional mode",
    )
    args = parser.parse_args()

    if args.mode == "coordinator":
        run_coordinator(args)
        return

    run_regional(args)


if __name__ == "__main__":
    main()
