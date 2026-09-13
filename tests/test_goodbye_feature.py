from eaw_lua_debugger.client import LuaDebuggerClient
from eaw_lua_debugger.exceptions import ProtocolError, Timeout
from eaw_lua_debugger.lua_messages import LuaMessageId, parse_lua_message
from eaw_lua_debugger.pgnet import PacketKind, PgNetPacket, decode_datagram, encode_datagram

KNOWN_CONNECT_RESPONSE = bytes.fromhex(
    "3d3c16e500000000e001e00ba6e0dedee81ca6e8c2e4aec2e4e692746e70706800"
)


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    def sendto(self, datagram, remote):
        self.sent.append((datagram, remote))

    def recvfrom(self, _size):
        return encode_datagram(PgNetPacket(0, PacketKind.ACK)), ("127.0.0.1", 1234)

    def close(self):
        self.closed = True


def test_close_sends_goodbye_when_lua_handshake_completed():
    sock = FakeSocket()
    client = LuaDebuggerClient()
    client.socket = sock
    client._lua_connected = True

    client.close()

    packet = decode_datagram(sock.sent[0][0])
    assert parse_lua_message(packet.payload).message_id == LuaMessageId.GOODBYE
    assert sock.closed is True


class TimeoutSocket:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.datagrams = [(KNOWN_CONNECT_RESPONSE, ("127.0.0.1", 1234))]

    def sendto(self, datagram, remote):
        self.sent.append((datagram, remote))

    def recvfrom(self, _size):
        if self.datagrams:
            return self.datagrams.pop(0)
        raise TimeoutError

    def close(self):
        self.closed = True


def test_close_sends_goodbye_after_partial_lua_handshake_timeout():
    sock = TimeoutSocket()
    client = LuaDebuggerClient(timeout=0.01)
    client.socket = sock

    try:
        client.connect()
    except Timeout:
        client.close()
    else:
        raise AssertionError("expected timeout")

    assert LuaMessageId.GOODBYE in _sent_lua_message_ids(sock.sent)
    assert sock.closed is True


def _sent_lua_message_ids(sent):
    message_ids = []
    for datagram, _remote in sent:
        try:
            message_ids.append(parse_lua_message(decode_datagram(datagram).payload).message_id)
        except ProtocolError:
            pass
    return message_ids
