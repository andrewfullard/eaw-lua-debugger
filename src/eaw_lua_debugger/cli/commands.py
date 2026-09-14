"""CLI command handlers."""

from __future__ import annotations

import argparse
import json

from ..core.exceptions import InvalidDebuggerState
from ..debugger.client import LuaDebuggerClient
from ..debugger.events import describe_message
from ..debugger.session import run_diagnostic_session
from ..protocol.pgnet import build_connect_request, parse_connect_response


def hello_bytes(args: argparse.Namespace) -> int:
    print(build_connect_request(args.client_name).hex())
    return 0


def parse_spoot(args: argparse.Namespace) -> int:
    print(parse_connect_response(bytes.fromhex(args.hex_datagram)))
    return 0


def scripts(args: argparse.Namespace) -> int:
    with _client(args) as client:
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


def threads(args: argparse.Namespace) -> int:
    with _client(args) as client:
        server_name = client.connect()
        client.request_scripts()
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


def attach(args: argparse.Namespace) -> int:
    with _client(args) as client:
        server_name = client.connect()
        client.request_scripts()
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


def control(args: argparse.Namespace) -> int:
    raise InvalidDebuggerState(
        "control commands require one persistent attach/suspend session; use the GUI"
    )


def context(args: argparse.Namespace) -> int:
    raise InvalidDebuggerState(
        "context commands require one persistent attach/suspend session; use the GUI"
    )


def breakpoint(args: argparse.Namespace) -> int:
    raise InvalidDebuggerState(
        "breakpoints are cleared when this one-shot command disconnects; use the GUI"
    )


def variable(args: argparse.Namespace) -> int:
    with _client(args) as client:
        server_name = client.connect()
        client.request_scripts()
        value = client.dump_variable(args.script_id, args.variable_name)
    if args.json:
        print(json.dumps({"server_name": server_name, **value.__dict__}, indent=2))
    else:
        print(f"{value.variable_name}\t{value.value_type}\t{value.value_text}")
    return 0


def execute(args: argparse.Namespace) -> int:
    with _client(args) as client:
        server_name = client.connect()
        client.request_scripts()
        result_text = client.execute_text(args.script_id, args.text)
    print(f"Connected to {server_name}")
    print(result_text)
    return 0


def table(args: argparse.Namespace) -> int:
    with _client(args) as client:
        server_name = client.connect()
        client.request_scripts()
        members = client.dump_table(
            args.script_id,
            args.context_id,
            args.table_name,
            args.path,
            allow_unsafe=args.unsafe,
        )
    if args.json:
        print(
            json.dumps(
                {"server_name": server_name, "members": [member.__dict__ for member in members]},
                indent=2,
            )
        )
    else:
        for member in members:
            print(f"{member.key_text}\t{member.key_type}\t{member.value_text}\t{member.value_type}")
    return 0


def session(args: argparse.Namespace) -> int:
    on_message = None
    if args.show_messages:
        def show_message(message):
            print(describe_message(message))

        on_message = show_message
    with _client(args) as client:
        server_name = client.connect()
        result = run_diagnostic_session(
            client,
            script_id=args.script_id,
            duration=args.duration,
            on_message=on_message,
            collect_messages=not args.show_messages,
        )
    print(f"Connected to {server_name}")
    print(f"scripts: {len(result['scripts'])}")
    print(f"child scripts: {len(result['child_script_names'])}")
    print(f"threads: {len(result['threads'])}")
    print(f"messages: {result['message_count']}")
    return 0


def _client(args: argparse.Namespace) -> LuaDebuggerClient:
    return LuaDebuggerClient(
        args.host,
        args.port,
        local_port=args.local_port,
        client_name=args.client_name,
        timeout=args.timeout,
    )
