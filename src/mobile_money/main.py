from __future__ import annotations

import argparse

from .coordinator_api import create_coordinator_server
from .gateway_api import create_gateway_server
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
    coordinator_urls = [
        url.strip() for url in (args.coordinators.split(",") if args.coordinators else [args.coordinator]) if url.strip()
    ]
    server = create_regional_server(
        host=args.host,
        port=args.port,
        region=args.region,
        coordinator_url=args.coordinator,
        coordinator_urls=coordinator_urls,
    )
    print(
        f"Regional node '{args.region}' listening on http://{args.host}:{args.port} "
        f"and forwarding to coordinators: {', '.join(coordinator_urls)}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def run_gateway(args: argparse.Namespace) -> None:
    regional_node_urls = [url.strip() for url in args.regional_nodes.split(",") if url.strip()]
    coordinator_urls = [url.strip() for url in args.coordinator_urls.split(",") if url.strip()]

    if not regional_node_urls:
        raise ValueError("At least one regional node URL is required (--regional-nodes)")
    if not coordinator_urls:
        raise ValueError("At least one coordinator URL is required (--coordinator-urls)")

    server = create_gateway_server(
        host=args.host,
        port=args.port,
        regional_node_urls=regional_node_urls,
        coordinator_urls=coordinator_urls,
    )
    print(f"Gateway load-balancer listening on http://{args.host}:{args.port}")
    print(f"Regional nodes: {', '.join(regional_node_urls)}")
    print(f"Coordinators: {', '.join(coordinator_urls)}")
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
        choices=["coordinator", "regional", "gateway"],
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
    parser.add_argument(
        "--coordinators",
        default="",
        help="Optional comma-separated coordinator URLs for shard routing in regional mode",
    )
    parser.add_argument(
        "--regional-nodes",
        default="",
        help="Comma-separated regional node URLs for gateway mode",
    )
    parser.add_argument(
        "--coordinator-urls",
        default="",
        help="Comma-separated coordinator URLs for gateway mode",
    )
    args = parser.parse_args()

    if args.mode == "coordinator":
        run_coordinator(args)
        return

    if args.mode == "gateway":
        run_gateway(args)
        return

    run_regional(args)


if __name__ == "__main__":
    main()
