#!/usr/bin/env python3
"""Latency to one host as a scrolling sparkline in an idle tmux pane.

Run: python3 apps/ambient/ping/ping.py [host]
"""

import argparse
import bisect
import collections
import enum
import errno
import itertools
import math
import os
import select
import signal
import socket
import struct
import sys
import time
from collections import namedtuple

ENTER_ALT_SCREEN = "\033[?1049h"
LEAVE_ALT_SCREEN = "\033[?1049l"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
HOME = "\033[H"
CLEAR_SCREEN = "\033[2J"
DEFAULT_FG = "\033[39m"

GAP = " "
DEFAULT_SIZE = (80, 24)
DEFAULT_HOST = "1.1.1.1"


class Loss(enum.Enum):
    """A Sample with no round-trip time. Any other Sample is a round-trip
    time in milliseconds."""

    LOSS = "loss"


LOSS = Loss.LOSS


# Each glyph is a 10-row logical-pixel bitmap (twice the height that gets
# printed). Terminal cells are roughly twice as tall as wide, so packing
# two logical rows into one printed row (see pack_rows) undoes that and
# lets curved digits (0, 6, 8, 9) read as curved instead of blocky.
# The digits are copied from weather; "<", "l", "o" and "s" are ping's own.
DIGIT_BITMAPS = {
    "0": (
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ),
    "1": (
        "  #  ",
        " ##  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        " ### ",
    ),
    "2": (
        " ### ",
        "#   #",
        "    #",
        "    #",
        "   # ",
        "  #  ",
        " #   ",
        "#    ",
        "#    ",
        "#####",
    ),
    "3": (
        " ### ",
        "#   #",
        "    #",
        "    #",
        "  ## ",
        "  ## ",
        "    #",
        "    #",
        "#   #",
        " ### ",
    ),
    "4": (
        "   # ",
        "  ## ",
        " # # ",
        "#  # ",
        "#  # ",
        "#####",
        "   # ",
        "   # ",
        "   # ",
        "   # ",
    ),
    "5": (
        "#####",
        "#    ",
        "#    ",
        "#    ",
        "#### ",
        "    #",
        "    #",
        "    #",
        "#   #",
        " ### ",
    ),
    "6": (
        " ### ",
        "#    ",
        "#    ",
        "#    ",
        "#### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ),
    "7": (
        "#####",
        "    #",
        "   # ",
        "   # ",
        "  #  ",
        "  #  ",
        " #   ",
        " #   ",
        " #   ",
        " #   ",
    ),
    "8": (
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ),
    "9": (
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        " ####",
        "    #",
        "    #",
        "    #",
        "    #",
        " ### ",
    ),
    "<": (
        "     ",
        "     ",
        "    #",
        "   # ",
        "  #  ",
        " #   ",
        "  #  ",
        "   # ",
        "    #",
        "     ",
    ),
    "l": (
        " ##  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        " ### ",
    ),
    "o": (
        "     ",
        "     ",
        "     ",
        "     ",
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ),
    "s": (
        "     ",
        "     ",
        "     ",
        "     ",
        " ####",
        "#    ",
        " ### ",
        "    #",
        "    #",
        "#### ",
    ),
}

# Text glyphs that have an ASCII stand-in.
TEXT_GLYPHS = {True: {"sep": " · ", "more": "…", "none": "–"}, False: {"sep": " - ", "more": "...", "none": "-"}}

Caps = namedtuple("Caps", "color unicode")


def detect_caps():
    """Read terminal capabilities once, at startup."""
    return Caps(color=not os.environ.get("NO_COLOR"), unicode=unicode_ok())


def unicode_ok():
    """Whether stdout can encode every non-ASCII glyph the app draws."""
    glyphs = "█▀▄×" + EIGHTHS + "".join(TEXT_GLYPHS[True].values())
    try:
        glyphs.encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def pack_rows(rows):
    """Pack a 10-row logical bitmap into 5 printed rows via half-blocks."""
    packed = []
    for i in range(0, len(rows), 2):
        top, bottom = rows[i], rows[i + 1]
        line = []
        for t, b in zip(top, bottom):
            if t != " " and b != " ":
                line.append("█")  # full block
            elif t != " ":
                line.append("▀")  # upper half block
            elif b != " ":
                line.append("▄")  # lower half block
            else:
                line.append(" ")
        packed.append("".join(line))
    return tuple(packed)


BLOCK_GLYPHS = {ch: pack_rows(rows) for ch, rows in DIGIT_BITMAPS.items()}


def big_text(chars, caps):
    """Lines of chars drawn in big glyphs."""
    glyphs = BLOCK_GLYPHS if caps.unicode else DIGIT_BITMAPS
    drawn = [glyphs[ch] for ch in chars]
    return [GAP.join(g[i] for g in drawn) for i in range(len(drawn[0]))]


def value_text(sample):
    """A Sample as the big digits show it: whole milliseconds, halves up,
    "<1" under 1 ms, or "loss"."""
    if sample is LOSS:
        return "loss"
    if sample < 1:
        return "<1"
    return str(round_half_up(sample))


# One line of a frame: its text, and the 256-color index of its text, or
# None for the default foreground.
Line = namedtuple("Line", "text color", defaults=(None,))


def header_texts(host, address, reason, g):
    """The header, widest first: the host as typed and the address it
    resolved to, then the latest Sample's error, if it has one; then the
    error alone, which is the part that changes."""
    text = address if host == address else f"{host} ({address})"
    return [text + g["sep"] + reason, reason] if reason else [text]


# The Ramp: 256-color steps from green when fast through yellow to red when
# slow. A
# round-trip time takes the step after the last threshold it reaches, so
# step 0 is under 50 ms and step 7 is 200 ms and above. The thresholds
# between are log-spaced, 50 · 2^(k/3) ms rounded.
RAMP = (46, 118, 190, 226, 220, 214, 208, 196)
RAMP_THRESHOLDS = (50, 63, 79, 100, 126, 159, 200)  # ms
LOSS_COLOR = 244  # gray, outside the Ramp


def ramp_step(rtt):
    """The Ramp step for a round-trip time in ms."""
    return bisect.bisect_right(RAMP_THRESHOLDS, rtt)


def sample_color(sample):
    """The 256-color index a Sample is drawn in."""
    return LOSS_COLOR if sample is LOSS else RAMP[ramp_step(sample)]


EIGHTHS = "▁▂▃▄▅▆▇█"  # 1 to 8 eighths of a cell, from the bottom
SCALE_FLOOR = 20.0  # ms; the sparkline's scale is never below this


def round_half_up(x):
    return int(math.floor(x + 0.5))


def sparkline(samples, width, height, caps):
    """Rows of cells, top first, drawing samples as bars growing up from
    the bottom, one column each, newest on the right, each in its Sample's
    color. Columns left of the oldest Sample are empty.

    Each row holds 8 levels (2 in ASCII). The scale is the largest
    round-trip time among samples, at least SCALE_FLOOR. A reply always
    reaches at least one level, and a Loss fills the column.
    """
    per_row = 8 if caps.unicode else 2
    levels = per_row * height
    rtts = [s for s in samples if s is not LOSS]
    scale = max([SCALE_FLOOR, *rtts])
    rows = [[(" ", None)] * width for _ in range(height)]
    first = width - len(samples)
    for c, sample in enumerate(samples, start=first):
        if sample is LOSS:
            for row in rows:
                row[c] = (loss_glyph(caps), LOSS_COLOR)
            continue
        level = max(1, round_half_up(sample / scale * levels))
        color = sample_color(sample)
        for r, row in enumerate(rows):
            fill = min(per_row, level - per_row * (height - 1 - r))
            if fill > 0:
                row[c] = (part_glyph(fill, caps), color)
    return rows


def part_glyph(fill, caps):
    """The glyph for a cell filled to fill levels from the bottom."""
    if caps.unicode:
        return EIGHTHS[fill - 1]
    return "#" if fill == 2 else "."


def loss_glyph(caps):
    """The glyph for each cell of a Loss column."""
    if not caps.unicode:
        return "x"
    return "█" if caps.color else "×"


def stat_text(samples, g):
    """min, avg and max of the round-trip times among samples, and the
    share of them that are a Loss."""
    rtts = [s for s in samples if s is not LOSS]
    if rtts:
        low, mean, high = (f"{v:.1f}" for v in (min(rtts), sum(rtts) / len(rtts), max(rtts)))
    else:
        low = mean = high = g["none"]
    loss = f"{round_half_up(100 * (len(samples) - len(rtts)) / len(samples))}%" if samples else g["none"]
    return f"min {low}  avg {mean}  max {high}  loss {loss}"


def centered(line, cols):
    """A Line as one row of cells, centered in cols."""
    left = (cols - len(line.text)) // 2
    row = [(" ", None)] * cols
    for j, ch in enumerate(line.text):
        if 0 <= left + j < cols:
            row[left + j] = (ch, line.color)
    return row


FULL_MIN_BARS = 3  # sparkline rows the full tier needs
CHART_MIN_BARS = 2  # sparkline rows the chart tier needs
STRIP_MIN_BARS = 8  # sparkline columns the strip tier needs


def big_lines(latest, caps):
    """The big digits for the latest Sample, then the "ms" line. Blank
    before the first Sample, and no "ms" under a Loss."""
    if latest is None:
        return [Line("")] * (len(big_text("0", caps)) + 1)
    color = sample_color(latest)
    rows = [Line(row, color) for row in big_text(value_text(latest), caps)]
    return rows + [Line("" if latest is LOSS else "ms")]


def value_line(latest, g):
    """The latest Sample as one short Line: "12 ms", "loss", or "…" before
    the first Sample."""
    if latest is None:
        return Line(g["more"])
    text = value_text(latest)
    return Line(text if latest is LOSS else f"{text} ms", sample_color(latest))


def middle(cells, rows):
    """cells with blank rows above, so they sit on the pane's middle row."""
    return [[(" ", None)] * len(cells[0])] * ((rows - len(cells)) // 2) + cells


def tier_cells(history, host, address, reason, cols, rows, caps):
    """The rows of cells of the largest size tier that fits the pane, top
    first. They may be fewer than rows, but never wider than cols.

    Resolving: the host and "resolving…"; "resolving…" alone; blank.
    Otherwise, largest first: full (header, big digits, "ms" line,
    sparkline, stat line, with the header's widest form that fits); chart (header, sparkline, stat line); strip
    (the value, then a one-row sparkline); value; blank. Full and chart
    fill the pane, the sparkline taking the rows left over. Strip and value
    sit on the middle row.
    """
    g = TEXT_GLYPHS[caps.unicode]
    if rows < 1:
        return []
    if address is None:
        for text in (f"{host}{g['sep']}resolving{g['more']}", f"resolving{g['more']}"):
            if len(text) <= cols:
                return middle([centered(Line(text), cols)], rows)
        return []

    latest = history.latest
    visible = history.newest(cols)
    stat = Line(stat_text(visible, g))
    header = next((Line(text) for text in header_texts(host, address, reason, g) if len(text) <= cols), None)
    if header is not None and len(stat.text) <= cols:
        big = big_lines(latest, caps)
        top = None
        if max(len(line.text) for line in big) <= cols and rows >= 1 + len(big) + FULL_MIN_BARS + 1:
            top = [header, *big]
        elif rows >= 1 + CHART_MIN_BARS + 1:
            top = [header]
        if top is not None:
            bars = sparkline(visible, cols, rows - len(top) - 1, caps)
            return [centered(line, cols) for line in top] + bars + [centered(stat, cols)]

    value = value_line(latest, g)
    width = cols - len(value.text) - 1
    if width >= STRIP_MIN_BARS:
        strip = [(ch, value.color) for ch in value.text] + [(" ", None)] + sparkline(history.newest(width), width, 1, caps)[0]
        return middle([strip], rows)
    if len(value.text) <= cols:
        return middle([centered(value, cols)], rows)
    return []


def build_frame(history, host, address, reason, cols, rows, caps):
    """One complete frame for the pane: cursor-home, then every cell.

    Pure: the History, the host as typed and its address (None while
    resolving), the latest Sample's error (or None), the pane size and the
    capabilities are all inputs. The largest size tier that fits is drawn.
    """
    cells = tier_cells(history, host, address, reason, cols, rows, caps)
    cells = cells + [[(" ", None)] * cols for _ in range(rows - len(cells))]
    return HOME + "\r\n".join(paint(row, caps) for row in cells)


def paint(row, caps):
    """One row of cells as text, with color escapes only if color is on.
    Each row ends with the default foreground."""
    if not caps.color:
        return "".join(ch for ch, _ in row)
    out = []
    color = None
    for ch, cell_color in row:
        if cell_color != color:
            out.append(DEFAULT_FG if cell_color is None else f"\033[38;5;{cell_color}m")
            color = cell_color
        out.append(ch)
    if color is not None:
        out.append(DEFAULT_FG)
    return "".join(out)


HISTORY_CAPACITY = 1024  # Samples, about 17 minutes at one a second


class History:
    """The last HISTORY_CAPACITY Samples, newest last, in memory only."""

    def __init__(self, capacity=HISTORY_CAPACITY):
        self._samples = collections.deque(maxlen=capacity)

    def add(self, sample):
        self._samples.append(sample)

    def newest(self, n):
        """The newest n Samples, oldest first; fewer if there aren't n."""
        n = max(0, min(n, len(self._samples)))
        return list(itertools.islice(self._samples, len(self._samples) - n, None))

    @property
    def latest(self):
        """The newest Sample, or None if there is none yet."""
        return self._samples[-1] if self._samples else None

    def __len__(self):
        return len(self._samples)


ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0
ICMP_HEADER = struct.Struct("!BBHHH")  # type, code, checksum, identifier, sequence
PAYLOAD = b"tui-time ping"


def checksum(data):
    """The RFC 1071 Internet checksum of data."""
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def echo_request(ident, seq, payload=PAYLOAD):
    """An ICMP echo request, checksum included. On an unprivileged socket
    the kernel replaces the identifier and checksum with its own."""
    header = ICMP_HEADER.pack(ICMP_ECHO_REQUEST, 0, 0, ident, seq)
    return ICMP_HEADER.pack(ICMP_ECHO_REQUEST, 0, checksum(header + payload), ident, seq) + payload


def is_reply(data, ident, seq):
    """Whether data is the echo reply to Probe seq from identifier ident."""
    if len(data) < ICMP_HEADER.size:
        return False
    kind, _, _, reply_ident, reply_seq = ICMP_HEADER.unpack_from(data)
    return kind == ICMP_ECHO_REPLY and reply_ident == ident and reply_seq == seq


# How one Probe ended: its Sample, and the error's reason if the Probe
# failed with one, else None.
Outcome = namedtuple("Outcome", "sample reason")

# Short reasons for the errors a Probe most often meets. Any other error
# uses the system's message.
REASONS = {
    errno.ENETUNREACH: "network unreachable",
    errno.EHOSTUNREACH: "host unreachable",
    errno.ECONNREFUSED: "connection refused",
    errno.EMSGSIZE: "message too long",
}


def error_reason(exc):
    """The short reason for an OSError raised sending or receiving."""
    return REASONS.get(exc.errno) or (exc.strerror or str(exc)).lower()


class Prober:
    """Sends Probes to one address over an unprivileged ICMP socket.

    The socket is connected to the address, so the kernel reports an ICMP
    error reply as an error on the next recv. clock is in seconds.
    """

    def __init__(self, sock, address, clock=time.monotonic):
        self.sock = sock
        self.address = address
        self.clock = clock
        self.connected = False
        self.sent_at = None

    def fileno(self):
        return self.sock.fileno()

    def send(self, seq):
        """Send Probe seq. None once it is sent, or a Loss Outcome with the
        error's reason."""
        try:
            if not self.connected:
                self.sock.connect((self.address, 0))
                self.connected = True
            self.sent_at = self.clock()
            self.sock.send(echo_request(0, seq))
        except OSError as exc:
            return Outcome(LOSS, error_reason(exc))
        return None

    def receive(self, seq):
        """Read one datagram, once the socket is readable. The Outcome of
        Probe seq, or None if the datagram is something else."""
        try:
            data = self.sock.recv(4096)
        except OSError as exc:
            return Outcome(LOSS, error_reason(exc))
        if not is_reply(data, self.sock.getsockname()[1], seq):
            return None
        return Outcome((self.clock() - self.sent_at) * 1000, None)


class Wake(enum.Enum):
    """Why wait_for returned: the socket is readable, the deadline came, or
    the pane was resized."""

    READABLE = "readable"
    DEADLINE = "deadline"
    RESIZED = "resized"


def probe_round(prober, seq, deadline, wait, redraw):
    """Send Probe seq and wait until deadline for its Outcome. No reply by
    then is a Loss. A resize while waiting calls redraw."""
    outcome = prober.send(seq)
    while outcome is None:
        event = wait(prober.fileno(), deadline)
        if event is Wake.DEADLINE:
            return Outcome(LOSS, None)
        if event is Wake.RESIZED:
            redraw()
            continue
        outcome = prober.receive(seq)
    return outcome


# The host name doesn't exist, or has no IPv4 address.
NO_SUCH_NAME = object()
NO_SUCH_NAME_ERRORS = {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)}
RESOLVE_RETRY = 5  # seconds


def resolve(host, getaddrinfo=socket.getaddrinfo):
    """host's first IPv4 address, NO_SUCH_NAME, or None if resolution
    failed some other way and should be retried."""
    try:
        infos = getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
    except socket.gaierror as exc:
        return NO_SUCH_NAME if exc.errno in NO_SUCH_NAME_ERRORS else None
    except OSError:
        return None
    return infos[0][4][0] if infos else None


REFUSED_MESSAGE = """\
{prog}: the system refused an unprivileged ICMP socket.
Allow your group to open one by widening net.ipv4.ping_group_range, e.g.:
  sudo sysctl -w net.ipv4.ping_group_range="0 2147483647"
"""


def open_icmp(make_socket=socket.socket):
    """An unprivileged ICMP datagram socket. Exits 1 if it is refused."""
    try:
        return make_socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
    except PermissionError:
        sys.stderr.write(REFUSED_MESSAGE.format(prog=os.path.basename(sys.argv[0])))
        sys.exit(1)


def make_parser():
    parser = argparse.ArgumentParser(
        description="Latency to one host as a scrolling sparkline, one ICMP Probe a second.",
    )
    parser.add_argument(
        "host",
        nargs="?",
        default=DEFAULT_HOST,
        help="host name or IPv4 address, resolved once at startup (default: %(default)s)",
    )
    return parser


def parse_args(argv):
    """The host given on the command line."""
    return make_parser().parse_args(argv).host


def no_such_name_error(host):
    """Exit 2 with a usage error: the host name doesn't exist."""
    make_parser().error(f"no IPv4 address found for {host!r}")


def get_pane_size():
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return DEFAULT_SIZE


def next_second(now):
    """The first wall-clock second strictly after now."""
    return math.floor(now) + 1


def next_probe(last, now):
    """The wall-clock second the next Probe is due, after one sent at last:
    the second after it, even if that has just passed, as it has when a
    Loss lands at its deadline. If the app has fallen further behind than
    that, the next second after now."""
    return last + 1 if now < last + 2 else next_second(now)


def wait_for(fd, deadline, wake_fd):
    """Sleep until fd (if not None) is readable, the deadline passes, or a
    resize arrives. Returns the Wake."""
    fds = [f for f in (fd, wake_fd) if f is not None]
    while not resized:
        timeout = deadline - time.time()
        if timeout <= 0:
            return Wake.DEADLINE
        ready, _, _ = select.select(fds, [], [], timeout)
        if wake_fd in ready:
            try:
                os.read(wake_fd, 4096)
            except BlockingIOError:
                pass
        if fd is not None and fd in ready:
            return Wake.READABLE
    return Wake.RESIZED


def write_out(text):
    """Write text to stdout in one write, bypassing Python's buffering."""
    data = text.encode(sys.stdout.encoding or "utf-8")
    while data:
        data = data[os.write(1, data) :]


def teardown(caps):
    reset = DEFAULT_FG if caps.color else ""
    try:
        write_out(reset + SHOW_CURSOR + LEAVE_ALT_SCREEN)
    except OSError:
        pass


resized = False


def handle_signal(signum, frame):
    sys.exit(0)


def handle_winch(signum, frame):
    global resized
    resized = True


def rounds(prober, wait, redraw):
    """Outcomes, one a second, forever. Each Probe is sent on the
    wall-clock second, and the next is due a second later. A resize while
    waiting calls redraw."""
    seq = 0
    boundary = next_second(time.time())
    while True:
        while wait(None, boundary) is Wake.RESIZED:
            redraw()
        yield probe_round(prober, seq, boundary + 1, wait, redraw)
        seq = (seq + 1) % 65536
        boundary = next_probe(boundary, time.time())


def plain_line(sample):
    """A Sample as one plain line, for when stdout isn't a tty."""
    return "loss" if sample is LOSS else f"{sample:.1f} ms"


def run_plain(host, sock, out):
    """Print one line per Sample to out until a signal. Returns NO_SUCH_NAME
    if the host doesn't exist."""
    address = resolve(host)
    while address is None:
        time.sleep(RESOLVE_RETRY)
        address = resolve(host)
    if address is NO_SUCH_NAME:
        return NO_SUCH_NAME
    wait = lambda fd, deadline: wait_for(fd, deadline, None)  # noqa: E731
    for outcome in rounds(Prober(sock, address), wait, lambda: None):
        print(plain_line(outcome.sample), file=out, flush=True)


def run_pane(host, sock, caps, wake_fd):
    """Resolve the host, then probe it once a second, drawing a frame as
    each Sample lands and on each resize, until a signal ends the app.
    Returns NO_SUCH_NAME if the host doesn't exist, or None if the pty goes
    away."""
    history = History()
    address, error = None, None

    def draw():
        global resized
        # Take the flag before reading the size, so a resize that lands
        # mid-frame is still seen, and cleared for, next time round.
        was_resized, resized = resized, False
        cols, rows = get_pane_size()
        frame = build_frame(history, host, address, error, cols, rows, caps)
        write_out(CLEAR_SCREEN + frame if was_resized else frame)

    def wait(fd, deadline):
        return wait_for(fd, deadline, wake_fd)

    try:
        while True:
            draw()
            address = resolve(host)
            if address is NO_SUCH_NAME:
                return NO_SUCH_NAME
            if address is not None:
                break
            deadline = time.time() + RESOLVE_RETRY
            while wait(None, deadline) is Wake.RESIZED:
                draw()
        draw()
        for outcome in rounds(Prober(sock, address), wait, draw):
            history.add(outcome.sample)
            error = outcome.reason
            draw()
    except OSError:
        return None  # the pty is gone


def main():
    host = parse_args(sys.argv[1:])
    sock = open_icmp()
    caps = detect_caps()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGHUP, handle_signal)
    if not sys.stdout.isatty():
        if run_plain(host, sock, sys.stdout) is NO_SUCH_NAME:
            no_such_name_error(host)
        return

    signal.signal(signal.SIGWINCH, handle_winch)
    wake_fd, wake_write_fd = os.pipe()
    os.set_blocking(wake_fd, False)
    os.set_blocking(wake_write_fd, False)
    signal.set_wakeup_fd(wake_write_fd)

    try:
        write_out(ENTER_ALT_SCREEN + HIDE_CURSOR)
        outcome = run_pane(host, sock, caps, wake_fd)
    finally:
        teardown(caps)
    if outcome is NO_SUCH_NAME:
        no_such_name_error(host)


if __name__ == "__main__":
    main()
