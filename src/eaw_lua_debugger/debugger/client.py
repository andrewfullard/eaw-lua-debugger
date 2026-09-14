"""Synchronous UDP client for the Empire at War Lua debugger."""

from __future__ import annotations

import os
import socket
import time
from collections import deque
from collections.abc import Callable, Iterable
from enum import StrEnum
from logging import getLogger

from ..core.exceptions import ConnectionLost, InvalidDebuggerState, Timeout, UnsafeOperation
from ..protocol.bitstream import BitBuffer
from ..protocol.lua_messages import (
    LuaMessage,
    LuaMessageId,
    encode_lua_message,
    parse_lua_message,
)
from ..protocol.pgnet import (
    PacketKind,
    build_connect_request,
    decode_datagram,
    parse_connect_response,
)
from ..protocol.reliable import ReliableState
from .types import ScriptInfo, TableMember, ThreadInfo, VariableValue

log = getLogger(__name__)
CONTROL_MESSAGES = {
    "break": LuaMessageId.BREAK_ALL,
    "continue": LuaMessageId.CONTINUE,
    "step-over": LuaMessageId.STEP_OVER,
    "step-into": LuaMessageId.STEP_INTO,
    "step-out": LuaMessageId.STEP_OUT,
}


class DebuggerRunState(StrEnum):
    RUNNING = "running"
    BREAK_PENDING = "break-pending"
    SUSPENDED = "suspended"


class LuaDebuggerClient:
    """A small blocking client for the game's UDP Lua debug server."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1234,
        *,
        local_port: int = 0,
        client_name: str | None = None,
        timeout: float = 5.0,
        resend_interval: float = 2.0,
    ) -> None:
        self.remote = (host, port)
        self.local_port = local_port
        self.client_name = client_name or f"EAWLuaDebugger:{os.getpid()}"
        self.timeout = timeout
        self.socket: socket.socket | None = None
        self.server_name: str | None = None
        self.reliable = ReliableState(resend_interval=resend_interval)
        self.messages: deque[LuaMessage] = deque()
        self._lua_connected = False
        self._lua_goodbye_needed = False
        self.run_state = DebuggerRunState.RUNNING
        self.context_script_id: int | None = None
        self.suspended_script_id: int | None = None
        self.suspended_callstack_size = 0
        self.attached_script_ids: set[int] = set()
        self.thread_ids_by_script: dict[int, set[int]] = {}
        self.known_script_ids: set[int] = set()

    def __enter__(self) -> LuaDebuggerClient:
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def open(self) -> None:
        if self.socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        sock.bind(("0.0.0.0", self.local_port))
        sock.settimeout(0.1)
        self.socket = sock
        log.info("bound UDP %s -> %s", sock.getsockname(), self.remote)

    def close(self) -> None:
        if self.socket is not None:
            if self._lua_connected or self._lua_goodbye_needed:
                self.send_lua(LuaMessageId.GOODBYE)
                try:
                    self.flush()
                except Timeout:
                    log.warning("timed out waiting for GOODBYE ACK")
                except (ConnectionLost, ConnectionResetError):
                    log.warning("remote debugger endpoint reset while sending GOODBYE")
                self._lua_connected = False
                self._lua_goodbye_needed = False
            self.socket.close()
            self.socket = None
            self._reset_debug_state()

    def abort(self) -> None:
        """Close locally after connection loss without trying to contact the peer."""

        if self.socket is not None:
            self.socket.close()
            self.socket = None
        self._lua_connected = False
        self._lua_goodbye_needed = False
        self._reset_debug_state()

    def connect(self) -> str:
        """Perform the PGNet and Lua debugger hello handshakes."""

        self.open()
        assert self.socket is not None
        log.info("sending PGNet connect request as %s", self.client_name)
        self.socket.sendto(build_connect_request(self.client_name), self.remote)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                datagram, address = self.socket.recvfrom(8192)
            except TimeoutError:
                continue
            if address != self.remote:
                log.debug("ignoring datagram from unexpected endpoint %s", address)
                continue
            packet = decode_datagram(datagram)
            self.server_name = parse_connect_response(datagram)
            log.info(
                "received Spoot from %s via packet id=%s kind=%s",
                self.server_name,
                packet.packet_id,
                packet.kind.name,
            )
            if packet.kind == PacketKind.GUARANTEED:
                for outbound in self.reliable.process_packet(packet).outbound:
                    log.debug("sending ACK/NACK for Spoot packet")
                    self.socket.sendto(outbound, self.remote)
            self.send_lua(LuaMessageId.HELLO)
            self.wait_for(LuaMessageId.HELLO, deadline=deadline)
            self._lua_connected = True
            log.info("Lua debugger hello completed")
            return self.server_name
        raise Timeout("timed out waiting for PGNet Spoot response")

    def send_lua(self, message_id: int | LuaMessageId, *fields: int | str | list[int]) -> None:
        log.info("sending Lua message id=%s", int(message_id))
        if message_id == LuaMessageId.HELLO:
            self._lua_goodbye_needed = True
        self.send_payload(encode_lua_message(message_id, *fields))

    def send_payload(self, payload: BitBuffer) -> None:
        assert self.socket is not None
        for datagram in self.reliable.make_guaranteed_packets(payload):
            packet = decode_datagram(datagram)
            log.debug(
                "sending reliable packet id=%s bytes=%s",
                packet.packet_id,
                len(datagram),
            )
            self.socket.sendto(datagram, self.remote)

    def service_once(self) -> list[LuaMessage]:
        """Service one UDP receive attempt, ACKing reliable packets immediately."""

        if self.messages:
            return self._drain_message_queue()
        _received, messages = self._service_once()
        for message in messages:
            self.messages.remove(message)
        return messages

    def service_available(self, *, max_packets: int = 256) -> list[LuaMessage]:
        """Drain immediately available UDP packets without waiting for the next GUI tick."""

        assert self.socket is not None
        old_timeout = self.socket.gettimeout()
        self.socket.settimeout(0.001)
        messages = self._drain_message_queue()
        try:
            for _ in range(max_packets):
                received, packet_messages = self._service_once()
                if not received:
                    break
                for message in packet_messages:
                    self.messages.remove(message)
                messages.extend(packet_messages)
        finally:
            self.socket.settimeout(old_timeout)
        return messages

    def _drain_message_queue(self) -> list[LuaMessage]:
        messages = list(self.messages)
        self.messages.clear()
        return messages

    def _service_once(self) -> tuple[bool, list[LuaMessage]]:
        assert self.socket is not None
        for datagram in self.reliable.due_resends():
            log.warning("resending reliable datagram bytes=%s", len(datagram))
            self.socket.sendto(datagram, self.remote)

        try:
            datagram, address = self.socket.recvfrom(65535)
        except TimeoutError:
            return False, []
        except BlockingIOError:
            return False, []
        except ConnectionResetError as exc:
            raise ConnectionLost("the game reset the debugger connection") from exc
        if address != self.remote:
            log.debug("ignoring datagram from unexpected endpoint %s", address)
            return True, []

        packet = decode_datagram(datagram)
        log.debug(
            "received packet id=%s kind=%s resend=%s bytes=%s",
            packet.packet_id,
            packet.kind.name,
            packet.resend,
            len(datagram),
        )
        result = self.reliable.process_packet(packet)
        for outbound in result.acks:
            ack = decode_datagram(outbound)
            log.debug("sending ACK id=%s", ack.packet_id)
            self.socket.sendto(outbound, self.remote)
        for outbound in result.nacks:
            nack = decode_datagram(outbound)
            log.debug("sending NACK id=%s", nack.packet_id)
            self.socket.sendto(outbound, self.remote)
        for outbound in result.resends:
            resend = decode_datagram(outbound)
            log.warning("resending packet id=%s", resend.packet_id)
            self.socket.sendto(outbound, self.remote)

        messages = []
        for payload in result.deliveries:
            log.debug(
                "parsing Lua payload bytes=%s first=%s",
                len(payload.data),
                payload.data[:16].hex(),
            )
            message = parse_lua_message(payload)
            if message.message_id == LuaMessageId.GOODBYE:
                raise ConnectionLost("the game closed the debugger connection")
            self._track_debug_state(message)
            log.info("received Lua message id=%s name=%s", message.message_id, message.name)
            self.messages.append(message)
            messages.append(message)
        return True, messages

    def _track_debug_state(self, message: LuaMessage) -> None:
        if message.message_id == LuaMessageId.SCRIPT_SUSPENDED:
            script_id = message.fields["script_id"]
            self.known_script_ids.add(script_id)
            self.run_state = DebuggerRunState.SUSPENDED
            self.context_script_id = script_id
            self.suspended_script_id = script_id
            self.suspended_callstack_size = len(message.fields["callstack"])
            self.attached_script_ids.add(script_id)
            self.thread_ids_by_script[script_id] = {
                message.fields["current_thread_id"],
                *(item["thread_index"] for item in message.fields["threads"]),
            }
        elif message.message_id == LuaMessageId.SCRIPT_REMOVED:
            script_id = message.fields["script_id"]
            self.known_script_ids.discard(script_id)
            self.attached_script_ids.discard(script_id)
            self.thread_ids_by_script.pop(script_id, None)
            if self.context_script_id == script_id:
                self._clear_execution_state()
        elif message.message_id == LuaMessageId.SCRIPT_ADDED:
            self.known_script_ids.add(message.fields["script_id"])

    def _reset_debug_state(self) -> None:
        self._clear_execution_state()
        self.attached_script_ids.clear()
        self.thread_ids_by_script.clear()
        self.known_script_ids.clear()

    def _clear_execution_state(self) -> None:
        self.run_state = DebuggerRunState.RUNNING
        self.context_script_id = None
        self.suspended_script_id = None
        self.suspended_callstack_size = 0

    def _require_current_script(self, script_id: int) -> None:
        if script_id not in self.known_script_ids:
            raise InvalidDebuggerState(
                f"script {script_id} is not in the latest game script list; refresh first"
            )

    def _validate_breakpoint_target(self, script_id: int, thread_id: int) -> None:
        if script_id == -1 and thread_id == -1:
            return
        if script_id < 0:
            raise InvalidDebuggerState(
                "only script=-1/thread=-1 is a valid global breakpoint target"
            )
        self._require_current_script(script_id)
        if thread_id != -1 and thread_id not in self.thread_ids_by_script.get(script_id, set()):
            raise InvalidDebuggerState(
                f"thread {thread_id} is not a known thread of script {script_id}; refresh first"
            )

    def wait_for(
        self,
        message_id: int | LuaMessageId,
        *,
        deadline: float | None = None,
        predicate: Callable[[LuaMessage], bool] | None = None,
    ) -> LuaMessage:
        target = int(message_id)
        predicate = (lambda _message: True) if predicate is None else predicate
        deadline = time.monotonic() + self.timeout if deadline is None else deadline
        while time.monotonic() < deadline:
            for message in list(self.messages):
                if message.message_id == target and predicate(message):
                    self.messages.remove(message)
                    return message
            self._service_once()
        raise Timeout(f"timed out waiting for Lua message ID {target}")

    def flush(self, *, deadline: float | None = None) -> None:
        deadline = time.monotonic() + self.timeout if deadline is None else deadline
        while self.reliable.pending and time.monotonic() < deadline:
            self._service_once()
        if self.reliable.pending:
            raise Timeout("timed out waiting for reliable ACKs")

    def request_scripts(self) -> list[ScriptInfo]:
        self.send_lua(LuaMessageId.REQUEST_SCRIPT_LIST)
        message = self.wait_for(LuaMessageId.SCRIPT_LIST)
        scripts = [
            ScriptInfo(script_id=item["script_id"], full_path_name=item["full_path_name"])
            for item in message.fields["scripts"]
        ]
        latest_ids = {script.script_id for script in scripts}
        self.attached_script_ids.intersection_update(latest_ids)
        for stale_id in self.thread_ids_by_script.keys() - latest_ids:
            self.thread_ids_by_script.pop(stale_id)
        if self.context_script_id not in latest_ids:
            self._clear_execution_state()
        self.known_script_ids = latest_ids
        return scripts

    def request_threads(self, script_id: int) -> list[ThreadInfo]:
        self._require_current_script(script_id)
        self.send_lua(LuaMessageId.REQUEST_THREAD_LIST, script_id)
        message = self.wait_for(
            LuaMessageId.THREAD_LIST,
            predicate=lambda message: message.fields["script_id"] == script_id,
        )
        threads = [
            ThreadInfo(thread_index=item["thread_index"], thread_name=item["thread_name"])
            for item in message.fields["threads"]
        ]
        self.thread_ids_by_script[script_id] = {thread.thread_index for thread in threads}
        return threads

    def attach_script(self, script_id: int) -> list[str]:
        self._require_current_script(script_id)
        self.send_lua(LuaMessageId.ATTACH_SCRIPT, script_id)
        message = self.wait_for(
            LuaMessageId.CHILD_SCRIPT_LIST,
            predicate=lambda message: message.fields["parent_script_id"] == script_id,
        )
        self.attached_script_ids.add(script_id)
        return list(message.fields["child_script_names"])

    def break_script(self, script_id: int) -> None:
        """Attach and request suspension of one script without double-arming BREAK_ALL."""

        if self.run_state == DebuggerRunState.SUSPENDED:
            raise InvalidDebuggerState(f"cannot break while debugger is {self.run_state}")
        if (
            self.run_state == DebuggerRunState.BREAK_PENDING
            and self.context_script_id == script_id
        ):
            raise InvalidDebuggerState("a break is already pending for this script")
        if script_id not in self.attached_script_ids:
            self.attach_script(script_id)
        if self.context_script_id == script_id:
            self.send_control("break")
        else:
            self.select_script(script_id)

    def send_control(self, command: str) -> None:
        try:
            message_id = CONTROL_MESSAGES[command]
        except KeyError as exc:
            raise ValueError(f"unknown control command {command!r}") from exc
        if command == "break":
            if self.run_state != DebuggerRunState.RUNNING:
                raise InvalidDebuggerState(f"cannot break while debugger is {self.run_state}")
        elif self.run_state != DebuggerRunState.SUSPENDED:
            raise InvalidDebuggerState(f"cannot {command} while debugger is {self.run_state}")
        self.send_lua(message_id)
        self.run_state = (
            DebuggerRunState.RUNNING
            if command == "continue"
            else DebuggerRunState.BREAK_PENDING
        )
        if command != "break":
            self.suspended_script_id = None
            self.suspended_callstack_size = 0

    def select_script(self, script_id: int) -> None:
        self._require_current_script(script_id)
        if self.context_script_id == script_id:
            return
        if self.run_state == DebuggerRunState.SUSPENDED:
            raise InvalidDebuggerState(
                f"cannot select/break a script while debugger is {self.run_state}"
            )
        self.send_lua(LuaMessageId.SELECT_SCRIPT, script_id)
        self.context_script_id = script_id
        self.suspended_script_id = None
        self.suspended_callstack_size = 0
        self.run_state = DebuggerRunState.BREAK_PENDING

    def select_thread(self, thread_id: int) -> None:
        """Backward-compatible name for the native break-thread command (ID 16)."""

        self.break_thread(thread_id)

    def break_thread(self, thread_id: int) -> None:
        if self.context_script_id is None:
            raise InvalidDebuggerState("cannot break a thread before selecting a script context")
        known_threads = self.thread_ids_by_script.get(self.context_script_id, set())
        if thread_id != -1 and thread_id not in known_threads:
            raise InvalidDebuggerState(
                f"thread {thread_id} is not a known thread of script {self.context_script_id}"
            )
        self.send_lua(LuaMessageId.BREAK_THREAD, thread_id)
        self.run_state = DebuggerRunState.BREAK_PENDING
        self.suspended_script_id = None
        self.suspended_callstack_size = 0

    def set_callstack_depth(self, script_id: int, callstack_level: int) -> None:
        if self.run_state != DebuggerRunState.SUSPENDED:
            raise InvalidDebuggerState(
                f"cannot select a callstack frame while debugger is {self.run_state}"
            )
        if script_id != self.suspended_script_id:
            raise InvalidDebuggerState(
                f"script {script_id} is not the suspended script {self.suspended_script_id}"
            )
        if not 0 <= callstack_level < self.suspended_callstack_size:
            raise InvalidDebuggerState(
                f"callstack level {callstack_level} is outside the suspended callstack"
            )
        self.send_lua(LuaMessageId.SET_CALLSTACK_DEPTH, script_id, callstack_level)

    def add_breakpoint(
        self,
        script_id: int,
        thread_id: int,
        source_name: str,
        line_number: int,
        condition: str = "",
    ) -> None:
        """Send a breakpoint; concrete script IDs must already be attached."""

        self._validate_breakpoint_target(script_id, thread_id)
        if script_id >= 0:
            if script_id not in self.attached_script_ids:
                raise InvalidDebuggerState(
                    f"script {script_id} must be attached before adding a breakpoint"
                )

        self.send_lua(
            LuaMessageId.ADD_BREAKPOINT,
            script_id,
            thread_id,
            source_name,
            line_number,
            condition,
        )

    def remove_breakpoint(
        self,
        script_id: int,
        thread_id: int,
        source_name: str,
        line_number: int,
        condition: str = "",
    ) -> None:
        self._validate_breakpoint_target(script_id, thread_id)
        self.send_lua(
            LuaMessageId.REMOVE_BREAKPOINT,
            script_id,
            thread_id,
            source_name,
            line_number,
            condition,
        )

    def dump_variable(self, script_id: int, variable_name: str) -> VariableValue:
        self._require_current_script(script_id)
        self.send_lua(LuaMessageId.DUMP_VARIABLE, script_id, variable_name)
        message = self.wait_for(
            LuaMessageId.VARIABLE_DUMP,
            predicate=lambda message: (
                message.fields["script_id"] == script_id
                and message.fields["variable_name"] == variable_name
            ),
        )
        return VariableValue(
            variable_name=message.fields["variable_name"],
            value_type=message.fields["value_type"],
            value_text=message.fields["value_text"],
        )

    def execute_text(self, script_id: int, text: str) -> str:
        self._require_current_script(script_id)
        self.send_lua(LuaMessageId.EXECUTE_TEXT, script_id, text)
        message = self.wait_for(
            LuaMessageId.EXECUTE_TEXT_RESPONSE,
            predicate=lambda message: message.fields["script_id"] == script_id,
        )
        return message.fields["result_text"]

    def dump_table(
        self,
        script_id: int,
        context_or_request_id: int,
        table_name: str,
        path: list[int] | None = None,
        *,
        allow_unsafe: bool = False,
    ) -> list[TableMember]:
        if not allow_unsafe:
            raise UnsafeOperation(
                "raw table dumps are disabled because any 255-byte rendered key or value "
                "asserts inside StarWarsI; pass allow_unsafe=True only if process failure "
                "is acceptable"
            )
        self._require_current_script(script_id)
        path = path or []
        self.send_lua(
            LuaMessageId.DUMP_TABLE,
            script_id,
            context_or_request_id,
            table_name,
            len(path),
            path,
        )
        message = self.wait_for(
            LuaMessageId.TABLE_DUMP,
            predicate=lambda message: (
                message.fields["response_or_request_id"] == context_or_request_id
            ),
        )
        return [
            TableMember(
                key_type=item["key_type"],
                key_text=item["key_text"],
                value_type=item["value_type"],
                value_text=item["value_text"],
            )
            for item in message.fields["members"]
        ]

    def iter_messages(self, *, timeout: float | None = None) -> Iterable[LuaMessage]:
        deadline = None if timeout is None else time.monotonic() + timeout
        while deadline is None or time.monotonic() < deadline:
            yield from self.service_once()
