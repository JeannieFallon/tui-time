# ping

Latency to one host, one ICMP Probe a second: the current Sample in
big digits, a scrolling sparkline of recent Samples colored from blue
when fast to hot pink when slow, and min, avg, max and loss over what
the sparkline shows.

## Usage

```
python3 apps/ambient/ping/ping.py
python3 apps/ambient/ping/ping.py one.one.one.one
python3 apps/ambient/ping/ping.py 192.168.1.1
```

The one optional argument is a host name or IPv4 address, `1.1.1.1`
by default. `-h` prints help. There are no other flags.

Exit status:

| Code | When |
|---|---|
| 0 | SIGINT (Ctrl-C), SIGTERM or SIGHUP (a closed tmux pane). All three restore the cursor and the main screen. |
| 1 | the system refused an unprivileged ICMP socket. The message on stderr names `net.ipv4.ping_group_range`. |
| 2 | usage error (more than one argument), or a host name that doesn't exist or has no IPv4 address. The app leaves the alternate screen first, then prints the error. |

The app draws on the alternate screen, so nothing goes into
scrollback. Each frame is written in one write and covers every cell
of the pane.

## Probing

The app opens `socket(AF_INET, SOCK_DGRAM, IPPROTO_ICMP)`, the
unprivileged ICMP socket Linux offers to groups inside
`net.ipv4.ping_group_range`. It needs no root and runs no subprocess.
If the socket is refused, it exits 1 before drawing anything. To
allow every group:

```
sudo sysctl -w net.ipv4.ping_group_range="0 2147483647"
```

The host is resolved once, at startup, to its first IPv4 address, and
never again. A name that doesn't exist (`EAI_NONAME`), or that has no
IPv4 address (`EAI_NODATA`), exits 2 with
`no IPv4 address found for 'name'`. Any other resolution failure,
such as the network being down, shows the resolving pane
(`one.one.one.one · resolving…`) and retries every 5 seconds, without
backing off.

A Probe is sent on each wall-clock second. Its Sample is either its
round-trip time, measured on the monotonic clock, or a Loss. A Loss
is recorded when:

- no reply has come back by the time the next Probe is due
- the send fails (`network unreachable`, `host unreachable`, …)
- an ICMP error comes back. The socket is connected to the address,
  so the kernel reports an ICMP error as an error on the next read.

When the latest Sample is a Loss from a failed send or an ICMP error,
the reason follows the header:
`one.one.one.one (1.1.1.1) · network unreachable`. When that is too
wide for the pane, the header shows the reason alone. The reason goes
when the next Sample isn't one. A Loss that got no reply has no
reason.

A frame is drawn when each Sample lands. A resize redraws at once,
even while a reply is awaited. The pane draws no Effect.

## History and the sparkline

The History keeps the last 1024 Samples, about 17 minutes, in memory
only. The sparkline draws the newest W of them, one column each,
newest on the right, where W is the sparkline's width. It scrolls left
a column a second. Before the History fills, the columns on the left
are empty. Widening the pane reveals older Samples that were already
kept.

Bars grow up from the bottom in eighth blocks `▁▂▃▄▅▆▇█`, stacked
across the sparkline's rows, so H rows give 8·H levels. The scale is
the largest round-trip time among the drawn Samples, with a floor of
20 ms. A spike rescales the whole sparkline until it scrolls out of
view. A reply too fast to reach one level still draws one, so it
never looks like an empty column. A Loss is a full-height column.

The stat line covers the same Samples as the sparkline:

```
min 9.8  avg 12.1  max 41.0  loss 2%
```

Min, avg and max leave Losses out. Loss is the share of Samples that
are Losses, rounded to a whole percent. With only Losses in view, min,
avg and max read `–`. With no Samples yet, all four do.

## The Ramp

Each sparkline column, and the big digits, take the color of their
own Sample, in 256-color:

| Step | Round-trip time | Color |
|---|---|---|
| 0 | under 50 ms | 26 |
| 1 | 50 ms | 62 |
| 2 | 63 ms | 56 |
| 3 | 79 ms | 92 |
| 4 | 100 ms | 128 |
| 5 | 126 ms | 164 |
| 6 | 159 ms | 199 |
| 7 | 200 ms and above | 205 |

Each step starts at its threshold. The thresholds are log-spaced,
50 · 2^(k/3) ms rounded. A Loss is gray (244), outside the Ramp. The
header, `ms` line and stat line use the terminal's default
foreground.

## Big digits

The current Sample in whole milliseconds, rounded half up, with `ms`
on the line under it. Under 1 ms reads `<1`. A Loss reads `loss` in
big letters, with no `ms` line. Before the first Sample lands, the
digits are blank.

## Pane sizes

The largest tier that fits is drawn:

| Tier | Content | Needs |
|---|---|---|
| full | header, big digits, `ms` line, sparkline, stat line | the widest of the header, digits and stat line × 11 rows (16 in ASCII) |
| chart | header, sparkline, stat line | the wider of the header and stat line × 4 rows |
| strip | `12 ms ▂▃▅▂▁`: the value, then a one-row sparkline | the value plus 9 columns × 1 row |
| value | `12 ms` or `loss` | its width × 1 row |
| blank | nothing | anything smaller |

Full and chart fill the pane. The header, digits and stat line are
centered, and the sparkline takes the full width and every row left
over: at least 3 in full and 2 in chart. Strip and value sit on the
middle row. The strip's sparkline fills the rest of the line, at least
8 columns, and the stat line goes with the tiers that show it. Before
the first Sample, the value reads `…`.

The header and stat line set the width full and chart need, so they
move with the host name, the error reason and the numbers. A header
with a reason falls back to the reason alone before a tier is dropped. The header
`one.one.one.one (1.1.1.1)` is 25 columns wide, and the stat line
around 37. Big digits are 5 columns wide with a 1-column gap.

While resolving, the pane shows `host · resolving…`, then
`resolving…`, then nothing.

Nothing is clipped. On resize the screen is cleared once and the tier
is picked again.

## NO_COLOR and ASCII

When `NO_COLOR` is set to a non-empty value, the app emits no SGR
escapes. A Loss column is drawn as `×` so it stays apart from a tall
bar.

When stdout's encoding can't encode the block characters, `×`, `·`,
`…` and `–` (for example `PYTHONIOENCODING=ascii`), the sparkline uses
`#` for a full cell and `.` for a part-filled top, 2 levels a row, and
`x` for a Loss. Big digits are drawn with `#`, 10 rows tall. `·`
becomes `-`, `…` becomes `...` and `–` becomes `-`.

## Not a terminal

When stdout isn't a tty, as with a pipe, a redirect or a status line,
the app prints one line per Sample, flushed as each lands, until a
signal:

```
12.3 ms
loss
```

It emits no escape codes and doesn't enter the alternate screen. A
resolution failure other than a missing name is retried every 5
seconds without printing anything.

## Simulating

`simulate.py`, beside the app, runs the same pane with a fake prober,
so every Ramp step and the Loss columns can be seen without a slow
network:

```
python3 apps/ambient/ping/simulate.py
python3 apps/ambient/ping/simulate.py --prefill 0
```

The host reads `simulated (192.0.2.1)`. The script sweeps up through
10, 35, 55, 70, 90, 110, 140, 180 and 260 ms and back down, three
Samples at each, so every step shows. Then it adds four
Losses with no reply and four `network unreachable` send errors, and
repeats.
Replies land at once. A scripted Loss lands when its Probe times out,
like a real one.

`--prefill N` starts the History with N scripted Samples, two passes
by default, so the pane is full from the first frame. `NO_COLOR` and
`PYTHONIOENCODING=ascii` apply as they do to the app. Everything else
is the app's own code: the layouts, the loop, the signals and the
teardown.

## Known limitations

- IPv4 only, and one host.
- Needs `net.ipv4.ping_group_range` to include the user's group, so
  Linux only in practice. There is no fallback to a setuid `ping` or
  TCP.
- The host is resolved only once. If its address changes, the app
  keeps probing the old one until restarted.
- Name resolution blocks the draw loop. A resolver that hangs holds
  the resolving pane, and resizes, until it returns.
- The History is lost on restart.
- A reply that arrives after the next Probe is due is ignored. Its
  Probe has already counted as a Loss.
- Timing follows the wall clock. After a suspend or a clock jump the
  app resumes on the next second, and the gap is not filled with
  Losses.
- Text widths are counted in characters. A host name with double-width
  characters can be wider on screen than the tier check assumes.
- Unicode support is judged from stdout's encoding, not from the font.
