"""Prints the raw bytes coming off a serial port, unparsed -- for checking
that the sensor is actually sending something before reaching for
cmd/start.py's frame parsing.

Usage:
    python cmd/serial_recorder.py [--port /dev/ttyUSB0] [--baud 921600]
                                   [--hex]
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


def build_parser():
    p = argparse.ArgumentParser(prog="serial_recorder", description="Print raw serial bytes")
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument("--hex", action="store_true",
                    help="print as hex bytes instead of raw repr")
    return p


def main():
    args = build_parser().parse_args()
    print(f"[serial_recorder] port={args.port} baud={args.baud} (Ctrl+C to stop)")

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
                ts = time.strftime("%H:%M:%S")
                if args.hex:
                    print(f"[{ts}] {data.hex(' ')}")
                else:
                    print(f"[{ts}] {data!r}")
        except KeyboardInterrupt:
            print("\n[serial_recorder] stopped")
            return
        except Exception as e:
            print(f"[serial_recorder] disconnected: {e}. Reconnecting...")
        finally:
            try:
                ser.close()
            except Exception:
                pass
        time.sleep(RECONNECT_DELAY_S)


if __name__ == "__main__":
    main()
