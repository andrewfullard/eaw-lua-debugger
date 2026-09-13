# eaw-lua-debugger

`eaw-lua-debugger` is a Python package for the Star Wars: Empire at War internal
Lua debugger protocol described in `starwars_lua_debug_server_protocol.md`.

It implements:

- least-significant-bit-first PGNet bitstreams
- CRC-checked UDP datagram framing
- the `Yo!`/`Spoot` core handshake
- reliable PGNet ACK/NACK state with ordered delivery and retained resends
- Lua debugger message encoding/parsing for the documented message IDs
- a synchronous backend client
- a CLI for scripting and diagnostics
- an optional Qt GUI for interactive inspection

## CLI

The default game port is `1234`.

```powershell
uv run eaw-lua-debugger scripts --host 127.0.0.1 --port 1234
uv run eaw-lua-debugger session --host 127.0.0.1 --port 1234 --duration 5 --show-messages
```

Supported CLI commands include:

- `scripts`, `threads`, and `attach`
- `control` for `break`, `continue`, `step-over`, `step-into`, and `step-out`
- `context` for script, thread, and callstack selection
- `breakpoint add` / `breakpoint remove`
- `variable`, `table`, and `execute`
- `session` for servicing output/events for a duration

Use `-v` or `-vv` before the subcommand for protocol logging:

```powershell
uv run eaw-lua-debugger -v session --host 127.0.0.1 --port 1234 --duration 1
```

## Qt GUI

The GUI is optional because it depends on PySide6:

```powershell
uv run --extra gui eaw-lua-debugger-gui
```

The window connects through the same backend as the CLI and exposes the debugger
state through tabs matching the native tool shape:

- Files, Call Stack, and Threads
- Debug Output, Variables, Lua Console, Breakpoints, Parse Errors, and Find In Files

Connection options are available as command-line arguments:

```powershell
uv run --extra gui eaw-lua-debugger-gui --host 127.0.0.1 --port 1234 --local-port 1247
```

When the GUI or CLI exits normally, it sends Lua debugger `GOODBYE` and flushes
the reliable ACK so the same local endpoint can be reused.

## Testing

The protocol-vector tests do not need the game to be running:

```powershell
uv run pytest
```

Live testing does need a compatible internal/debug `StarWarsI.exe`, the Lua debug
server started with `luadebug`.

```powershell
uv run eaw-lua-debugger scripts --host 127.0.0.1 --port 1234
```

For linting:

```powershell
uv run ruff check .
```
