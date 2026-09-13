"""Command-line frontend."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .client import LuaDebuggerClient
from .exceptions import EawLuaDebuggerError
from .pgnet import build_connect_request, parse_connect_response


def _add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="StarWarsI host address")
    parser.add_argument("--port", type=int, default=1234, help="StarWarsI Lua debug UDP port")
    parser.add_argument(
        "--local-port",
        type=int,
        default=0,
        help="local UDP source port; 0 selects a fresh port",
    )
    parser.add_argument("--client-name", default=None, help="PGNet client name")
    parser.add_argument("--timeout", type=float, default=5.0, help="operation timeout in seconds")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eaw-lua-debugger")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="show protocol progress")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scripts = subparsers.add_parser("scripts", help="connect and print the active script list")
    _add_connection_args(scripts)
    scripts.add_argument("--json", action="store_true", help="emit JSON")

    hello = subparsers.add_parser("hello-bytes", help="print the core connect request as hex")
    hello.add_argument("client_name", help="client name to encode")

    parse = subparsers.add_parser("parse-spoot", help="parse a Spoot response hex datagram")
    parse.add_argument("hex_datagram", help="raw UDP response as hexadecimal")

    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", 0))

    try:
        if args.command == "hello-bytes":
            print(build_connect_request(args.client_name).hex())
            return 0

        if args.command == "parse-spoot":
            print(parse_connect_response(bytes.fromhex(args.hex_datagram)))
            return 0

        if args.command == "scripts":
            with LuaDebuggerClient(
                args.host,
                args.port,
                local_port=args.local_port,
                client_name=args.client_name,
                timeout=args.timeout,
            ) as client:
                server_name = client.connect()
                script_list = client.request_scripts()
            if args.json:
                print(
                    json.dumps(
                        {
                            "server_name": server_name,
                            "scripts": [script.__dict__ for script in script_list],
                        },
                        indent=2,
                    )
                )
            else:
                print(f"Connected to {server_name}")
                for script in script_list:
                    print(f"{script.script_id}\t{script.full_path_name}")
            return 0

    except EawLuaDebuggerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error("unknown command")
    return 2


def _configure_logging(verbosity: int) -> None:
    if verbosity <= 0:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    elif verbosity == 1:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")


if __name__ == "__main__":
    raise SystemExit(main())
