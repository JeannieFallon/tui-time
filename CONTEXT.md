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
