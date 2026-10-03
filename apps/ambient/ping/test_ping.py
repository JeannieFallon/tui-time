"""Tests for ping.py. Run: python3 -m unittest apps/ambient/ping/test_ping.py"""

import errno
import os
import re
import socket
import struct
import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ping  # noqa: E402

CSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]")
UNICODE = ping.Caps(color=True, unicode=True)
ASCII = ping.Caps(color=True, unicode=False)
PLAIN = ping.Caps(color=False, unicode=True)
HOST, ADDRESS = "one.one.one.one", "1.1.1.1"


def grid(frame):
    """Strip escape codes and return the frame as a list of rows."""
    assert frame.startswith("\033[H"), "frame must start with cursor-home"
    return CSI.sub("", frame).split("\r\n")


def lines_of(frame):
    """The frame's non-blank lines, stripped."""
    return [line.strip() for line in grid(frame) if line.strip()]


def history(*samples):
    h = ping.History()
    for sample in samples:
        h.add(sample)
    return h


def frame(h, cols=80, rows=24, caps=UNICODE, reason=None, host=HOST, address=ADDRESS):
    return ping.build_frame(h, host, address, reason, cols, rows, caps)


class EchoRequestTest(unittest.TestCase):
    def test_packs_type_code_checksum_identifier_sequence_and_payload(self):
        packet = ping.echo_request(0x1234, 7, b"abcd")
        self.assertEqual(packet[:2], b"\x08\x00")
        self.assertEqual(struct.unpack("!HH", packet[4:8]), (0x1234, 7))
        self.assertEqual(packet[8:], b"abcd")

    def test_checksum_makes_the_packet_sum_to_all_ones(self):
        # RFC 1071: the ones'-complement sum of a packet with its checksum
        # in place is 0xffff.
        for payload in (b"", b"abcd", b"odd"):
            packet = ping.echo_request(0xBEEF, 65535, payload)
            if len(packet) % 2:
                packet += b"\0"
            total = sum(struct.unpack(f"!{len(packet) // 2}H", packet))
            while total >> 16:
                total = (total & 0xFFFF) + (total >> 16)
            self.assertEqual(total, 0xFFFF, payload)

    def test_known_checksum(self):
        # Worked by hand: 0x0800 + 0x0001 + 0x0001 = 0x0802, complement 0xf7fd.
        self.assertEqual(ping.echo_request(1, 1, b"")[2:4], b"\xf7\xfd")


class ReplyMatchTest(unittest.TestCase):
    def reply(self, ident=4, seq=7, kind=0):
        return struct.pack("!BBHHH", kind, 0, 0, ident, seq) + b"payload"

    def test_accepts_the_echo_reply_to_this_identifier_and_sequence(self):
        self.assertTrue(ping.is_reply(self.reply(), 4, 7))

    def test_ignores_other_sequences_identifiers_and_types(self):
        self.assertFalse(ping.is_reply(self.reply(seq=6), 4, 7))
        self.assertFalse(ping.is_reply(self.reply(ident=5), 4, 7))
        self.assertFalse(ping.is_reply(self.reply(kind=8), 4, 7))

    def test_ignores_truncated_packets(self):
        self.assertFalse(ping.is_reply(self.reply()[:7], 4, 7))


class ValueTextTest(unittest.TestCase):
    def test_whole_milliseconds_under_1_and_loss(self):
        cases = [(0.2, "<1"), (0.99, "<1"), (1.0, "1"), (12.3, "12"), (12.5, "13"), (199.6, "200"), (ping.LOSS, "loss")]
        for sample, expected in cases:
            with self.subTest(sample=sample):
                self.assertEqual(ping.value_text(sample), expected)


class HeaderTest(unittest.TestCase):
    def test_host_as_typed_then_its_address(self):
        self.assertEqual(lines_of(frame(history(12.3)))[0], "one.one.one.one (1.1.1.1)")

    def test_address_alone_when_it_was_typed_as_one(self):
        self.assertEqual(lines_of(frame(history(12.3), host=ADDRESS))[0], "1.1.1.1")


def big_rows(frame):
    """The big-glyph rows of an ASCII frame, trimmed to their bounding box."""
    rows = [line for line in grid(frame) if "#" in line]
    left = min(len(r) - len(r.lstrip()) for r in rows)
    width = max(len(r.rstrip()) for r in rows) - left
    return [r[left : left + width].ljust(width) for r in rows]


class BigDigitTest(unittest.TestCase):
    # ASCII frames just tall enough for the full tier: header on row 0,
    # the big glyphs on rows 1 to 10.
    def big(self, sample):
        lines = grid(frame(history(sample), cols=40, rows=17, caps=ASCII))
        return big_rows("\033[H" + "\r\n".join(lines[1:11]))

    def test_current_sample_in_big_digits_with_ms_under_them(self):
        self.assertEqual(
            self.big(12.3),
            [
                " #    ### ",
                "##   #   #",
                " #       #",
                " #       #",
                " #      # ",
                " #     #  ",
                " #    #   ",
                " #   #    ",
                " #   #    ",
                "###  #####",
            ],
        )
        self.assertEqual(lines_of(frame(history(12.3), cols=40, rows=17, caps=ASCII))[11], "ms")

    def test_loss_reads_loss_in_four_big_glyphs_with_no_ms(self):
        rows = self.big(ping.LOSS)
        # Four 5-wide glyphs and three gaps, less the blank column left of "l".
        self.assertEqual((len(rows), len(rows[0])), (10, 22))
        self.assertNotIn("ms", lines_of(frame(history(ping.LOSS), cols=40, rows=17, caps=ASCII)))

    def test_under_1_ms_reads_less_than_1(self):
        rows = self.big(0.4)
        # "<" spans columns 1-4 of its glyph and "1" columns 7-9 after the gap.
        self.assertEqual(len(rows[0]), 9)
        self.assertNotEqual(rows, self.big(1.0))

    def test_unicode_digits_are_five_rows(self):
        lines = grid(frame(history(12.3), cols=40, rows=11))
        self.assertTrue(all(set(line.strip()) <= set("█▀▄ ") for line in lines[1:6]))
        self.assertEqual(lines[6].strip(), "ms")


class FrameCoverageTest(unittest.TestCase):
    def test_frames_cover_every_cell_at_a_range_of_sizes(self):
        states = [history(), history(12.3), history(ping.LOSS, 250.0, 0.5)]
        for h in states:
            for caps in (UNICODE, ASCII, PLAIN):
                for cols, rows in [(80, 24), (120, 40), (40, 11), (20, 4), (10, 3), (1, 1), (0, 0)]:
                    with self.subTest(h=h.newest(3), caps=caps, cols=cols, rows=rows):
                        cells = grid(frame(h, cols, rows, caps))
                        if rows == 0:
                            self.assertEqual(cells, [""])
                        else:
                            self.assertEqual([len(line) for line in cells], [cols] * rows)


class FakeSocket:
    """Stands in for a connected ICMP datagram socket. Each recv returns
    the next queued datagram, or raises it if it is an exception."""

    def __init__(self, port=4, send_error=None, connect_error=None):
        self.port = port
        self.send_error = send_error
        self.connect_error = connect_error
        self.queue = []
        self.sent = []
        self.connected = None

    def connect(self, addr):
        if self.connect_error:
            raise self.connect_error
        self.connected = addr

    def getsockname(self):
        return ("192.168.0.2", self.port)

    def send(self, data):
        if self.send_error:
            raise self.send_error
        self.sent.append(data)
        return len(data)

    def recv(self, size):
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def fileno(self):
        return -1


def echo_reply(ident=4, seq=0):
    return struct.pack("!BBHHH", 0, 0, 0, ident, seq) + ping.PAYLOAD


class FakeClock:
    def __init__(self, *times):
        self.times = list(times)

    def __call__(self):
        return self.times.pop(0)


class ProberTest(unittest.TestCase):
    def test_reply_to_the_probe_is_its_round_trip_time_in_ms(self):
        sock = FakeSocket()
        sock.queue.append(echo_reply(seq=3))
        prober = ping.Prober(sock, ADDRESS, clock=FakeClock(10.0, 10.0123))
        self.assertIsNone(prober.send(3))
        self.assertEqual(sock.connected, (ADDRESS, 0))
        outcome = prober.receive(3)
        self.assertAlmostEqual(outcome.sample, 12.3)
        self.assertIsNone(outcome.reason)

    def test_a_reply_to_an_earlier_probe_is_ignored(self):
        sock = FakeSocket()
        sock.queue.append(echo_reply(seq=2))
        prober = ping.Prober(sock, ADDRESS, clock=FakeClock(10.0, 10.5))
        prober.send(3)
        self.assertIsNone(prober.receive(3))

    def test_a_send_error_is_a_loss_with_its_reason(self):
        sock = FakeSocket(send_error=OSError(errno.ENETUNREACH, "Network is unreachable"))
        outcome = ping.Prober(sock, ADDRESS).send(0)
        self.assertEqual(outcome, ping.Outcome(ping.LOSS, "network unreachable"))

    def test_a_connect_error_is_a_loss_with_its_reason(self):
        sock = FakeSocket(connect_error=OSError(errno.ENETUNREACH, "Network is unreachable"))
        self.assertEqual(ping.Prober(sock, ADDRESS).send(0), ping.Outcome(ping.LOSS, "network unreachable"))

    def test_an_icmp_error_reply_is_a_loss_with_its_reason(self):
        # On a connected ICMP socket the kernel reports an error reply as an
        # error on the next recv.
        sock = FakeSocket()
        sock.queue.append(OSError(errno.EHOSTUNREACH, "No route to host"))
        prober = ping.Prober(sock, ADDRESS, clock=FakeClock(10.0))
        prober.send(0)
        self.assertEqual(prober.receive(0), ping.Outcome(ping.LOSS, "host unreachable"))

    def test_other_errors_use_the_system_message_in_lower_case(self):
        sock = FakeSocket(send_error=OSError(errno.EINVAL, "Invalid argument"))
        self.assertEqual(ping.Prober(sock, ADDRESS).send(0).reason, "invalid argument")


class FakeProber:
    """Stands in for a Prober: send and receive answer from queues."""

    def __init__(self, send=None, receive=()):
        self.send_outcome = send
        self.received = list(receive)

    def send(self, seq):
        return self.send_outcome

    def receive(self, seq):
        return self.received.pop(0)

    def fileno(self):
        return -1


class FakeWait:
    """Stands in for wait_for: returns queued events, records deadlines."""

    def __init__(self, *events):
        self.events = list(events)
        self.deadlines = []

    def __call__(self, fd, deadline):
        self.deadlines.append(deadline)
        return self.events.pop(0)


class ProbeRoundTest(unittest.TestCase):
    def test_the_reply_ends_the_round(self):
        prober = FakeProber(receive=[None, ping.Outcome(12.3, None)])
        wait = FakeWait(ping.Wake.READABLE, ping.Wake.READABLE)
        self.assertEqual(ping.probe_round(prober, 0, 101.0, wait, lambda: None), ping.Outcome(12.3, None))
        self.assertEqual(wait.deadlines, [101.0, 101.0])

    def test_no_reply_before_the_next_probe_is_due_is_a_loss(self):
        wait = FakeWait(ping.Wake.READABLE, ping.Wake.DEADLINE)
        outcome = ping.probe_round(FakeProber(receive=[None]), 0, 101.0, wait, lambda: None)
        self.assertEqual(outcome, ping.Outcome(ping.LOSS, None))

    def test_a_send_error_ends_the_round_at_once(self):
        failed = ping.Outcome(ping.LOSS, "network unreachable")
        wait = FakeWait()
        self.assertEqual(ping.probe_round(FakeProber(send=failed), 0, 101.0, wait, lambda: None), failed)
        self.assertEqual(wait.deadlines, [])

    def test_a_resize_while_waiting_redraws_and_keeps_waiting(self):
        redraws = []
        prober = FakeProber(receive=[ping.Outcome(12.3, None)])
        wait = FakeWait(ping.Wake.RESIZED, ping.Wake.READABLE)
        outcome = ping.probe_round(prober, 0, 101.0, wait, lambda: redraws.append(1))
        self.assertEqual((outcome, redraws), (ping.Outcome(12.3, None), [1]))


class ScheduleTest(unittest.TestCase):
    def test_the_next_probe_is_due_on_the_second_after_the_last(self):
        self.assertEqual(ping.next_probe(100, 100.012), 101)

    def test_a_loss_lands_at_the_deadline_without_skipping_a_second(self):
        # The Loss of the Probe sent at 100 lands just after 101.
        self.assertEqual(ping.next_probe(100, 101.0004), 101)

    def test_after_falling_behind_probes_resume_on_the_next_second(self):
        self.assertEqual(ping.next_probe(100, 250.5), 251)


class ErrorHeaderTest(unittest.TestCase):
    def test_the_latest_errors_reason_follows_the_header(self):
        lines = lines_of(frame(history(12.3, ping.LOSS), reason="network unreachable"))
        self.assertEqual(lines[0], "one.one.one.one (1.1.1.1) · network unreachable")

    def test_ascii_separator(self):
        lines = lines_of(frame(history(ping.LOSS), caps=ASCII, rows=40, reason="network unreachable"))
        self.assertEqual(lines[0], "one.one.one.one (1.1.1.1) - network unreachable")


def lookup(result):
    """A stand-in for socket.getaddrinfo that returns or raises result."""

    def getaddrinfo(host, port, family, kind):
        if isinstance(result, BaseException):
            raise result
        return result

    return getaddrinfo


class ResolveTest(unittest.TestCase):
    def test_first_ipv4_address(self):
        infos = [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("1.0.0.1", 0)), (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("1.1.1.1", 0))]
        self.assertEqual(ping.resolve(HOST, lookup(infos)), "1.0.0.1")

    def test_a_name_that_does_not_exist(self):
        error = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        self.assertIs(ping.resolve("nope.invalid", lookup(error)), ping.NO_SUCH_NAME)

    def test_a_name_with_no_ipv4_address_counts_as_not_existing(self):
        error = socket.gaierror(socket.EAI_NODATA, "No address associated with hostname")
        self.assertIs(ping.resolve("ipv6.example", lookup(error)), ping.NO_SUCH_NAME)

    def test_any_other_failure_is_retried(self):
        for error in (socket.gaierror(socket.EAI_AGAIN, "Temporary failure"), OSError(errno.ENETUNREACH, "down")):
            with self.subTest(error=error):
                self.assertIsNone(ping.resolve(HOST, lookup(error)))

    def test_resolving_pane(self):
        self.assertEqual(lines_of(frame(history(), address=None)), ["one.one.one.one · resolving…"])


class OpenSocketTest(unittest.TestCase):
    def test_a_refused_socket_exits_1_naming_ping_group_range(self):
        def refuse(family, kind, proto):
            raise PermissionError(errno.EACCES, "Permission denied")

        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            ping.open_icmp(refuse)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("net.ipv4.ping_group_range", err.getvalue())

    def test_opens_an_unprivileged_icmp_datagram_socket(self):
        calls = []
        ping.open_icmp(lambda *args: calls.append(args) or "sock")
        self.assertEqual(calls, [(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)])


class ArgsTest(unittest.TestCase):
    def test_default_host(self):
        self.assertEqual(ping.parse_args([]), "1.1.1.1")
        self.assertEqual(ping.parse_args(["example.com"]), "example.com")

    def test_extra_arguments_exit_2(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as cm:
            ping.parse_args(["a", "b"])
        self.assertEqual(cm.exception.code, 2)


class HistoryTest(unittest.TestCase):
    def test_wraps_at_capacity_keeping_the_newest(self):
        h = ping.History(capacity=3)
        for sample in (1.0, 2.0, ping.LOSS, 4.0):
            h.add(sample)
        self.assertEqual(h.newest(10), [2.0, ping.LOSS, 4.0])
        self.assertEqual(len(h), 3)

    def test_default_capacity_is_1024(self):
        h = history(*range(1, 1100))
        self.assertEqual(len(h), 1024)
        self.assertEqual(h.newest(1024)[0], 1099 - 1023)

    def test_newest_w_oldest_first(self):
        h = history(1.0, 2.0, 3.0, 4.0)
        self.assertEqual(h.newest(2), [3.0, 4.0])
        self.assertEqual(h.newest(0), [])


def spark(h, cols=10, height=3, caps=PLAIN):
    """The sparkline rows of a full-tier frame with this many sparkline
    rows: the rows between the "ms" line and the stat line."""
    rows = grid(frame(h, cols=cols, rows=8 + height, caps=caps))
    return rows[7 : 7 + height]


def column(rows, c=-1):
    """One column of the sparkline, top to bottom."""
    return "".join(row[c] for row in rows)


class SparklineTest(unittest.TestCase):
    # With 3 rows there are 24 levels. A 24 ms Sample in the window makes
    # the scale 24 ms, so 1 ms is one level.
    def test_bar_heights_at_eighth_block_boundaries(self):
        cases = [(1.0, "  ▁"), (7.0, "  ▇"), (8.0, "  █"), (9.0, " ▁█"), (16.0, " ██"), (17.0, "▁██"), (24.0, "███")]
        for rtt, expected in cases:
            with self.subTest(rtt=rtt):
                self.assertEqual(column(spark(history(24.0, rtt), cols=40)), expected)

    def test_a_reply_too_small_to_reach_a_level_still_shows_one(self):
        self.assertEqual(column(spark(history(24.0, 0.2), cols=40)), "  ▁")

    def test_scale_has_a_20_ms_floor(self):
        # 5 ms of 20 ms is 6 of 24 levels.
        self.assertEqual(column(spark(history(5.0), cols=40)), "  ▆")
        self.assertEqual(column(spark(history(20.0), cols=40)), "███")

    def test_a_spike_rescales_the_window(self):
        self.assertEqual(column(spark(history(10.0, 30.0, 10.0), cols=40)), "  █")
        self.assertEqual(column(spark(history(10.0, 10.0), cols=40)), " ▄█")

    def test_a_spike_scrolled_out_of_view_no_longer_scales(self):
        h = history(100.0, *[10.0] * 40)
        self.assertEqual(column(spark(h, cols=40)), " ▄█")
        # 10 ms of 100 ms is 2.4 of 24 levels.
        self.assertEqual(column(spark(h, cols=41)), "  ▂")

    def test_loss_is_a_full_height_column(self):
        self.assertEqual(column(spark(history(5.0, ping.LOSS), cols=40, caps=UNICODE)), "███")

    def test_newest_on_the_right_empty_columns_on_the_left(self):
        rows = spark(history(20.0, ping.LOSS, 20.0), cols=40)
        self.assertEqual([column(rows, c) for c in range(36, 40)], ["   ", "███", "×××", "███"])

    def test_widening_reveals_older_samples(self):
        h = history(*[20.0] * 30, *[ping.LOSS] * 10)
        narrow, wide = spark(h, cols=40), spark(h, cols=60)
        self.assertEqual(narrow[-1].count("█"), 30)
        self.assertEqual(wide[-1].count("█"), 30)
        self.assertEqual(wide[-1][:20], " " * 20)

    def test_sparkline_fills_the_height_left_over(self):
        rows = grid(frame(history(20.0), cols=40, rows=24))
        self.assertEqual(column(rows[7:23]), "█" * 16)


class StatLineTest(unittest.TestCase):
    def stat(self, h, cols=40, caps=UNICODE):
        # The full tier with 3 sparkline rows: 11 rows, 16 in ASCII.
        return lines_of(frame(h, cols=cols, rows=11 if caps.unicode else 16, caps=caps))[-1]

    def test_min_avg_max_ignore_losses_and_loss_counts_them(self):
        self.assertEqual(self.stat(history(9.8, 12.0, ping.LOSS, 41.0)), "min 9.8  avg 20.9  max 41.0  loss 25%")

    def test_only_the_visible_samples_count(self):
        h = history(500.0, *[10.0] * 38, ping.LOSS, ping.LOSS)
        self.assertEqual(self.stat(h), "min 10.0  avg 10.0  max 10.0  loss 5%")

    def test_all_loss(self):
        self.assertEqual(self.stat(history(ping.LOSS, ping.LOSS)), "min –  avg –  max –  loss 100%")
        self.assertEqual(self.stat(history(ping.LOSS), caps=ASCII), "min -  avg -  max -  loss 100%")

    def test_empty(self):
        self.assertEqual(self.stat(history()), "min –  avg –  max –  loss –")


SGR = re.compile(r"\033\[([0-9;]*)m")


def styled(frame):
    """The frame as rows of (character, 256-color index or None)."""
    rows = []
    for line in frame[len("\033[H") :].split("\r\n"):
        color, row, i = None, [], 0
        while i < len(line):
            m = SGR.match(line, i)
            if m:
                params = m.group(1)
                color = int(params.split(";")[2]) if params.startswith("38;5;") else None
                i = m.end()
            else:
                row.append((line[i], color))
                i += 1
        rows.append(row)
    return rows


class RampTest(unittest.TestCase):
    def test_step_at_and_around_each_threshold(self):
        cases = [(0.1, 0), (49.9, 0), (50.0, 1), (62.9, 1), (63.0, 2), (79.0, 3), (100.0, 4), (126.0, 5), (159.0, 6), (199.9, 6), (200.0, 7), (999.0, 7)]
        for rtt, step in cases:
            with self.subTest(rtt=rtt):
                self.assertEqual(ping.ramp_step(rtt), step)

    def test_steps_run_from_green_through_yellow_to_red(self):
        self.assertEqual(ping.RAMP, (46, 118, 190, 226, 220, 214, 208, 196))

    def test_each_column_takes_its_own_samples_step(self):
        rows = styled(frame(history(30.0, 70.0, 250.0, ping.LOSS), cols=40, rows=11))
        bottom = rows[9]
        self.assertEqual([color for _, color in bottom[36:]], [46, 190, 196, 244])  # steps 0, 2, 7 and gray

    def test_a_loss_column_is_gray_all_the_way_up(self):
        rows = styled(frame(history(5.0, ping.LOSS), cols=40, rows=11))
        self.assertEqual([rows[r][39] for r in range(7, 10)], [("█", 244)] * 3)

    def test_big_digits_take_the_current_samples_step(self):
        for sample, color in [(12.3, 46), (150.0, 214), (ping.LOSS, 244)]:
            with self.subTest(sample=sample):
                rows = styled(frame(history(sample), cols=40, rows=11))
                drawn = {c for row in rows[1:6] for ch, c in row if ch != " "}
                self.assertEqual(drawn, {color})

    def test_header_ms_and_stat_lines_use_the_default_foreground(self):
        rows = styled(frame(history(250.0), cols=50, rows=11, reason="host unreachable"))
        for r in (0, 6, 10):
            with self.subTest(row=r):
                self.assertEqual({c for ch, c in rows[r] if ch != " "}, {None})


class NoColorTest(unittest.TestCase):
    def test_no_sgr_at_all(self):
        for h in (history(), history(12.3, ping.LOSS, 250.0)):
            for cols, rows in [(80, 24), (40, 11), (20, 4), (10, 1)]:
                with self.subTest(cols=cols, rows=rows):
                    body = frame(h, cols, rows, PLAIN)[len("\033[H") :]
                    self.assertNotIn("\033", body)

    def test_a_loss_column_is_drawn_as_a_cross(self):
        self.assertEqual(column(spark(history(5.0, ping.LOSS), cols=40, caps=PLAIN)), "×××")


class AsciiTest(unittest.TestCase):
    def spark(self, h):
        # ASCII big digits are 10 rows: header, 10, ms, 3 sparkline rows, stat.
        return grid(frame(h, cols=40, rows=16, caps=ASCII))[12:15]

    def test_full_cells_are_hashes_and_a_partial_top_is_a_dot(self):
        # 3 rows of 2 levels; a 24 ms Sample makes 4 ms one level.
        cases = [(4.0, "  ."), (8.0, "  #"), (12.0, " .#"), (24.0, "###")]
        for rtt, expected in cases:
            with self.subTest(rtt=rtt):
                self.assertEqual(column(self.spark(history(24.0, rtt))), expected)

    def test_a_loss_column_is_xs(self):
        self.assertEqual(column(self.spark(history(5.0, ping.LOSS))), "xxx")

    def test_ascii_frames_are_pure_ascii(self):
        caps_list = (ASCII, ping.Caps(color=False, unicode=False))
        for caps in caps_list:
            for h in (history(), history(0.4, 12.3, ping.LOSS, 250.0)):
                for cols, rows in [(80, 24), (40, 16), (40, 11), (20, 4), (10, 1)]:
                    for address in (ADDRESS, None):
                        with self.subTest(caps=caps, cols=cols, rows=rows, address=address):
                            f = frame(h, cols, rows, caps, reason="host unreachable", address=address)
                            f.encode("ascii")


class SizeTierTest(unittest.TestCase):
    # For history(12.3): the header is 25 wide, the stat line
    # "min 12.3  avg 12.3  max 12.3  loss 0%" 37 wide, so full and chart
    # need 37 columns. Full needs 1 + 5 + 1 + 3 + 1 = 11 rows (16 in
    # ASCII), chart 1 + 2 + 1 = 4.
    STAT = "min 12.3  avg 12.3  max 12.3  loss 0%"

    def tier(self, cols, rows, caps=UNICODE, h=None):
        return lines_of(frame(history(12.3) if h is None else h, cols, rows, caps))

    def assert_full(self, lines):
        self.assertEqual(lines[0], "one.one.one.one (1.1.1.1)")
        self.assertEqual(lines[-1], self.STAT)
        self.assertIn("ms", lines)

    def test_full_at_its_exact_thresholds(self):
        self.assert_full(self.tier(37, 11))
        self.assertNotIn("ms", self.tier(37, 10))
        self.assertNotIn("ms", self.tier(36, 11))

    def test_ascii_full_needs_16_rows(self):
        self.assertIn("ms", self.tier(37, 16, ASCII))
        self.assertNotIn("ms", self.tier(37, 15, ASCII))

    def test_chart_is_header_sparkline_and_stat_line(self):
        rows = grid(frame(history(12.3), 37, 4))
        self.assertEqual(rows[0].strip(), "one.one.one.one (1.1.1.1)")
        # 12.3 ms of 20 ms is 9.8 of 16 levels.
        self.assertEqual([r[-1] for r in rows[1:3]], ["▂", "█"])
        self.assertEqual(rows[3].strip(), self.STAT)
        self.assertEqual(lines_of(frame(history(12.3), 37, 10))[0], "one.one.one.one (1.1.1.1)")

    def test_chart_at_its_exact_thresholds(self):
        self.assertEqual(len(self.tier(37, 4)), 4)
        self.assertEqual(self.tier(37, 3), ["12 ms" + " " * 31 + "▅"])
        self.assertEqual(self.tier(36, 10), ["12 ms" + " " * 30 + "▅"])

    def test_strip_is_the_value_then_a_one_row_sparkline(self):
        # 12.3 ms of 20 ms is 4.9 of 8 levels.
        self.assertEqual(self.tier(14, 1), ["12 ms        ▅"])

    def test_strip_needs_8_sparkline_columns(self):
        self.assertEqual(self.tier(14, 5), ["12 ms        ▅"])
        self.assertEqual(self.tier(13, 5), ["12 ms"])

    def test_strip_and_value_for_a_loss(self):
        self.assertEqual(self.tier(13, 1, PLAIN, history(ping.LOSS)), ["loss        ×"])
        self.assertEqual(self.tier(12, 1, PLAIN, history(ping.LOSS)), ["loss"])

    def test_value_then_blank(self):
        self.assertEqual(self.tier(5, 1), ["12 ms"])
        self.assertEqual(self.tier(4, 1), [])
        self.assertEqual(self.tier(4, 1, h=history(ping.LOSS)), ["loss"])
        self.assertEqual(self.tier(3, 1, h=history(ping.LOSS)), [])

    def test_strip_and_value_are_centered_on_the_middle_row(self):
        self.assertEqual(grid(frame(history(12.3), 9, 5))[2], "  12 ms  ")

    def test_value_takes_the_samples_color(self):
        rows = styled(frame(history(250.0), 9, 1))
        self.assertEqual({c for ch, c in rows[0] if ch != " "}, {196})

    def test_before_the_first_sample(self):
        self.assertEqual(self.tier(14, 1, h=history()), ["…"])
        self.assertEqual(lines_of(frame(history(), 40, 11))[0], "one.one.one.one (1.1.1.1)")

    def test_resolving_pane_shrinks_the_same_way(self):
        def resolving(cols, caps=UNICODE):
            return lines_of(frame(history(), cols, 3, caps, address=None))

        self.assertEqual(resolving(28), ["one.one.one.one · resolving…"])
        self.assertEqual(resolving(27), ["resolving…"])
        self.assertEqual(resolving(10), ["resolving…"])
        self.assertEqual(resolving(9), [])
        self.assertEqual(resolving(12, ASCII), ["resolving..."])

    def test_a_reason_too_wide_beside_the_host_shows_alone(self):
        # "one.one.one.one (1.1.1.1) · network unreachable" is 47 wide.
        lines = lines_of(frame(history(12.3, ping.LOSS), 46, 24, reason="network unreachable"))
        self.assertEqual(lines[0], "network unreachable")
        self.assertIn("min", lines[-1])
        lines = lines_of(frame(history(12.3, ping.LOSS), 47, 24, reason="network unreachable"))
        self.assertEqual(lines[0], "one.one.one.one (1.1.1.1) · network unreachable")

    def test_a_host_too_wide_for_the_pane_drops_the_layouts_that_show_it(self):
        lines = lines_of(frame(history(12.3), 40, 24, host="a-very-long-host-name.example.com"))
        self.assertEqual(len(lines), 1)

    def test_frames_never_clip(self):
        # Any header, stat or value text in a frame is whole: nothing is cut
        # at the pane's edge.
        h = history(0.4, 12.3, ping.LOSS, 250.0)
        header = "one.one.one.one (1.1.1.1) · host unreachable"
        for caps in (UNICODE, ASCII, PLAIN):
            for cols in range(0, 60, 3):
                for rows in range(0, 20, 2):
                    with self.subTest(caps=caps, cols=cols, rows=rows):
                        f = frame(h, cols, rows, caps, reason="host unreachable")
                        for line in lines_of(f):
                            if "one" in line or "unreach" in line:
                                full = header if caps.unicode else header.replace("·", "-")
                                self.assertIn(line, (full, "host unreachable"))
                            elif "avg" in line or line.startswith("min") or "%" in line:
                                self.assertRegex(line, r"^min \S+  avg \S+  max \S+  loss \d+%$")
                            elif "m" in line and line != "ms":
                                self.assertTrue(line.startswith("250 ms"), line)


class PlainLineTest(unittest.TestCase):
    def test_rtt_to_one_decimal_place_and_loss(self):
        self.assertEqual(ping.plain_line(12.34), "12.3 ms")
        self.assertEqual(ping.plain_line(0.4), "0.4 ms")
        self.assertEqual(ping.plain_line(ping.LOSS), "loss")


if __name__ == "__main__":
    unittest.main()
