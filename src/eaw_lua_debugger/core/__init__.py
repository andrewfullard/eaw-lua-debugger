"""Shared package infrastructure."""

from .exceptions import (
    ConnectionLost,
    CrcMismatch,
    EawLuaDebuggerError,
    InvalidDebuggerState,
    ProtocolError,
    Timeout,
    UnsafeOperation,
)

__all__ = [
    "CrcMismatch",
    "ConnectionLost",
    "EawLuaDebuggerError",
    "InvalidDebuggerState",
    "ProtocolError",
    "Timeout",
    "UnsafeOperation",
]
