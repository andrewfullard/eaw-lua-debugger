"""Command-line frontend."""

from __future__ import annotations

import argparse
import logging
import sys

from ..core.exceptions import EawLuaDebuggerError
from ..debugger.client import CONTROL_MESSAGES
from . import commands


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
    scripts.set_defaults(handler=commands.scripts)

    threads = subparsers.add_parser("threads", help="connect and print threads for a script")
    _add_connection_args(threads)
    threads.add_argument("script_id", type=int)
    threads.add_argument("--json", action="store_true", help="emit JSON")
    threads.set_defaults(handler=commands.threads)

    attach = subparsers.add_parser("attach", help="attach to a script and print child scripts")
    _add_connection_args(attach)
    attach.add_argument("script_id", type=int)
    attach.add_argument("--json", action="store_true", help="emit JSON")
    attach.set_defaults(handler=commands.attach)

    control = subparsers.add_parser("control", help="send an execution-control command")
    _add_connection_args(control)
    control.add_argument("control_command", choices=sorted(CONTROL_MESSAGES))
    control.set_defaults(handler=commands.control)

    context = subparsers.add_parser("context", help="select script/thread or callstack level")
    _add_connection_args(context)
    context.add_argument("action", choices=["script", "thread", "callstack"])
    context.add_argument("values", type=int, nargs="+")
    context.set_defaults(handler=commands.context)

    breakpoint = subparsers.add_parser("breakpoint", help="add or remove a breakpoint")
    _add_connection_args(breakpoint)
    breakpoint.add_argument("action", choices=["add", "remove"])
    breakpoint.add_argument("script_id", type=int)
    breakpoint.add_argument("thread_id", type=int)
    breakpoint.add_argument("source_name")
    breakpoint.add_argument("line_number", type=int)
    breakpoint.add_argument("--condition", default="")
    breakpoint.set_defaults(handler=commands.breakpoint)

    variable = subparsers.add_parser("variable", help="dump a variable in a script context")
    _add_connection_args(variable)
    variable.add_argument("script_id", type=int)
    variable.add_argument("variable_name")
    variable.add_argument("--json", action="store_true", help="emit JSON")
    variable.set_defaults(handler=commands.variable)

    execute = subparsers.add_parser("execute", help="execute text in a script context")
    _add_connection_args(execute)
    execute.add_argument("script_id", type=int)
    execute.add_argument("text")
    execute.set_defaults(handler=commands.execute)

    table = subparsers.add_parser("table", help="dump a table in a script context")
    _add_connection_args(table)
    table.add_argument("script_id", type=int)
    table.add_argument("context_id", type=int, help="opaque table context/request id")
    table.add_argument("table_name")
    table.add_argument("--path", type=int, nargs="*", default=[])
    table.add_argument("--json", action="store_true", help="emit JSON")
    table.set_defaults(handler=commands.table)

    session = subparsers.add_parser("session", help="connect and service a diagnostic session")
    _add_connection_args(session)
    session.add_argument("--script-id", type=int, default=None)
    session.add_argument("--duration", type=float, default=30.0)
    session.add_argument("--show-messages", action="store_true", help="print serviced messages")
    session.set_defaults(handler=commands.session)

    hello = subparsers.add_parser("hello-bytes", help="print the core connect request as hex")
    hello.add_argument("client_name", help="client name to encode")
    hello.set_defaults(handler=commands.hello_bytes)

    parse = subparsers.add_parser("parse-spoot", help="parse a Spoot response hex datagram")
    parse.add_argument("hex_datagram", help="raw UDP response as hexadecimal")
    parse.set_defaults(handler=commands.parse_spoot)

    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", 0))

    try:
        return args.handler(args)

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
