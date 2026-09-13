from eaw_lua_debugger.core.exceptions import Timeout
from eaw_lua_debugger.debugger.client import LuaDebuggerClient
from eaw_lua_debugger.protocol.bitstream import BitBuffer
from eaw_lua_debugger.protocol.pgnet import PacketKind, PgNetPacket, encode_datagram


class AckSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    def sendto(self, datagram, remote):
        self.sent.append((datagram, remote))

    def recvfrom(self, _size):
        return encode_datagram(PgNetPacket(0, PacketKind.ACK)), ("127.0.0.1", 1234)

    def close(self):
        self.closed = True


def test_flush_waits_until_pending_reliable_packets_are_acked():
    client = LuaDebuggerClient(timeout=0.01)
    client.socket = AckSocket()
    client.send_payload(BitBuffer(b"x", 8))

    client.flush()

    assert client.reliable.pending == {}


def test_flush_times_out_with_pending_packets():
    client = LuaDebuggerClient(timeout=0.01)
    client.socket = AckSocket()
    client.socket.recvfrom = lambda _size: (_ for _ in ()).throw(TimeoutError())
    client.send_payload(BitBuffer(b"x", 8))

    try:
        client.flush()
    except Timeout:
        pass
    else:
        raise AssertionError("expected timeout")


def test_close_flushes_goodbye_before_closing_socket():
    client = LuaDebuggerClient(timeout=0.01)
    client.socket = AckSocket()
    client._lua_connected = True

    client.close()

    assert client.reliable.pending == {}
    assert client.socket is None
