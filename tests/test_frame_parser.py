import numpy as np
import pytest

from sensor.frame_parser import FrameParser


def make_packet(header, pre, payload, post):
    return bytes(header) + bytes(pre) + bytes(payload) + bytes(post)


def test_single_clean_frame():
    cols, rows = 4, 3
    header = bytes.fromhex("A55A")
    pre = 6
    post = 2
    payload = bytes(range(cols * rows))
    packet = make_packet(header, [0] * pre, payload, [0] * post)
    frames = []
    p = FrameParser(cols, rows, header, pre, post, lambda ts, f: frames.append(f))
    p.feed(packet)
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
    p.feed(b"\x00\x01\xff" + packet)
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
    p.feed(packet[5:])
    assert len(frames) == 1


def test_multiple_frames():
    cols, rows = 2, 1
    header = bytes.fromhex("A55A")
    p0 = make_packet(header, [0] * 6, bytes([1, 2]), [0, 0])
    p1 = make_packet(header, [0] * 6, bytes([3, 4]), [0, 0])
    frames = []
    p = FrameParser(cols, rows, header, 6, 2, lambda ts, f: frames.append(f))
    p.feed(p0 + p1)
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
    p.feed(b"\x5A" + packet[2:])
    assert len(frames) == 1
    assert frames[0][0, 0] == 77
