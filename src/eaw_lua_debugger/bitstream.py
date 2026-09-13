"""Least-significant-bit-first bitstream helpers used by PGNet."""

from __future__ import annotations

from dataclasses import dataclass

from bitarray import bitarray

from .exceptions import ProtocolError


@dataclass(frozen=True)
class BitBuffer:
    data: bytes
    bit_count: int

    def __post_init__(self) -> None:
        if self.bit_count < 0 or self.bit_count > len(self.data) * 8:
            raise ValueError("invalid bit_count")

    @classmethod
    def empty(cls) -> BitBuffer:
        return cls(b"", 0)

    def reader(self) -> BitReader:
        return BitReader(self.data, self.bit_count)

    def trim(self, bit_count: int) -> BitBuffer:
        return BitReader(self.data, self.bit_count).read_buffer(bit_count)


class BitWriter:
    def __init__(self) -> None:
        self._bits = bitarray(endian="little")

    @property
    def bit_count(self) -> int:
        return len(self._bits)

    def write_bits(self, value: int, width: int) -> None:
        if width < 0 or value < 0 or (width and value >= 1 << width):
            raise ValueError("integer does not fit field")
        self._bits.extend(bool((value >> bit) & 1) for bit in range(width))

    def write_bool(self, value: bool) -> None:
        self._bits.append(value)

    def write_u8(self, value: int) -> None:
        self.write_bits(value, 8)

    def write_u32(self, value: int) -> None:
        self.write_bits(value, 32)

    def write_bytes(self, data: bytes) -> None:
        bits = bitarray(endian="little")
        bits.frombytes(data)
        self._bits.extend(bits)

    def write_string(self, value: str) -> None:
        data = value.encode("ascii")
        if len(data) >= 255:
            raise ValueError("PGNet strings must be shorter than 255 bytes")
        self.write_u8(len(data))
        self.write_bytes(data)

    def write_buffer(self, buffer: BitBuffer) -> None:
        bits = bitarray(endian="little")
        bits.frombytes(buffer.data)
        self._bits.extend(bits[: buffer.bit_count])

    def buffer(self) -> BitBuffer:
        return BitBuffer(self.to_bytes(), len(self._bits))

    def to_bytes(self) -> bytes:
        bits = self._bits.copy()
        bits.fill()
        return bits.tobytes()


class BitReader:
    def __init__(self, data: bytes, bit_count: int | None = None, bit_offset: int = 0) -> None:
        bits = bitarray(endian="little")
        bits.frombytes(data)
        stop = len(bits) if bit_count is None else bit_offset + bit_count
        if bit_offset < 0 or stop < bit_offset or stop > len(bits):
            raise ValueError("bit range is outside data")
        self._bits = bits[bit_offset:stop]
        self._pos = 0

    @property
    def remaining_bits(self) -> int:
        return len(self._bits) - self._pos

    @property
    def consumed_bits(self) -> int:
        return self._pos

    def read_bits(self, width: int) -> int:
        if width < 0:
            raise ValueError("width must be non-negative")
        if width > self.remaining_bits:
            raise ProtocolError("unexpected end of bitstream")
        value = sum(int(self._bits[self._pos + bit]) << bit for bit in range(width))
        self._pos += width
        return value

    def read_bool(self) -> bool:
        return bool(self.read_bits(1))

    def read_u8(self) -> int:
        return self.read_bits(8)

    def read_u32(self) -> int:
        return self.read_bits(32)

    def read_bytes(self, size: int) -> bytes:
        return bytes(self.read_u8() for _ in range(size))

    def read_string(self) -> str:
        try:
            return self.read_bytes(self.read_u8()).decode("ascii")
        except UnicodeDecodeError as exc:
            raise ProtocolError("string is not ASCII") from exc

    def read_buffer(self, bit_count: int) -> BitBuffer:
        if bit_count < 0 or bit_count > self.remaining_bits:
            raise ProtocolError("unexpected end of bitstream")
        writer = BitWriter()
        writer._bits.extend(self._bits[self._pos : self._pos + bit_count])
        self._pos += bit_count
        return writer.buffer()
