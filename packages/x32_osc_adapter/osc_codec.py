"""
OSC (Open Sound Control) Binary Codec for Behringer X32.
Strict 4-byte boundary padding, supporting:
- Address string
- Type tags: 'i' (int32), 'f' (float32), 's' (string), 'b' (blob)
Zero external dependencies, purely standard struct/typing.
"""

from __future__ import annotations
import struct
from typing import Any, Tuple, List, Union

class OSCMessage:
    def __init__(self, address: str, args: List[Any] | None = None, type_tags: str | None = None):
        if not address.startswith('/'):
            address = '/' + address
        self.address = address
        self.args = args or []
        self.type_tags = type_tags

    def __repr__(self) -> str:
        return f"OSCMessage(address='{self.address}', args={self.args})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OSCMessage):
            return False
        return self.address == other.address and self.args == other.args


def _pad_string(s: bytes) -> bytes:
    """Pad null-terminated byte sequence to a multiple of 4 bytes."""
    s = s + b'\x00'
    remainder = len(s) % 4
    if remainder != 0:
        s += b'\x00' * (4 - remainder)
    return s


def _read_string(data: bytes, offset: int) -> Tuple[str, int]:
    """Read null-terminated string padded to 4-byte boundary."""
    null_pos = data.find(b'\x00', offset)
    if null_pos == -1:
        raise ValueError(f"Unterminated string in OSC packet at offset {offset}")
    s = data[offset:null_pos].decode('utf-8', errors='replace')
    end = null_pos + 1
    rem = end % 4
    if rem != 0:
        end += (4 - rem)
    return s, end


def encode_osc(message: OSCMessage) -> bytes:
    """Encode an OSCMessage into standard binary bytes."""
    buf = bytearray()
    
    # 1. Address pattern
    buf.extend(_pad_string(message.address.encode('utf-8')))

    # 2. Type tags and payload
    tags = [',']
    payload = bytearray()

    for arg in message.args:
        if isinstance(arg, bool):
            tags.append('i')
            payload.extend(struct.pack('>i', 1 if arg else 0))
        elif isinstance(arg, int):
            tags.append('i')
            payload.extend(struct.pack('>i', arg))
        elif isinstance(arg, float):
            tags.append('f')
            payload.extend(struct.pack('>f', arg))
        elif isinstance(arg, str):
            tags.append('s')
            payload.extend(_pad_string(arg.encode('utf-8')))
        elif isinstance(arg, (bytes, bytearray)):
            tags.append('b')
            payload.extend(struct.pack('>i', len(arg)))
            payload.extend(_pad_string(bytes(arg)))
        else:
            raise TypeError(f"Unsupported OSC argument type: {type(arg)} for {arg}")

    tag_str = "".join(tags)
    buf.extend(_pad_string(tag_str.encode('utf-8')))
    buf.extend(payload)
    return bytes(buf)


def decode_osc(data: bytes) -> OSCMessage:
    """Decode raw UDP bytes into an OSCMessage."""
    if len(data) < 4:
        raise ValueError(f"Packet too short: {len(data)} bytes")

    address, offset = _read_string(data, 0)
    if not address.startswith('/'):
        raise ValueError(f"Invalid OSC address: {address}")

    if offset >= len(data):
        return OSCMessage(address=address, args=[])

    if data[offset:offset+1] == b',':
        tags, offset = _read_string(data, offset)
        type_tags = tags[1:]
    else:
        return OSCMessage(address=address, args=[])

    args: List[Any] = []
    for tag in type_tags:
        if tag == 'i':
            if offset + 4 > len(data):
                raise ValueError("Truncated int32 in OSC payload")
            val = struct.unpack_from('>i', data, offset)[0]
            args.append(val)
            offset += 4
        elif tag == 'f':
            if offset + 4 > len(data):
                raise ValueError("Truncated float32 in OSC payload")
            val = struct.unpack_from('>f', data, offset)[0]
            args.append(val)
            offset += 4
        elif tag == 's':
            s_val, offset = _read_string(data, offset)
            args.append(s_val)
        elif tag == 'b':
            if offset + 4 > len(data):
                raise ValueError("Truncated blob length in OSC payload")
            blob_len = struct.unpack_from('>i', data, offset)[0]
            offset += 4
            if offset + blob_len > len(data):
                raise ValueError("Truncated blob payload")
            raw_blob = data[offset:offset+blob_len]
            args.append(raw_blob)
            end = offset + blob_len
            rem = end % 4
            if rem != 0:
                end += (4 - rem)
            offset = end
        elif tag in ('T', 'F'):
            args.append(True if tag == 'T' else False)
        elif tag == 'N':
            args.append(None)
        else:
            raise ValueError(f"Unsupported OSC type tag: '{tag}'")

    return OSCMessage(address=address, args=args, type_tags=type_tags)
