"""Lua debugger message serializers and parsers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from .bitstream import BitBuffer, BitReader, BitWriter
from .exceptions import ProtocolError

LUA_DEBUGGER_MAGIC = 0xD


class LuaMessageId(IntEnum):
    HELLO = 1
    GOODBYE = 2
    REQUEST_SCRIPT_LIST = 3
    REQUEST_THREAD_LIST = 4
    ADD_BREAKPOINT = 7
    REMOVE_BREAKPOINT = 8
    BREAK_ALL = 9
    STEP_OVER = 10
    STEP_INTO = 11
    STEP_OUT = 12
    HEARTBEAT = 13
    ATTACH_SCRIPT = 14
    SELECT_SCRIPT = 15
    SELECT_THREAD = 16
    CONTINUE = 17
    DUMP_VARIABLE = 19
    DUMP_TABLE = 20
    SET_CALLSTACK_DEPTH = 21
    SCRIPT_LIST = 24
    THREAD_LIST = 25
    SCRIPT_ADDED = 27
    SCRIPT_REMOVED = 28
    SCRIPT_SUSPENDED = 29
    VARIABLE_DUMP = 30
    TABLE_DUMP = 31
    CHILD_SCRIPT_LIST = 32
    OUTPUT = 33
    EXECUTE_TEXT = 34
    EXECUTE_TEXT_RESPONSE = 35


@dataclass(frozen=True)
class LuaMessage:
    message_id: int
    fields: dict[str, Any]
    raw_payload: BitBuffer

    @property
    def name(self) -> str:
        try:
            return LuaMessageId(self.message_id).name
        except ValueError:
            return f"UNKNOWN_{self.message_id}"


def _write_header(writer: BitWriter, message_id: int) -> None:
    writer.write_bits(LUA_DEBUGGER_MAGIC, 4)
    writer.write_u32(message_id)


def encode_lua_message(message_id: int | LuaMessageId, *fields: int | str | list[int]) -> BitBuffer:
    """Encode a documented Lua debugger request."""

    writer = BitWriter()
    _write_header(writer, int(message_id))
    for field in fields:
        if isinstance(field, int):
            writer.write_u32(field)
        elif isinstance(field, str):
            writer.write_string(field)
        elif isinstance(field, list):
            for item in field:
                writer.write_u32(item)
        else:
            raise TypeError(f"unsupported Lua message field {field!r}")
    return writer.buffer()


def request_thread_list(script_id: int) -> BitBuffer:
    return encode_lua_message(LuaMessageId.REQUEST_THREAD_LIST, script_id)


def add_breakpoint(
    script_id: int,
    thread_id: int,
    source_name: str,
    line_number: int,
    condition: str = "",
) -> BitBuffer:
    return encode_lua_message(
        LuaMessageId.ADD_BREAKPOINT,
        script_id,
        thread_id,
        source_name,
        line_number,
        condition,
    )


def remove_breakpoint(
    script_id: int,
    thread_id: int,
    source_name: str,
    line_number: int,
) -> BitBuffer:
    return encode_lua_message(
        LuaMessageId.REMOVE_BREAKPOINT,
        script_id,
        thread_id,
        source_name,
        line_number,
    )


def dump_variable(script_id: int, variable_name: str) -> BitBuffer:
    return encode_lua_message(LuaMessageId.DUMP_VARIABLE, script_id, variable_name)


def dump_table(
    script_id: int,
    context_or_request_id: int,
    table_expression_or_name: str,
    table_path_components: list[int] | None = None,
) -> BitBuffer:
    components = table_path_components or []
    return encode_lua_message(
        LuaMessageId.DUMP_TABLE,
        script_id,
        context_or_request_id,
        table_expression_or_name,
        len(components),
        components,
    )


def execute_text(script_id: int, text: str) -> BitBuffer:
    return encode_lua_message(LuaMessageId.EXECUTE_TEXT, script_id, text)


def parse_lua_message(payload: BitBuffer) -> LuaMessage:
    reader = _reader_after_magic(payload)
    message_id = reader.read_u32()
    fields = _parse_fields(message_id, reader)
    return LuaMessage(message_id=message_id, fields=fields, raw_payload=payload)


def _reader_after_magic(payload: BitBuffer) -> BitReader:
    reader = payload.reader()
    magic = reader.read_bits(4)
    if magic == LUA_DEBUGGER_MAGIC:
        return reader

    if payload.bit_count >= 61:
        prefix = payload.reader()
        if prefix.read_bits(57) == 0:
            shifted = BitReader(payload.data, payload.bit_count - 57, bit_offset=57)
            if shifted.read_bits(4) == LUA_DEBUGGER_MAGIC:
                return shifted

    raise ProtocolError(f"unexpected Lua debugger packet magic 0x{magic:x}")


def _parse_thread_pairs(reader: BitReader) -> list[dict[str, Any]]:
    threads: list[dict[str, Any]] = []
    while reader.remaining_bits >= 40:
        thread_index = reader.read_u32()
        name = reader.read_string()
        threads.append({"thread_index": thread_index, "thread_name": name})
    return threads


def _parse_script_list(reader: BitReader) -> dict[str, Any]:
    count = reader.read_u32()
    scripts = []
    for _ in range(count):
        scripts.append({"script_id": reader.read_u32(), "full_path_name": reader.read_string()})
    return {"script_count": count, "scripts": scripts}


def _parse_fields(message_id: int, reader: BitReader) -> dict[str, Any]:
    if message_id in {LuaMessageId.HELLO, LuaMessageId.GOODBYE, LuaMessageId.HEARTBEAT}:
        return {}

    if message_id == LuaMessageId.SCRIPT_LIST:
        return _parse_script_list(reader)

    if message_id == LuaMessageId.THREAD_LIST:
        script_id = reader.read_u32()
        active_thread_count = reader.read_u32()
        return {
            "script_id": script_id,
            "active_thread_count": active_thread_count,
            "threads": _parse_thread_pairs(reader),
        }

    if message_id == LuaMessageId.SCRIPT_ADDED:
        return {"script_id": reader.read_u32(), "full_path_name": reader.read_string()}

    if message_id == LuaMessageId.SCRIPT_REMOVED:
        return {"script_id": reader.read_u32()}

    if message_id == LuaMessageId.SCRIPT_SUSPENDED:
        script_id = reader.read_u32()
        current_thread_id = reader.read_u32()
        full_path_name = reader.read_string()
        callstack_entry_count = reader.read_u32()
        callstack = [reader.read_string() for _ in range(callstack_entry_count)]
        active_thread_count = reader.read_u32()
        return {
            "script_id": script_id,
            "current_thread_id": current_thread_id,
            "full_path_name": full_path_name,
            "callstack": callstack,
            "active_thread_count": active_thread_count,
            "threads": _parse_thread_pairs(reader),
        }

    if message_id == LuaMessageId.VARIABLE_DUMP:
        return {
            "script_id": reader.read_u32(),
            "variable_name": reader.read_string(),
            "value_type": reader.read_u32(),
            "value_text": reader.read_string(),
        }

    if message_id == LuaMessageId.TABLE_DUMP:
        response_or_request_id = reader.read_u32()
        member_count = reader.read_u32()
        members = []
        for _ in range(member_count):
            members.append(
                {
                    "key_type": reader.read_u32(),
                    "key_text": reader.read_string(),
                    "value_type": reader.read_u32(),
                    "value_text": reader.read_string(),
                }
            )
        return {
            "response_or_request_id": response_or_request_id,
            "member_count": member_count,
            "members": members,
        }

    if message_id == LuaMessageId.CHILD_SCRIPT_LIST:
        parent_script_id = reader.read_u32()
        child_count = reader.read_u32()
        return {
            "parent_script_id": parent_script_id,
            "child_count": child_count,
            "child_script_names": [reader.read_string() for _ in range(child_count)],
        }

    if message_id == LuaMessageId.OUTPUT:
        return {"output_type": reader.read_u32(), "message": reader.read_string()}

    if message_id == LuaMessageId.EXECUTE_TEXT_RESPONSE:
        return {"script_id": reader.read_u32(), "result_text": reader.read_string()}

    return {"unparsed_bits": reader.remaining_bits}
