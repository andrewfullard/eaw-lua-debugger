"""PGNet datagram framing for the Empire at War Lua debugger."""

from __future__ import annotations

import binascii
from dataclasses import dataclass
from enum import IntEnum

from ..core.exceptions import CrcMismatch, ProtocolError
from .bitstream import BitBuffer, BitReader, BitWriter

MAX_PACKET_ID = 0x3FFFFF
CONNECT_MAGIC = 0xF000F000
SEQUENCER_MAGIC = 0x49960201


class PacketKind(IntEnum):
    """PGNet base packet type."""

    GUARANTEED = 0
    NON_GUARANTEED = 1
    ACK = 2
    NACK = 3


@dataclass(frozen=True)
class PgNetPacket:
    packet_id: int
    kind: PacketKind
    resend: bool = False
    payload: BitBuffer = BitBuffer.empty()

    def __post_init__(self) -> None:
        if not 0 <= self.packet_id <= MAX_PACKET_ID:
            raise ValueError("packet_id must fit in 22 bits")


def _crc32_body(datagram: bytes) -> int:
    return binascii.crc32(datagram[4:]) & 0xFFFFFFFF


def encode_datagram(packet: PgNetPacket) -> bytes:
    """Serialize a PGNet packet and write the CRC field."""

    writer = BitWriter()
    writer.write_bits(packet.packet_id, 22)
    writer.write_bits(int(packet.kind), 2)
    writer.write_bool(packet.resend)
    writer.write_buffer(packet.payload)

    datagram = bytearray(4 + len(writer.to_bytes()))
    datagram[4:] = writer.to_bytes()
    crc = _crc32_body(datagram)
    datagram[:4] = crc.to_bytes(4, "little")
    return bytes(datagram)


def decode_datagram(datagram: bytes, *, validate_crc: bool = True) -> PgNetPacket:
    """Parse and optionally CRC-check a PGNet datagram."""

    if len(datagram) < 8:
        raise ProtocolError("PGNet datagram is too short")

    stored_crc = int.from_bytes(datagram[:4], "little")
    actual_crc = _crc32_body(datagram)
    if validate_crc and stored_crc != actual_crc:
        raise CrcMismatch(f"CRC mismatch: stored 0x{stored_crc:08x}, actual 0x{actual_crc:08x}")

    reader = BitReader(datagram, bit_offset=32)
    packet_id = reader.read_bits(22)
    kind = PacketKind(reader.read_bits(2))
    resend = reader.read_bool()
    if kind in {PacketKind.ACK, PacketKind.NACK}:
        return PgNetPacket(packet_id=packet_id, kind=kind, resend=resend)
    payload = reader.read_buffer(reader.remaining_bits)
    return PgNetPacket(packet_id=packet_id, kind=kind, resend=resend, payload=payload)


def build_connect_payload(client_name: str) -> BitBuffer:
    writer = BitWriter()
    writer.write_u32(CONNECT_MAGIC)
    writer.write_string("Yo!")
    writer.write_string(client_name)
    return writer.buffer()


def build_connect_request(client_name: str) -> bytes:
    """Build the non-guaranteed core PGNet connection request."""

    return encode_datagram(
        PgNetPacket(
            packet_id=MAX_PACKET_ID,
            kind=PacketKind.NON_GUARANTEED,
            payload=build_connect_payload(client_name),
        )
    )


def parse_connect_response(datagram: bytes) -> str:
    """Validate a server Spoot response and return the diagnostic server name."""

    packet = decode_datagram(datagram)
    reader = packet.payload.reader()
    magic = reader.read_u32()
    greeting = reader.read_string()
    server_name = reader.read_string()
    if magic != CONNECT_MAGIC:
        raise ProtocolError(f"unexpected connect magic 0x{magic:08x}")
    if greeting != "Spoot":
        raise ProtocolError(f"unexpected connect greeting {greeting!r}")
    return server_name


def build_ack(packet_id: int) -> bytes:
    return encode_datagram(PgNetPacket(packet_id=packet_id, kind=PacketKind.ACK))


def build_nack(packet_id: int) -> bytes:
    return encode_datagram(PgNetPacket(packet_id=packet_id, kind=PacketKind.NACK))
