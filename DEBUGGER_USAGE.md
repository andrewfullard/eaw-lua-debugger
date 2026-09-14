# Lua debugger user guide

This guide describes every control currently exposed by the Python debugger.
The GUI is the normal way to debug a running game. The command-line interface
is mainly useful for diagnostics and protocol testing.

## Before starting

You need an internal/debug build of `StarWarsI.exe`. Open the game's console,
enter `luadebug`, and return to the game. The game simulation must be allowed to
run when you want a script to reach a breakpoint.

Start the debugger from the project directory:

```powershell
uv run eaw-lua-debugger-gui
```

If the debugger cannot find the source files reported by the game, give it the
game or mod directory:

```powershell
uv run eaw-lua-debugger-gui --source-root "G:\Games\Empire at War\corruption"
```

You can repeat `--source-root` for multiple game or mod directories. The other
connection options are:

- `--host`: computer running the game; the default is `127.0.0.1`.
- `--port`: game Lua-debug port; the default is `1234`.
- `--local-port`: debugger's local UDP port; `0` chooses an available port.
- `--client-name`: optional network client name.
- `--timeout`: seconds to wait for a game response.

## Normal debugging workflow

1. Choose **File > Connect**.
2. Select a green, thread-active script in **Files**.
3. Open its source and double-click a line to set a breakpoint.
4. Let the game run until that line executes.
5. Wait for the status bar to say **Suspended**.
6. Inspect the call stack and variables, or use a step command.
7. Choose **Continue** when finished.

“Break requested” is not the same as “Suspended.” It means the debugger is
waiting for the selected script to execute another Lua line. Pausing the game
normally does not create a debugger suspension.

## Toolbar

The toolbar contains shortcuts for the most frequently used menu commands:

- **Connect** and **Disconnect** control the debugger connection.
- **Refresh** reloads the game's active script list.
- **Break**, **Continue**, **Step Over**, **Step Into**, and **Step Out** are the
  same commands described under the Debug menu below.

Unavailable commands are disabled. This is particularly important for step
commands, which are valid only after the game has reported a real debugger
suspension.

## File menu

### Connect

Connects to the game's Lua-debug server and loads the current script list.
Connecting does not pause the game.

### Disconnect

Closes the debugger connection cleanly. The game clears its network-debugger
context and installed hooks. The GUI remembers ordinary breakpoints and tries
to restore them after reconnecting when a source has one unambiguous live
script match.

### Open

Opens a local `.lua` file by path. A local-only file can be read and edited,
but it has no live game script ID and cannot create a game-wide breakpoint.

### Smart open

Lists the `.lua` files beneath the configured source roots. Type part of a name
or path to filter the list, then double-click a result or choose **OK**.

### Close / Close All

Closes the current source tab or all source tabs. This does not unload scripts
from the game and does not delete breakpoints.

### Save

Writes changes in the current source tab to its existing local file. If the
source has no writable local path, **Save** opens **Save a Copy** instead.

Saving a source file does not make the running game reload it automatically.

### Save a Copy

Writes the current source text to a path you choose.

### Save All

Writes every open source tab that has a local path.

### Refresh

Requests a new active-script list. Use it after scripts are created, destroyed,
or reloaded. Runtime script IDs can change between game sessions.

### Exit

Disconnects cleanly and closes the GUI.

## Edit menu

### Cut, Copy, Paste, Undo, and Redo

Apply the requested operation to the currently focused editable control, such
as a source editor or text field.

### Find

Prompts for text and searches forward in the current source tab. The search
starts at the current cursor position.

### Find Next / Find Prev

Repeat the most recent source search forward or backward. Their shortcuts are
**F3** and **Shift+F3**.

### Go to line

Prompts for a line number, moves the current source cursor there, and centers
the line in the editor.

## Debug menu

### Break

Attaches the currently selected live script if necessary and asks it to stop at
its next executable Lua line. The game must continue running and the script must
actually execute before suspension can occur.

### Continue

Leaves the suspended state and lets the game run normally. Use this if the game
appears stuck after a debugging stop.

### Step Over

Runs the current line and stops at the next line in the same stack frame. A
function called by the current line runs without stopping inside it unless a
breakpoint is reached.

### Step Into

Runs until the next Lua line, including inside a function called by the current
line when the game can debug that source.

### Step Out

Runs until the current function returns to its caller.

### Break Thread

Requests a stop in the selected entry under **Threads**. Selecting a thread by
itself only highlights it; **Break Thread** performs the actual game command.

## Breakpoints menu

### Toggle Breakpoint

Adds or removes a breakpoint at the current source line for the current live
script. The shortcut is **Shift+F9**. Double-clicking a source line performs the
same operation.

### Toggle Global Breakpoint

Adds or removes a source-wide breakpoint at the current line. It can apply when
the same source is used by the game independently of one runtime script ID. It
requires a game-reported source; it is unavailable for a local-only file. The
shortcut is **F9**.

### Delete All Breakpoints

Removes every breakpoint known to the GUI and sends an individual removal to
the game for each valid live target.

## Source tabs

The title is `[script ID] filename`, which distinguishes multiple live scripts
using the same source. Line numbers and breakpoint dots are display decoration
and are removed when the file is saved.

- Double-click a line to toggle a script-specific breakpoint.
- A breakpoint is shown with a dot beside its line number.
- The active call-stack line has a yellow highlight.
- Changing the active call-stack frame opens the matching local source, when it
  can be found, and navigates to that frame's line.

Opening a source tab does not mean that the game has stopped at that file.

## Files tab

This is the latest game-reported list of live Lua scripts:

- **ID** is the temporary runtime script ID.
- **File** is the source path reported by the game.
- **Threads** is the number of named threads returned by the latest poll.

Click any column header to sort it. The default order places scripts with the
largest non-zero thread counts first. A green, bold row means the most recent
five-second poll returned at least one named thread. Treat this as an activity
hint, not proof that the script is executing at that exact moment.

Selecting a file makes it the current GUI script, opens its source when found,
attaches the debug hook if needed, and requests its threads.

## Call Stack tab

The call stack appears when the game sends a suspension event. The debugger
selects the deepest reported frame by default. The selected frame is
highlighted, and its source line is opened and centered when a matching local
file exists.

Double-click another frame to make it the inspection context. Frame selection
is valid only while suspended; sending it while the game is merely paused or
running can trigger a native game assertion.

## Threads tab

Lists the named threads reported for the selected script. Selecting a row sets
the target used by **Debug > Break Thread**. It does not change the call-stack
frame or pause the game on its own.

The game may have internal thread slots that it does not serialize as named
rows, so an empty list is not absolute proof that the Lua state is unused.

## Debug Output tab

Shows asynchronous Lua output sent by the game. Messages may arrive in pieces;
the GUI appends the raw pieces into one continuous output stream. This is where
calls such as `DebugMessage` normally appear.

## Variables tab

### Variable list

Each returned value has a name, the game's numeric Lua type, and a display
string. Table and userdata values are display summaries rather than complete
serialized objects.

### Script

The live script ID used for inspection. Selecting a file normally fills this
in. Leave it on the currently suspended script when inspecting stack values.

### Variable and Read Variable

Enter one variable name, such as `planet`, and choose **Read Variable**. While
suspended, the result belongs to the currently selected call-stack frame. If
you change frames, read the variable again.

Reading `_G` returns a table summary; it does not safely enumerate every global.

### Table, Table path indexes, and Expand Table (unsafe)

These controls ask the game to enumerate a table and optionally descend using
numeric path components separated by spaces. This feature is unsafe in the
analyzed game build: any displayed key or value of 255 bytes or more can cause
a native assertion or close the game.

Never expand `_G`. Use **Read Variable** for individual names whenever possible.
Proceed past the warning only when losing the current game session is
acceptable.

## Lua Console tab

Enter a valid Lua chunk and choose **Execute**. The chunk runs in the selected
live script's Lua environment. Suspension is not required.

This is not a normal expression REPL:

- `1 + 1` is not a complete Lua statement and produces a parse error.
- `return 1` does not reliably display `1`; the game does not expose returned
  Lua values as an evaluator result.
- Assignments and function calls can succeed without visible console output.
- Syntax and runtime errors are returned in the console response.

To run a function and see a simple result, write it to debug output:

```lua
DebugMessage("Result: %s", tostring(object.Get_Name()))
```

Or assign the result to a temporary global and inspect it under **Variables**:

```lua
__debug_result = object.Get_Name()
```

Then read `__debug_result`. A name that exists only as a local in a suspended
stack frame may not be visible to the console chunk even though **Read
Variable** can inspect it. Function calls can change game state; prefer known
read-only methods while experimenting.

## Breakpoints tab

This read-only table lists every breakpoint currently known to the GUI:

- **Script**: runtime script ID, or `-1` for a global breakpoint.
- **Thread**: target thread ID, or `-1` for any thread.
- **Source**: game-reported source name.
- **Line**: one-based Lua line number.
- **Condition**: condition text when supplied by the protocol or another tool.

Use the source editor or **Breakpoints** menu to change the list.

## Status bar and error dialogs

The bottom status bar is the authoritative summary of the current operation.
Important states include:

- **Running**: the game is not stopped by this debugger.
- **Break requested**: a stop is armed, but no script has reached a Lua line.
- **Suspended**: variable, call-stack, continue, and step operations are valid.
- **Error**: the last request failed or timed out.

Errors that need attention also appear in a dialog. If the game closes or the
network connection is lost, reconnect only after restarting `luadebug` in the
game.

## Settings and Help menus

The **Settings > Add Source Root...** command adds a game or mod directory to
the source search paths. Repeat it to add multiple directories; the new roots
are used by **File > Smart open...** and when opening reported source files.
Use **Settings > List Source Roots** to view the current search paths and delete
the selected directory from the session.

The **Help** menu contains **Debugger Usage**, which opens this guide in a
source tab.

## Command-line functions

The CLI uses one short-lived connection per command. Put `-v` or `-vv` before
the subcommand to show increasing protocol detail.

### scripts

Lists the game's current scripts and IDs. Add `--json` for machine-readable
output.

```powershell
uv run eaw-lua-debugger scripts
```

### threads

Lists the named threads for one live script ID.

```powershell
uv run eaw-lua-debugger threads 343 --json
```

### attach

Attaches the Lua debug hook to one script and prints the subordinate source
files reported for that context. The hook is removed when this one-shot command
disconnects, so use the GUI for actual breakpoint debugging.

```powershell
uv run eaw-lua-debugger attach 343
```

### variable

Reads one named variable from a live script.

```powershell
uv run eaw-lua-debugger variable 343 planet --json
```

### execute

Executes one Lua chunk in a live script environment.

```powershell
uv run eaw-lua-debugger execute 343 "__debug_value = 42"
```

The same non-REPL limitations described for the GUI console apply.

### table

Enumerates a known-small table only when `--unsafe` is supplied. The numeric
context ID is an opaque request identifier and the optional path is a sequence
of numeric descent components.

```powershell
uv run eaw-lua-debugger table 343 1 SmallTable --unsafe --json
```

Never use this command on `_G`.

### session

Maintains a diagnostic connection for a chosen duration, services incoming
messages, and optionally attaches one script.

```powershell
uv run eaw-lua-debugger session --script-id 343 --duration 30 --show-messages
```

### control, context, and breakpoint

These subcommands intentionally report an error. Their operations require one
persistent connection that retains attach and suspension state; use the GUI.

### hello-bytes and parse-spoot

Low-level protocol-development helpers:

- `hello-bytes CLIENT_NAME` prints a core connection request as hexadecimal.
- `parse-spoot HEX_DATAGRAM` decodes a hexadecimal core connection response.

They are not needed for normal Lua debugging.

## Common problems

### A breakpoint never fires

- Confirm that the status bar says connected.
- Refresh and make sure the script still exists.
- Prefer a green thread-active script.
- Make sure the game is running and executes that particular line.
- Keep the same debugger connection open while waiting for the stop.

### Break requested never changes to Suspended

The selected script has not reached another hooked Lua line. Continue the game,
trigger the gameplay event that uses the script, or choose another active
script. Do not use step commands until **Suspended** appears.

### Source does not open from the call stack

Add the game or mod directory as a `--source-root`. The debugger matches the
reported `Data/Scripts/...` suffix against files beneath each root.

### The game remains suspended

Choose **Continue**. If the connection was lost while suspended, reconnecting
cannot safely reconstruct the old call-stack context; restart or recover the
game's Lua-debug session as necessary.

### A variable is empty or missing

Confirm that the correct script and call-stack frame are selected. Function
parameters and locals can differ between frames. Read the variable again after
changing the frame.

### A console command shows no result

The command may have run successfully but returned no display text. Use
`DebugMessage`, assign the value to a temporary global, or inspect the changed
variable. Bare expressions are not supported.
