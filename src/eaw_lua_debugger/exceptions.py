"""Protocol-specific exceptions."""


class EawLuaDebuggerError(Exception):
    """Base error for this package."""


class ProtocolError(EawLuaDebuggerError):
    """Raised when a packet is malformed or violates the protocol."""


class CrcMismatch(ProtocolError):
    """Raised when a PGNet datagram CRC does not match its body."""


class Timeout(EawLuaDebuggerError):
    """Raised when the debugger client waits too long for a response."""
