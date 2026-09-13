import pytest

from eaw_lua_debugger.bitstream import BitBuffer, BitWriter
from eaw_lua_debugger.exceptions import ProtocolError
from eaw_lua_debugger.pgnet import (
    MAX_PACKET_ID,
    SEQUENCER_MAGIC,
    PacketKind,
    PgNetPacket,
    decode_datagram,
)
from eaw_lua_debugger.reliable import CHUNK_DATA_SIZE, DIRECT_SEND_THRESHOLD, ReliableState


def test_reliable_receive_wraps_22_bit_packet_ids():
    state = ReliableState()
    state.expected_recv_id = MAX_PACKET_ID

    first = state.process_packet(
        PgNetPacket(MAX_PACKET_ID, PacketKind.GUARANTEED, payload=BitBuffer(b"A", 8))
    )
    second = state.process_packet(PgNetPacket(0, PacketKind.GUARANTEED, payload=BitBuffer(b"B", 8)))

    assert [delivery.data for delivery in first.deliveries] == [b"A"]
    assert [delivery.data for delivery in second.deliveries] == [b"B"]
    assert state.expected_recv_id == 1


def test_large_payloads_are_split_and_reassembled_without_padding_bits():
    original = bytes(i % 256 for i in range(DIRECT_SEND_THRESHOLD + 17))
    payload = BitBuffer(original, len(original) * 8 - 3)
    sender = ReliableState()
    receiver = ReliableState()

    datagrams = sender.make_guaranteed_packets(payload)
    assert len(datagrams) > 1

    deliveries = []
    for datagram in datagrams:
        result = receiver.process_packet(decode_datagram(datagram))
        deliveries.extend(result.deliveries)

    assert len(deliveries) == 1
    assert (
        deliveries[0].reader().read_buffer(payload.bit_count).data
        == payload.reader().read_buffer(payload.bit_count).data
    )
    assert deliveries[0].bit_count == payload.bit_count


def test_large_payload_descriptor_and_chunks_match_protocol_shape():
    data = bytes(i % 256 for i in range(DIRECT_SEND_THRESHOLD + 17))
    payload = BitBuffer(data + b"ignored slack", len(data) * 8)
    datagrams = ReliableState().make_guaranteed_packets(payload)

    descriptor = decode_datagram(datagrams[0])
    descriptor_reader = descriptor.payload.reader()
    assert descriptor_reader.read_u32() == SEQUENCER_MAGIC
    assert descriptor_reader.read_u8() == 0
    assert descriptor_reader.read_u32() == len(datagrams) - 1
    assert descriptor_reader.read_u32() == len(data)
    assert descriptor_reader.read_u32() == len(data) * 8

    chunk = decode_datagram(datagrams[1])
    chunk_reader = chunk.payload.reader()
    assert chunk_reader.read_u32() == SEQUENCER_MAGIC
    assert chunk_reader.read_u8() == 1
    assert chunk_reader.read_bytes(CHUNK_DATA_SIZE) == data[:CHUNK_DATA_SIZE]


def test_large_payload_rejects_descriptor_size_mismatch():
    data = bytes(i % 256 for i in range(DIRECT_SEND_THRESHOLD + 17))
    datagrams = ReliableState().make_guaranteed_packets(BitBuffer(data, len(data) * 8))
    descriptor = decode_datagram(datagrams[0])
    reader = descriptor.payload.reader()
    reader.read_u32()
    reader.read_u8()
    last_chunk_id = reader.read_u32()
    wrong_size = reader.read_u32() + 1
    bit_count = reader.read_u32()
    bad_descriptor_payload = _descriptor_payload(last_chunk_id, wrong_size, bit_count)
    receiver = ReliableState()

    with pytest.raises(ProtocolError):
        receiver.process_packet(
            PgNetPacket(0, PacketKind.GUARANTEED, payload=bad_descriptor_payload)
        )


def test_reliable_ack_gap_duplicate_and_resend_behaviors():
    state = ReliableState(resend_interval=10)
    sent = state.make_guaranteed(BitBuffer(b"x", 8))
    assert 0 in state.pending
    state.process_packet(PgNetPacket(0, PacketKind.ACK))
    assert state.pending == {}

    state = ReliableState(resend_interval=10)
    sent = state.make_guaranteed(BitBuffer(b"x", 8))
    resend = state.process_packet(PgNetPacket(0, PacketKind.NACK))
    assert resend.resends == [sent]

    state = ReliableState()
    gap = state.process_packet(PgNetPacket(1, PacketKind.GUARANTEED, payload=BitBuffer(b"b", 8)))
    assert gap.deliveries == []
    assert decode_datagram(gap.nacks[0]).packet_id == 0

    in_order = state.process_packet(
        PgNetPacket(0, PacketKind.GUARANTEED, payload=BitBuffer(b"a", 8))
    )
    assert [delivery.data for delivery in in_order.deliveries] == [b"a", b"b"]
    duplicate = state.process_packet(
        PgNetPacket(0, PacketKind.GUARANTEED, payload=BitBuffer(b"a", 8))
    )
    assert duplicate.deliveries == []

    state = ReliableState(resend_interval=5)
    sent = state.make_guaranteed(BitBuffer(b"x", 8))
    assert state.due_resends(now=state.pending[0].sent_at + 5) == [sent]


def _descriptor_payload(last_chunk_id: int, byte_size: int, bit_count: int) -> BitBuffer:
    writer = BitWriter()
    writer.write_u32(SEQUENCER_MAGIC)
    writer.write_u8(0)
    writer.write_u32(last_chunk_id)
    writer.write_u32(byte_size)
    writer.write_u32(bit_count)
    return writer.buffer()
