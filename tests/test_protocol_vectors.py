import binascii

import pytest

import eaw_lua_debugger as eld

KNOWN_CONNECT_REQUEST = bytes.fromhex(
    "04cc6158ffff7f00e001e007b2de422898eac288cac4eacececae49c8aa87464606a707000"
)
KNOWN_CONNECT_RESPONSE = bytes.fromhex(
    "3d3c16e500000000e001e00ba6e0dedee81ca6e8c2e4aec2e4e692746e70706800"
)


def _pack_lsb_fields(*fields):
    bits = []
    for value, width in fields:
        bits.extend((value >> bit) & 1 for bit in range(width))

    data = bytearray((len(bits) + 7) // 8)
    for bit_offset, bit in enumerate(bits):
        data[bit_offset // 8] |= bit << (bit_offset % 8)
    return data


def _write_string_fields(text):
    raw = text.encode("ascii")
    return [(len(raw), 8), *((byte, 8) for byte in raw)]


def _connect_response_with_greeting(greeting):
    fields = [
        (0, 32),
        (0, 22),
        (0, 2),
        (0, 1),
        (0xF000F000, 32),
        *_write_string_fields(greeting),
        *_write_string_fields("StarWarsI:7884"),
    ]
    data = _pack_lsb_fields(*fields)
    crc = binascii.crc32(data[4:]) & 0xFFFFFFFF
    data[:4] = crc.to_bytes(4, "little")
    return bytes(data)


def test_bit_writer_and_reader_use_lsb_first_order_across_byte_boundaries():
    writer = eld.BitWriter()

    writer.write_bits(0b101, 3)
    writer.write_bits(0b10010, 5)
    writer.write_bits(0xABC, 12)

    assert writer.to_bytes() == bytes.fromhex("95bc0a")

    reader = eld.BitReader(writer.to_bytes())
    assert reader.read_bits(3) == 0b101
    assert reader.read_bits(5) == 0b10010
    assert reader.read_bits(12) == 0xABC
    assert reader.read_bits(4) == 0


def test_strings_are_one_byte_length_prefixed_ascii_and_reject_255_bytes():
    writer = eld.BitWriter()

    writer.write_string("Yo!")
    writer.write_string("Spoot")

    assert writer.to_bytes() == b"\x03Yo!\x05Spoot"

    reader = eld.BitReader(writer.to_bytes())
    assert reader.read_string() == "Yo!"
    assert reader.read_string() == "Spoot"

    with pytest.raises(ValueError):
        eld.BitWriter().write_string("x" * 255)


def test_connect_request_matches_known_good_stock_debugger_vector():
    request = eld.build_connect_request("EAWLuaDebugger:20588")

    assert request == KNOWN_CONNECT_REQUEST

    packet = eld.decode_datagram(request)
    assert packet.packet_id == 0x3FFFFF
    assert packet.kind == eld.PacketKind.NON_GUARANTEED
    assert packet.resend is False

    payload = packet.payload.reader()
    assert payload.read_bits(32) == 0xF000F000
    assert payload.read_string() == "Yo!"
    assert payload.read_string() == "EAWLuaDebugger:20588"


def test_connect_response_parses_spoot_without_hard_coding_server_process_id():
    server_name = eld.parse_connect_response(KNOWN_CONNECT_RESPONSE)
    packet = eld.decode_datagram(KNOWN_CONNECT_RESPONSE)
    payload = packet.payload.reader()

    assert packet.packet_id == 0
    assert packet.kind == eld.PacketKind.GUARANTEED
    assert payload.read_bits(32) == 0xF000F000
    assert payload.read_string() == "Spoot"
    assert server_name == "StarWarsI:7884"


def test_connect_response_rejects_bad_crc_and_bad_greeting():
    bad_crc = bytearray(KNOWN_CONNECT_RESPONSE)
    bad_crc[-1] ^= 0x01

    with pytest.raises(eld.ProtocolError):
        eld.parse_connect_response(bytes(bad_crc))

    bad_greeting = _connect_response_with_greeting("Spoof")

    with pytest.raises(eld.ProtocolError):
        eld.parse_connect_response(bad_greeting)


def test_inner_lua_packet_encoding_starts_with_four_bit_magic_then_message_id():
    assert eld.encode_lua_message(1).data == bytes.fromhex("1d00000000")
    assert eld.encode_lua_message(3).data == bytes.fromhex("3d00000000")

    reader = eld.encode_lua_message(14, 0x1234).reader()
    assert reader.read_bits(4) == 0xD
    assert reader.read_bits(32) == 14
    assert reader.read_bits(32) == 0x1234


def test_lua_parser_accepts_large_packet_payload_with_embedded_pgnet_header():
    writer = eld.BitWriter()
    writer.write_bits(0, 57)
    writer.write_buffer(eld.encode_lua_message(1))

    message = eld.parse_lua_message(writer.buffer())

    assert message.message_id == 1
    assert message.name == "HELLO"


def test_guaranteed_lua_packet_and_ack_header_shape_match_known_vectors():
    lua_hello = eld.encode_lua_message(1)
    guaranteed = eld.encode_datagram(
        eld.PgNetPacket(packet_id=0, kind=eld.PacketKind.GUARANTEED, payload=lua_hello)
    )

    parsed = eld.decode_datagram(guaranteed)
    assert parsed.packet_id == 0
    assert parsed.kind == eld.PacketKind.GUARANTEED
    assert parsed.payload.data == lua_hello.data

    ack = eld.build_ack(packet_id=1)
    assert ack == bytes.fromhex("32207ba201008000")

    parsed_ack = eld.decode_datagram(ack)
    assert parsed_ack.packet_id == 1
    assert parsed_ack.kind == eld.PacketKind.ACK
    assert parsed_ack.payload.data == b""
    assert len(ack) == 8
