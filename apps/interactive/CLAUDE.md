# Interactive apps

Accepts keyboard input. Driven, not just looked at.

## Contract

- Terminal state is restored on every exit path, including
  crashes: termios settings, cursor, alternate screen
- Restore via try/finally or a context manager, never only in a
  signal handler
- q and Ctrl-C both quit
- Handle SIGWINCH and re-layout
- Persistent state is written atomically (temp file plus rename),
  never truncate-then-write
- State file lives under $XDG_DATA_HOME or ~/.local/share
- Define behavior at small sizes explicitly
- Respect NO_COLOR
- Exit non-zero on unrecoverable error, with the message on stderr
  after the terminal is restored

## Stack

Textual is allowed here and is usually the right call. Raw ANSI
with termios cbreak mode is acceptable for something small.

Decide per app. Do not mix.
