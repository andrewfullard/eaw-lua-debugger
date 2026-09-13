import pytest

from eaw_lua_debugger.core.exceptions import Timeout
from eaw_lua_debugger.debugger.client import LuaDebuggerClient
from eaw_lua_debugger.protocol.lua_messages import LuaMessageId, encode_lua_message
from eaw_lua_debugger.protocol.pgnet import (
    PacketKind,
    PgNetPacket,
    decode_datagram,
    encode_datagram,
)

KNOWN_CONNECT_RESPONSE = bytes.fromhex(
    "3d3c16e500000000e001e00ba6e0dedee81ca6e8c2e4aec2e4e692746e70706800"
)


class FakeSocket:
    def __init__(self, datagrams):
        self.datagrams = list(datagrams)
        self.sent = []

    def sendto(self, datagram, remote):
        self.sent.append((datagram, remote))

    def recvfrom(self, _size):
        if not self.datagrams:
            raise TimeoutError
        return self.datagrams.pop(0)

    def close(self):
        pass


def test_connect_acks_guaranteed_spoot_before_waiting_for_lua_hello():
    remote = ("127.0.0.1", 1234)
    lua_hello = encode_datagram(
        PgNetPacket(
            packet_id=1,
            kind=PacketKind.GUARANTEED,
            payload=encode_lua_message(LuaMessageId.HELLO),
        )
    )
    client = LuaDebuggerClient(timeout=0.01)
    client.socket = FakeSocket([(KNOWN_CONNECT_RESPONSE, remote), (lua_hello, remote)])

    assert client.connect() == "StarWarsI:7884"
    assert decode_datagram(client.socket.sent[1][0]).kind == PacketKind.ACK
    assert decode_datagram(client.socket.sent[1][0]).packet_id == 0


def test_connect_times_out_if_spoot_sequence_is_not_consumed():
    remote = ("127.0.0.1", 1234)
    lua_hello = encode_datagram(
        PgNetPacket(
            packet_id=1,
            kind=PacketKind.GUARANTEED,
            payload=encode_lua_message(LuaMessageId.HELLO),
        )
    )
    client = LuaDebuggerClient(timeout=0.01)
    client.socket = FakeSocket([(lua_hello, remote)])

    with pytest.raises(Timeout):
        client.wait_for(LuaMessageId.HELLO)
