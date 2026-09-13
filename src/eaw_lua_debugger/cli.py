"""Command-line frontend."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .client import CONTROL_MESSAGES, LuaDebuggerClient
from .exceptions import EawLuaDebuggerError
from .pgnet import build_connect_request, parse_connect_response
from .session import run_diagnostic_session


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

    threads = subparsers.add_parser("threads", help="connect and print threads for a script")
    _add_connection_args(threads)
    threads.add_argument("script_id", type=int)
    threads.add_argument("--json", action="store_true", help="emit JSON")

    attach = subparsers.add_parser("attach", help="attach to a script and print child scripts")
    _add_connection_args(attach)
    attach.add_argument("script_id", type=int)
    attach.add_argument("--json", action="store_true", help="emit JSON")

    control = subparsers.add_parser("control", help="send an execution-control command")
    _add_connection_args(control)
    control.add_argument("control_command", choices=sorted(CONTROL_MESSAGES))

    session = subparsers.add_parser("session", help="connect and service a diagnostic session")
    _add_connection_args(session)
    session.add_argument("--script-id", type=int, default=None)
    session.add_argument("--duration", type=float, default=30.0)

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

        if args.command == "threads":
            with LuaDebuggerClient(
                args.host,
                args.port,
                local_port=args.local_port,
                client_name=args.client_name,
                timeout=args.timeout,
            ) as client:
                server_name = client.connect()
                thread_list = client.request_threads(args.script_id)
            if args.json:
                print(
                    json.dumps(
                        {
                            "server_name": server_name,
                            "script_id": args.script_id,
                            "threads": [thread.__dict__ for thread in thread_list],
                        },
                        indent=2,
                    )
                )
            else:
                print(f"Connected to {server_name}")
                for thread in thread_list:
                    print(f"{thread.thread_index}\t{thread.thread_name}")
            return 0

        if args.command == "attach":
            with LuaDebuggerClient(
                args.host,
                args.port,
                local_port=args.local_port,
                client_name=args.client_name,
                timeout=args.timeout,
            ) as client:
                server_name = client.connect()
                child_names = client.attach_script(args.script_id)
            if args.json:
                print(
                    json.dumps(
                        {
                            "server_name": server_name,
                            "script_id": args.script_id,
                            "child_script_names": child_names,
                        },
                        indent=2,
                    )
                )
            else:
                print(f"Connected to {server_name}")
                for child_name in child_names:
                    print(child_name)
            return 0

        if args.command == "control":
            with LuaDebuggerClient(
                args.host,
                args.port,
                local_port=args.local_port,
                client_name=args.client_name,
                timeout=args.timeout,
            ) as client:
                server_name = client.connect()
                client.send_control(args.control_command)
            print(f"Sent {args.control_command} to {server_name}")
            return 0

        if args.command == "session":
            with LuaDebuggerClient(
                args.host,
                args.port,
                local_port=args.local_port,
                client_name=args.client_name,
                timeout=args.timeout,
            ) as client:
                server_name = client.connect()
                result = run_diagnostic_session(
                    client,
                    script_id=args.script_id,
                    duration=args.duration,
                )
            print(f"Connected to {server_name}")
            print(f"scripts: {len(result['scripts'])}")
            print(f"child scripts: {len(result['child_script_names'])}")
            print(f"threads: {len(result['threads'])}")
            print(f"messages: {len(result['messages'])}")
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
