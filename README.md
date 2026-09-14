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
- a Qt GUI for interactive inspection
- a CLI for scripting and diagnostics

## Qt GUI

The GUI is the primary way to use the debugger:

See [DEBUGGER_USAGE.md](DEBUGGER_USAGE.md) for a user-facing reference to every
GUI control and command-line function.

```powershell
uv run eaw-lua-debugger-gui
```

Use an internal/debug `StarWarsI.exe`, run `luadebug` in its console, and leave
the game simulation running while requesting a break. Select an actively
executing script in the GUI before pressing Break. The GUI keeps one connection
open, attaches the selected script's Lua line hook, and waits for the game's
`SCRIPT_SUSPENDED` event before step/continue commands become valid. The game's
ordinary pause and internal debug-window single-step modes do not create this
network-debugger suspended state.

The window connects through the same backend as the CLI and exposes the debugger
state through tabs matching the native tool shape:

- Files, Call Stack, and Threads
- line-numbered Lua source tabs with Pygments syntax highlighting
- source-line breakpoint display and Breakpoints tab management
- `File > Smart open...` to list Lua files found under source roots
- File/Edit/Breakpoints menus with the native debugger-style shortcuts
- Debug Output, Variables, Lua Console, and a read-only Breakpoints table

Connection options are available as command-line arguments:

```powershell
uv run eaw-lua-debugger-gui --host 127.0.0.1 --port 1234 --local-port 1247 --source-root "G:\SteamLibrary\steamapps\common\Star Wars Empire at War\corruption"
```

`--source-root` may be passed more than once. The GUI tries to match
game-reported paths directly and by common suffixes such as `Data/Scripts/...`.
You can also set `EAW_LUA_SOURCE_ROOT` to one or more roots separated by the
platform path separator.

## Debug a Lua script: quick guide

1. Start an internal/debug build of the game. Open its console, enter
   `luadebug`, and return to the game. If the game shows a message saying a Lua
   script is suspended without a debugger, dismiss that message before trying
   to connect.
2. Start the GUI with `uv run eaw-lua-debugger-gui`. Add `--source-root` if you
   want the debugger to open your local `.lua` files when the game reports
   them.
3. Choose **File > Connect**. Wait for the bottom status bar to say that it is
   connected, then choose a script from **Files**. Pick one that the game is
   actively using. Selecting it prepares that script for debugging and loads
   its known threads.
4. To stop at a particular line, open the script and double-click that line to
   add a breakpoint. Let the game keep running until it reaches the line. To
   stop at the next Lua line instead, choose **Debug > Break**.
5. Wait for the status bar to say **Suspended**. “Break requested” means the
   debugger issued the request and is waiting for the selected script to
   execute another Lua line. Pausing the game normally does not count as a
   debugger stop.
6. While suspended, use **Call Stack** to see how the script reached the
   current line. Double-click a frame before reading values from that frame.
   Enter a name in **Variables** and choose **Read Variable** to inspect it.
7. Use **Continue**, **Step Over**, **Step Into**, or **Step Out** from the
   Debug menu or toolbar. Step controls are available only after the debugger
   has actually suspended the script.
8. To target one thread, select it under **Threads** and choose
   **Debug > Break Thread**. This is a break request, not just a different way
   to highlight the thread.

You can disconnect and reconnect without recreating ordinary breakpoints. When
exactly one live script has the same source name, the GUI matches it to the new
game script ID, attaches it again, and sends the breakpoint back to the game.
If several live Lua states use the same source, the GUI waits rather than
guessing and says so in the status bar; select the intended live script again.

Table expansion is deliberately labelled unsafe. The game can assert or close
if even one displayed key or value is too long. Prefer **Read Variable**, never
expand `_G`, and accept the warning only when losing the current game session
is acceptable.

If a breakpoint never fires, check these in order:

- The status bar says connected.
- The script still appears in **Files**; use **File > Refresh** if necessary.
- The game is running and is actually executing that script and line.
- The breakpoint source name came from the game-selected file rather than an
  unrelated local copy.
- You did not disconnect after requesting the break. The same connection must
  stay open until the script stops.

## CLI

The CLI is still available for scripting and diagnostics.

The default game port is `1234`.

```powershell
uv run eaw-lua-debugger scripts --host 127.0.0.1 --port 1234
uv run eaw-lua-debugger session --host 127.0.0.1 --port 1234 --duration 5 --show-messages
```

Supported CLI commands include:

- `scripts`, `threads`, and `attach`
- `control`, `context`, and `breakpoint` report that their stateful workflow
  requires the persistent GUI session; a one-shot connection cannot retain it
- `variable`, `execute`, and unsafe opt-in `table --unsafe`
- `session` for servicing output/events for a duration

Use `-v` or `-vv` before the subcommand for protocol logging:

```powershell
uv run eaw-lua-debugger -v session --host 127.0.0.1 --port 1234 --duration 1
```

When the GUI or CLI exits normally, it sends Lua debugger `GOODBYE` and flushes
the reliable ACK so the same local endpoint can be reused. The game then clears
all debugger context, breakpoints, suspension state, and installed Lua hooks.

Raw table enumeration is disabled unless `--unsafe` is passed. The game asserts
while serializing any table member whose display string is 255 bytes or longer;
prefer individual variable requests and never expand `_G` indiscriminately.

## Testing

The protocol-vector tests do not need the game to be running:

```powershell
uv run pytest
```

Live testing does need a compatible internal/debug `StarWarsI.exe`, with the Lua
debug server started using `luadebug`. StarWarsI embeds Lua 5.0.2.

```powershell
uv run eaw-lua-debugger scripts --host 127.0.0.1 --port 1234
```

For linting:

```powershell
uv run ruff check .
```
