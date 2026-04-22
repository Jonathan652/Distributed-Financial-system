from __future__ import annotations

import time
from typing import Iterable


def print_service_banner(title: str, rows: Iterable[tuple[str, str]]) -> None:
    width = 76
    line = "=" * width
    print("\n" + line)
    print(f"{title:^{width}}")
    print(line)
    for key, value in rows:
        print(f"{key:<20}: {value}")
    print(line)


def format_request_log(service: str, client_ip: str, request_line: str, status: str) -> str:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    return f"[{timestamp}] [{service}] {client_ip:<15} | {status:<3} | {request_line}"
