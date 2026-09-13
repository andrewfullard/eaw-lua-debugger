"""Synchronous UDP client for the Empire at War Lua debugger."""

from __future__ import annotations

import os
import socket
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from logging import getLogger

from .bitstream import BitBuffer
from .exceptions import Timeout
from .lua_messages import LuaMessage, LuaMessageId, encode_lua_message, parse_lua_message
from .pgnet import PacketKind, build_connect_request, decode_datagram, parse_connect_response
from .reliable import ReliableState

log = getLogger(__name__)
CONTROL_MESSAGES = {
    "break": LuaMessageId.BREAK_ALL,
    "continue": LuaMessageId.CONTINUE,
    "step-over": LuaMessageId.STEP_OVER,
    "step-into": LuaMessageId.STEP_INTO,
    "step-out": LuaMessageId.STEP_OUT,
}


@dataclass(frozen=True)
class ScriptInfo:
    script_id: int
    full_path_name: str


@dataclass(frozen=True)
class ThreadInfo:
    thread_index: int
    thread_name: str


@dataclass(frozen=True)
class VariableValue:
    variable_name: str
    value_type: int
    value_text: str


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
        self.client_name = client_name or f"LuaDebuggerNET:{os.getpid()}"
        self.timeout = timeout
        self.socket: socket.socket | None = None
        self.server_name: str | None = None
        self.reliable = ReliableState(resend_interval=resend_interval)
        self.messages: deque[LuaMessage] = deque()
        self._lua_connected = False

    def __enter__(self) -> LuaDebuggerClient:
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def open(self) -> None:
        if self.socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", self.local_port))
        sock.settimeout(0.1)
        self.socket = sock
        log.info("bound UDP %s -> %s", sock.getsockname(), self.remote)

    def close(self) -> None:
        if self.socket is not None:
            if self._lua_connected:
                self.send_lua(LuaMessageId.GOODBYE)
                try:
                    self.flush()
                except Timeout:
                    log.warning("timed out waiting for GOODBYE ACK")
                self._lua_connected = False
            self.socket.close()
            self.socket = None

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

        assert self.socket is not None
        for datagram in self.reliable.due_resends():
            log.warning("resending reliable datagram bytes=%s", len(datagram))
            self.socket.sendto(datagram, self.remote)

        try:
            datagram, address = self.socket.recvfrom(65535)
        except TimeoutError:
            return []
        if address != self.remote:
            log.debug("ignoring datagram from unexpected endpoint %s", address)
            return []

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
            log.warning("sending NACK id=%s", nack.packet_id)
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
            log.info("received Lua message id=%s name=%s", message.message_id, message.name)
            self.messages.append(message)
            messages.append(message)
        return messages

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
            self.service_once()
        raise Timeout(f"timed out waiting for Lua message ID {target}")

    def flush(self, *, deadline: float | None = None) -> None:
        deadline = time.monotonic() + self.timeout if deadline is None else deadline
        while self.reliable.pending and time.monotonic() < deadline:
            self.service_once()
        if self.reliable.pending:
            raise Timeout("timed out waiting for reliable ACKs")

    def request_scripts(self) -> list[ScriptInfo]:
        self.send_lua(LuaMessageId.REQUEST_SCRIPT_LIST)
        message = self.wait_for(LuaMessageId.SCRIPT_LIST)
        return [
            ScriptInfo(script_id=item["script_id"], full_path_name=item["full_path_name"])
            for item in message.fields["scripts"]
        ]

    def request_threads(self, script_id: int) -> list[ThreadInfo]:
        self.send_lua(LuaMessageId.REQUEST_THREAD_LIST, script_id)
        message = self.wait_for(
            LuaMessageId.THREAD_LIST,
            predicate=lambda message: message.fields["script_id"] == script_id,
        )
        return [
            ThreadInfo(thread_index=item["thread_index"], thread_name=item["thread_name"])
            for item in message.fields["threads"]
        ]

    def attach_script(self, script_id: int) -> list[str]:
        self.send_lua(LuaMessageId.ATTACH_SCRIPT, script_id)
        message = self.wait_for(
            LuaMessageId.CHILD_SCRIPT_LIST,
            predicate=lambda message: message.fields["parent_script_id"] == script_id,
        )
        return list(message.fields["child_script_names"])

    def send_control(self, command: str) -> None:
        try:
            message_id = CONTROL_MESSAGES[command]
        except KeyError as exc:
            raise ValueError(f"unknown control command {command!r}") from exc
        self.send_lua(message_id)

    def add_breakpoint(
        self,
        script_id: int,
        thread_id: int,
        source_name: str,
        line_number: int,
        condition: str = "",
    ) -> None:
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
    ) -> None:
        self.send_lua(
            LuaMessageId.REMOVE_BREAKPOINT,
            script_id,
            thread_id,
            source_name,
            line_number,
        )

    def dump_variable(self, script_id: int, variable_name: str) -> VariableValue:
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
        self.send_lua(LuaMessageId.EXECUTE_TEXT, script_id, text)
        message = self.wait_for(
            LuaMessageId.EXECUTE_TEXT_RESPONSE,
            predicate=lambda message: message.fields["script_id"] == script_id,
        )
        return message.fields["result_text"]

    def iter_messages(self, *, timeout: float | None = None) -> Iterable[LuaMessage]:
        deadline = None if timeout is None else time.monotonic() + timeout
        while deadline is None or time.monotonic() < deadline:
            yield from self.service_once()
