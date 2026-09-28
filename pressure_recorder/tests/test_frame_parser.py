import os
import sys

import numpy as np
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.frame_parser import FrameParser


def make_packet(header, pre, payload, post):
    return bytes(header) + bytes(pre) + bytes(payload) + bytes(post)


def test_single_clean_frame():
    # A packet's end is only known once the *next* header shows up (packets
    # aren't a fixed length any more -- see test_short_packet_is_zero_padded),
    # so a trailing header (starting a second, otherwise-irrelevant packet)
    # is needed to close out the frame under test.
    cols, rows = 4, 3
    header = bytes.fromhex("A55A")
    pre = 6
    post = 2
    payload = bytes(range(cols * rows))
    packet = make_packet(header, [0] * pre, payload, [0] * post)
    frames = []
    p = FrameParser(cols, rows, header, pre, post, lambda ts, f: frames.append(f))
    p.feed(packet + header)
    assert len(frames) == 1
    assert frames[0].shape == (rows, cols)
    assert np.array_equal(frames[0].flatten(), np.frombuffer(payload, dtype=np.uint8))


def test_noise_before_header():
    cols, rows = 2, 2
    header = bytes.fromhex("A55A")
    payload = bytes([1, 2, 3, 4])
    packet = make_packet(header, [9] * 6, payload, [0, 0])
    frames = []
    p = FrameParser(cols, rows, header, 6, 2, lambda ts, f: frames.append(f))
    p.feed(b"\x00\x01\xff" + packet + header)
    assert len(frames) == 1
    assert np.array_equal(frames[0].flatten(), np.array([1, 2, 3, 4], dtype=np.uint8))


def test_split_across_feeds():
    cols, rows = 2, 2
    header = bytes.fromhex("A55A")
    payload = bytes([10, 20, 30, 40])
    packet = make_packet(header, [0] * 6, payload, [0, 0])
    frames = []
    p = FrameParser(cols, rows, header, 6, 2, lambda ts, f: frames.append(f))
    p.feed(packet[:5])
    assert frames == []
    p.feed(packet[5:] + header)
    assert len(frames) == 1


def test_multiple_frames():
    cols, rows = 2, 1
    header = bytes.fromhex("A55A")
    p0 = make_packet(header, [0] * 6, bytes([1, 2]), [0, 0])
    p1 = make_packet(header, [0] * 6, bytes([3, 4]), [0, 0])
    frames = []
    p = FrameParser(cols, rows, header, 6, 2, lambda ts, f: frames.append(f))
    # p1 needs its own trailing header before it's considered complete.
    p.feed(p0 + p1 + header)
    assert len(frames) == 2
    assert frames[0][0, 0] == 1 and frames[1][0, 1] == 4


def test_header_straddles_boundary():
    cols, rows = 1, 1
    header = bytes.fromhex("A55A")
    payload = bytes([77])
    packet = make_packet(header, [0] * 6, payload, [0, 0])
    frames = []
    p = FrameParser(cols, rows, header, 6, 2, lambda ts, f: frames.append(f))
    p.feed(b"\xA5")
    p.feed(b"\x5A" + packet[2:] + header)
    assert len(frames) == 1
    assert frames[0][0, 0] == 77


def test_short_packet_is_zero_padded():
    """If the next header shows up before cols*rows payload bytes have
    arrived (a dropped byte, or a device that occasionally sends a
    shorter packet), the missing payload bytes are zero-padded instead of
    the parser stalling forever waiting for bytes that will never come."""
    cols, rows = 2, 2
    header = bytes.fromhex("A55A")
    pre = 6
    # Only 2 of the 4 expected payload bytes actually arrive before the
    # next header -- no post_skip either, it's just cut short.
    short_packet = header + bytes([0] * pre) + bytes([11, 22])
    frames = []
    p = FrameParser(cols, rows, header, pre, 2, lambda ts, f: frames.append(f))
    p.feed(short_packet + header)
    assert len(frames) == 1
    assert np.array_equal(frames[0].flatten(), np.array([11, 22, 0, 0], dtype=np.uint8))


def test_oversized_packet_is_truncated_to_payload_len():
    """The inverse of zero-padding: if somehow more bytes than expected sit
    between two headers (e.g. pre_skip/post_skip misconfigured for this
    device), the payload is truncated to cols*rows rather than reshape()
    raising on a mismatched size."""
    cols, rows = 1, 1
    header = bytes.fromhex("A55A")
    packet = header + bytes([0] * 6) + bytes([55]) + bytes([0] * 10)  # way over post_skip=2
    frames = []
    p = FrameParser(cols, rows, header, 6, 2, lambda ts, f: frames.append(f))
    p.feed(packet + header)
    assert len(frames) == 1
    assert frames[0][0, 0] == 55
