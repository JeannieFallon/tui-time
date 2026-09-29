# tui-time

Small terminal apps that occupy idle tmux panes. This glossary covers the
vocabulary shared across apps.

## Language

### App classes

**Ambient app**:
An app that fills a pane and is looked at, never driven; it takes no input.
_Avoid_: Widget, screensaver, display

**Interactive app**:
An app that accepts keyboard input.

### Rendering

**Pane**:
The rectangle of terminal cells an app owns, usually a tmux pane.
_Avoid_: Window, screen

**Frame**:
One complete image of the pane, written in a single write.
_Avoid_: Draw, refresh

**Frame rate**:
How many frames per second an app produces. In the clock, the theme decides it.
_Avoid_: Tick, refresh rate

**Size tier**:
One of an app's ordered layouts, chosen by the largest one that fits the current pane.
_Avoid_: Mode, breakpoint, fallback

### Clock

**Theme**:
A named bundle of one palette and at most one effect, selected at launch.
_Avoid_: Skin, style, color scheme

**Palette**:
The fixed set of colors a theme uses.
_Avoid_: Theme (when only colors are meant)

**Effect**:
The time-varying part of a theme, such as starfield, rain, or wave.
_Avoid_: Animation, background

### Weather

**Reading**:
One successful fetch of current conditions, together with when it was fetched.
_Avoid_: Cache, snapshot, data

**Condition**:
The short description of the weather in a reading, such as "Light rain".
_Avoid_: Summary, status

**Fetch interval**:
How often the app asks for a new reading when fetches are succeeding. Distinct from frame rate.
_Avoid_: Refresh rate, poll rate

**Stale**:
A reading older than two fetch intervals. Still shown, but marked as old.

**Expired**:
A reading too old to show as current. The pane shows no reading instead.
_Avoid_: Invalid, dead
