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
How many frames per second an app produces. It is higher while an effect is showing: in the clock the theme sets the rate, in weather the effect does.
_Avoid_: Tick, refresh rate

**Size tier**:
One of an app's ordered layouts, chosen by the largest one that fits the current pane.
_Avoid_: Mode, breakpoint, fallback

**Palette**:
The fixed set of colors an app, or a clock theme, draws with.
_Avoid_: Theme (when only colors are meant)

**Effect**:
The time-varying, decorative part of a frame, such as starfield or rain. In the clock the theme picks it; in weather the sky does.
_Avoid_: Animation, background

### Clock

**Theme**:
A named bundle of one palette and at most one effect, selected at launch.
_Avoid_: Skin, style, color scheme

### Weather

**Reading**:
One successful fetch of current conditions and today's forecast, together with when it was fetched. It goes stale and expires as a whole.
_Avoid_: Cache, snapshot, data

**Condition**:
The short description of the weather in a reading, such as "Light rain".
_Avoid_: Summary, status

**Sky**:
The coarse group a condition falls into: Clear, Cloudy, Rain, Snow, or Storm. Many conditions share one sky.
_Avoid_: Condition type, category, icon (for the group itself)

**Fetch interval**:
How often the app asks for a new reading when fetches are succeeding. Distinct from frame rate.
_Avoid_: Refresh rate, poll rate

**Stale**:
A reading older than two fetch intervals. Still shown, but marked as old.

**Expired**:
A reading too old to show as current. The pane shows no reading instead.
_Avoid_: Invalid, dead

### Ping

**Probe**:
One echo request sent to the host.
_Avoid_: Packet, ping (for a single request)

**Sample**:
The outcome of one probe: a round-trip time or a loss.
_Avoid_: Reply, RTT (for the outcome as a whole), measurement

**Loss**:
A sample whose probe got no reply before the next probe was due.
_Avoid_: Timeout, drop

**History**:
The fixed-capacity ring of recent samples, newest last. Lives only as long as the app runs.
_Avoid_: Buffer, log, window

**Ramp**:
The ordered palette steps a sample's round-trip time maps onto, from green when fast through yellow to red when slow. A loss is outside the ramp.
_Avoid_: Gradient, heatmap, scale
