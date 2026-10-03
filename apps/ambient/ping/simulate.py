#!/usr/bin/env python3
"""Run ping.py's pane with a fake prober that sweeps the Ramp.

Run: python3 apps/ambient/ping/simulate.py [--prefill N]
See the README's Simulating section.
"""

import argparse
import itertools
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ping  # noqa: E402

UNREACHABLE = "network unreachable"

# One pass of fake Samples: up through every Ramp step and back down, three
# Samples each, then a burst of plain Losses, then a burst of send errors.
SWEEP = (10.0, 35.0, 55.0, 70.0, 90.0, 110.0, 140.0, 180.0, 260.0)
SCRIPT = (
    [rtt for rtt in SWEEP + SWEEP[-2::-1] for _ in range(3)]
    + [ping.LOSS] * 4
    + [20.0] * 3
    + [UNREACHABLE] * 4
    + [15.0] * 3
)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Run the ping pane with a fake prober that sweeps the Ramp and adds bursts of Loss.",
    )
    parser.add_argument(
        "--prefill",
        type=int,
        default=2 * len(SCRIPT),
        help="fake Samples already in the History at startup (default: %(default)s)",
    )
    return parser.parse_args(argv)


class FakeProber:
    """A stand-in for ping.Prober that answers each Probe from SCRIPT, at
    once. A scripted Loss gets no reply, so it lands when the Probe times
    out, and UNREACHABLE fails the send."""

    def __init__(self, sock, address):
        self.samples = itertools.cycle(SCRIPT)
        self.replies, self.inbox = socket.socketpair()
        self.current = None

    def fileno(self):
        return self.inbox.fileno()

    def send(self, seq):
        self.current = next(self.samples)
        if self.current == UNREACHABLE:
            return ping.Outcome(ping.LOSS, UNREACHABLE)
        if self.current is not ping.LOSS:
            self.replies.send(b".")
        return None

    def receive(self, seq):
        self.inbox.recv(1)
        return ping.Outcome(self.current, None)


def prefilled_history(count):
    """A ping.History class whose instances start with count scripted
    Samples."""

    class PrefilledHistory(ping.History):
        def __init__(self, capacity=ping.HISTORY_CAPACITY):
            super().__init__(capacity)
            for sample in itertools.islice(itertools.cycle(SCRIPT), count):
                self.add(ping.LOSS if sample == UNREACHABLE else sample)

    return PrefilledHistory


def main():
    opts = parse_args(sys.argv[1:])
    ping.open_icmp = lambda: None
    ping.resolve = lambda host: "192.0.2.1"
    ping.Prober = FakeProber
    ping.History = prefilled_history(opts.prefill)
    sys.argv = [sys.argv[0], "simulated"]
    ping.main()


if __name__ == "__main__":
    main()
