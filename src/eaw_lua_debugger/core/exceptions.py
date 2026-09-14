"""Protocol-specific exceptions."""


class EawLuaDebuggerError(Exception):
    """Base error for this package."""


class ProtocolError(EawLuaDebuggerError):
    """Raised when a packet is malformed or violates the protocol."""


class CrcMismatch(ProtocolError):
    """Raised when a PGNet datagram CRC does not match its body."""


class Timeout(EawLuaDebuggerError):
    """Raised when the debugger client waits too long for a response."""


class ConnectionLost(EawLuaDebuggerError):
    """Raised when the game closes or resets the debugger connection."""


class InvalidDebuggerState(EawLuaDebuggerError):
    """Raised before sending a command that is invalid in the native debugger state."""


class UnsafeOperation(EawLuaDebuggerError):
    """Raised when an operation can trigger an unrecoverable game-side assertion."""
