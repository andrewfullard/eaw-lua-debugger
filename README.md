# eaw-lua-debugger

`eaw-lua-debugger` is a Python package for the Star Wars: Empire at War internal
Lua debugger protocol described in `starwars_lua_debug_server_protocol.md`.

It implements:

- least-significant-bit-first PGNet bitstreams
- CRC-checked UDP datagram framing
- the `Yo!`/`Spoot` core handshake
- reliable PGNet ACK/NACK state with ordered delivery and retained resends
- Lua debugger message encoding/parsing for the documented message IDs
- a small synchronous client and CLI

## Testing

The protocol-vector tests do not need the game to be running:

```powershell
uv run pytest
```

Live testing does need a compatible internal/debug `StarWarsI.exe`, the Lua debug
server started with `luadebug`, and a fresh UDP source endpoint. The default game
port is `1234`.

```powershell
uv run eaw-lua-debugger scripts --host 127.0.0.1 --port 1234
```

If a connection attempt partially succeeds and then stalls, restart the game or
choose a different `--local-port`; the game rejects duplicate source endpoints.
