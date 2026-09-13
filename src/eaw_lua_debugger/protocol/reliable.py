"""Reliable PGNet packet state."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from logging import getLogger

from ..core.exceptions import ProtocolError
from .bitstream import BitBuffer, BitWriter
from .pgnet import (
    MAX_PACKET_ID,
    SEQUENCER_MAGIC,
    PacketKind,
    PgNetPacket,
    build_ack,
    build_nack,
    encode_datagram,
)

ID_MODULUS = MAX_PACKET_ID + 1
DIRECT_SEND_THRESHOLD = 0x495
CHUNK_DATA_SIZE = DIRECT_SEND_THRESHOLD - 6
log = getLogger(__name__)


@dataclass
class PendingPacket:
    datagram: bytes
    sent_at: float
    attempts: int = 1


@dataclass
class LargeSequence:
    last_chunk_packet_id: int
    original_payload_write_size_bytes: int
    original_payload_bit_count: int
    chunks: list[BitBuffer] = field(default_factory=list)


@dataclass
class ReceiveResult:
    acks: list[bytes] = field(default_factory=list)
    nacks: list[bytes] = field(default_factory=list)
    resends: list[bytes] = field(default_factory=list)
    deliveries: list[BitBuffer] = field(default_factory=list)

    @property
    def outbound(self) -> list[bytes]:
        return [*self.acks, *self.nacks, *self.resends]


class ReliableState:
    """Tracks reliable IDs, ACKs, in-order delivery, and retained resends."""

    def __init__(self, *, resend_interval: float = 2.0) -> None:
        self.next_send_id = 0
        self.expected_recv_id = 0
        self.resend_interval = resend_interval
        self.pending: dict[int, PendingPacket] = {}
        self._queued: dict[int, BitBuffer] = {}
        self._large_sequence: LargeSequence | None = None

    def make_guaranteed(self, payload: BitBuffer) -> bytes:
        packets = self.make_guaranteed_packets(payload)
        if len(packets) != 1:
            raise ValueError("large payload produced multiple guaranteed packets")
        return packets[0]

    def make_guaranteed_packets(self, payload: BitBuffer) -> list[bytes]:
        payload = payload.trim(payload.bit_count)
        if len(payload.data) < DIRECT_SEND_THRESHOLD:
            return [self._make_one(payload)]

        chunks = [
            payload.data[i : i + CHUNK_DATA_SIZE]
            for i in range(0, len(payload.data), CHUNK_DATA_SIZE)
        ]
        last_chunk_packet_id = (self.next_send_id + len(chunks)) % ID_MODULUS
        descriptor = BitWriter()
        descriptor.write_u32(SEQUENCER_MAGIC)
        descriptor.write_u8(0)
        descriptor.write_u32(last_chunk_packet_id)
        descriptor.write_u32(len(payload.data))
        descriptor.write_u32(payload.bit_count)

        packets = [self._make_one(descriptor.buffer())]
        for chunk in chunks:
            writer = BitWriter()
            writer.write_u32(SEQUENCER_MAGIC)
            writer.write_u8(1)
            writer.write_bytes(chunk)
            packets.append(self._make_one(writer.buffer()))
        return packets

    def _make_one(self, payload: BitBuffer) -> bytes:
        packet_id = self.next_send_id
        self.next_send_id = (self.next_send_id + 1) % ID_MODULUS
        datagram = encode_datagram(
            PgNetPacket(packet_id=packet_id, kind=PacketKind.GUARANTEED, payload=payload)
        )
        self.pending[packet_id] = PendingPacket(datagram=datagram, sent_at=time.monotonic())
        return datagram

    def due_resends(self, now: float | None = None) -> list[bytes]:
        now = time.monotonic() if now is None else now
        datagrams = []
        for pending in self.pending.values():
            if now - pending.sent_at >= self.resend_interval:
                pending.sent_at = now
                pending.attempts += 1
                datagrams.append(pending.datagram)
        return datagrams

    def process_packet(self, packet: PgNetPacket) -> ReceiveResult:
        result = ReceiveResult()

        if packet.kind == PacketKind.ACK:
            self.pending.pop(packet.packet_id, None)
            return result

        if packet.kind == PacketKind.NACK:
            pending = self.pending.get(packet.packet_id)
            if pending is not None:
                pending.sent_at = time.monotonic()
                pending.attempts += 1
                result.resends.append(pending.datagram)
            return result

        if packet.kind != PacketKind.GUARANTEED:
            return result

        result.acks.append(build_ack(packet.packet_id))
        distance = (packet.packet_id - self.expected_recv_id) % ID_MODULUS
        if distance > MAX_PACKET_ID // 2:
            return result
        if distance:
            self._queued.setdefault(packet.packet_id, packet.payload)
            result.nacks.append(build_nack(self.expected_recv_id))
            return result

        self._deliver_ordered(packet.packet_id, packet.payload, result)
        while self.expected_recv_id in self._queued:
            payload = self._queued.pop(self.expected_recv_id)
            self._deliver_ordered(self.expected_recv_id, payload, result)
        return result

    def _deliver_ordered(self, packet_id: int, payload: BitBuffer, result: ReceiveResult) -> None:
        self.expected_recv_id = (self.expected_recv_id + 1) % ID_MODULUS
        logical_payload = self._maybe_reassemble_large(packet_id, payload)
        if logical_payload is not None:
            result.deliveries.append(logical_payload)

    def _maybe_reassemble_large(self, packet_id: int, payload: BitBuffer) -> BitBuffer | None:
        if payload.bit_count < 40:
            return payload

        reader = payload.reader()
        magic = reader.read_u32()
        subtype = reader.read_u8()
        if magic != SEQUENCER_MAGIC or subtype not in {0, 1}:
            return payload

        if subtype == 0:
            last_chunk_packet_id = reader.read_u32()
            original_payload_write_size_bytes = reader.read_u32()
            original_payload_bit_count = reader.read_u32()
            log.info(
                "large-packet descriptor last_chunk=%s bytes=%s bits=%s",
                last_chunk_packet_id,
                original_payload_write_size_bytes,
                original_payload_bit_count,
            )
            if original_payload_write_size_bytes != (original_payload_bit_count + 7) // 8:
                raise ProtocolError("large-packet descriptor byte size does not match bit count")
            self._large_sequence = LargeSequence(
                last_chunk_packet_id=last_chunk_packet_id,
                original_payload_write_size_bytes=original_payload_write_size_bytes,
                original_payload_bit_count=original_payload_bit_count,
            )
            return None

        if self._large_sequence is None:
            raise ProtocolError("received large-packet chunk before descriptor")

        chunk_bits = reader.remaining_bits - 7
        if chunk_bits < 0 or chunk_bits % 8:
            raise ProtocolError("large-packet chunk is not byte-aligned")
        chunk = reader.read_buffer(chunk_bits)
        log.debug(
            "large-packet chunk packet=%s bytes=%s first=%s",
            packet_id,
            len(chunk.data),
            chunk.data[:8].hex(),
        )
        self._large_sequence.chunks.append(chunk)
        if packet_id != self._large_sequence.last_chunk_packet_id:
            return None

        writer = BitWriter()
        for chunk in self._large_sequence.chunks:
            writer.write_buffer(chunk)
        assembled_bytes = writer.buffer()
        if len(assembled_bytes.data) != self._large_sequence.original_payload_write_size_bytes:
            raise ProtocolError("large-packet chunks do not match descriptor byte size")
        assembled = assembled_bytes.trim(self._large_sequence.original_payload_bit_count)
        log.info(
            "large-packet assembled bytes=%s bits=%s first=%s",
            len(assembled.data),
            assembled.bit_count,
            assembled.data[:16].hex(),
        )
        self._large_sequence = None
        return assembled
