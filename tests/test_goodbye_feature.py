from eaw_lua_debugger.client import LuaDebuggerClient
from eaw_lua_debugger.lua_messages import LuaMessageId, parse_lua_message
from eaw_lua_debugger.pgnet import PacketKind, PgNetPacket, decode_datagram, encode_datagram


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
