"""Prints the raw bytes coming off a serial port, unparsed -- for checking
that the sensor is actually sending something before reaching for
cmd/start.py's frame parsing. Bytes are split into packets on the header
marker (default A5 5A, matching cmd/start.py's --header), so each printed
line is one packet rather than an arbitrary read-sized chunk.

Usage:
    python cmd/serial_recorder.py [--port /dev/ttyUSB0] [--baud 921600]
                                   [--header A55A] [--hex]
"""
import argparse
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import serial

RECONNECT_DELAY_S = 1.0
READ_CHUNK = 4096
READ_TIMEOUT_S = 0.1


class HeaderSplitter:
    """Buffers incoming bytes and yields one packet per call to feed() for
    every *complete* header-to-next-header span found so far (the last,
    still-incomplete tail is held back until more data arrives or the
    stream stops)."""

    def __init__(self, header: bytes):
        self.header = header
        self._buf = bytearray()

    def feed(self, data: bytes):
        self._buf.extend(data)
        packets = []
        while True:
            start = self._buf.find(self.header)
            if start < 0:
                self._buf.clear()
                break
            next_start = self._buf.find(self.header, start + len(self.header))
            if next_start < 0:
                if start > 0:
                    del self._buf[:start]
                break
            packets.append(bytes(self._buf[start:next_start]))
            del self._buf[:next_start]
        return packets

    def flush(self):
        """Call on disconnect: whatever's left in the buffer is one final
        (possibly truncated) packet, if it starts with the header."""
        if self._buf.startswith(self.header):
            packet = bytes(self._buf)
            self._buf.clear()
            return [packet]
        self._buf.clear()
        return []


def build_parser():
    p = argparse.ArgumentParser(prog="serial_recorder", description="Print raw serial packets")
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument("--header", default="A55A", help="hex string, e.g. A55A")
    p.add_argument("--hex", action="store_true",
                    help="print as hex bytes instead of raw repr")
    return p


def _print_packet(packet: bytes, as_hex: bool):
    ts = time.strftime("%H:%M:%S")
    if as_hex:
        print(f"[{ts}] ({len(packet)}B) {packet.hex(' ')}")
    else:
        print(f"[{ts}] ({len(packet)}B) {packet!r}")


def main():
    args = build_parser().parse_args()
    header = bytes.fromhex(args.header.strip().replace(" ", ""))
    splitter = HeaderSplitter(header)
    print(f"[serial_recorder] port={args.port} baud={args.baud} header={header.hex(' ')} (Ctrl+C to stop)")

    while True:
        try:
            ser = serial.Serial(args.port, args.baud, timeout=READ_TIMEOUT_S)
        except Exception as e:
            print(f"[serial_recorder] connect failed: {e}. Retrying...")
            time.sleep(RECONNECT_DELAY_S)
            continue

        print(f"[serial_recorder] connected to {args.port}")
        try:
            while True:
                data = ser.read(READ_CHUNK)
                if not data:
                    continue
                for packet in splitter.feed(data):
                    _print_packet(packet, args.hex)
        except KeyboardInterrupt:
            for packet in splitter.flush():
                _print_packet(packet, args.hex)
            print("\n[serial_recorder] stopped")
            return
        except Exception as e:
            for packet in splitter.flush():
                _print_packet(packet, args.hex)
            print(f"[serial_recorder] disconnected: {e}. Reconnecting...")
        finally:
            try:
                ser.close()
            except Exception:
                pass
        time.sleep(RECONNECT_DELAY_S)


if __name__ == "__main__":
    main()
