import time
import numpy as np


class FrameParser:
    """Splits packets on header-to-next-header boundaries (rather than a
    fixed packet_len), so a packet that came in short -- a dropped byte, a
    device that occasionally sends fewer bytes than cols*rows -- doesn't
    permanently desync the framing while it waits for bytes that will
    never arrive. A short packet's missing payload bytes are zero-padded
    instead, so on_frame always gets a full (rows, cols) frame."""

    def __init__(self, cols, rows, header_bytes, pre_skip, post_skip, on_frame):
        self.cols = cols
        self.rows = rows
        self.header = bytes(header_bytes)
        self.pre_skip = pre_skip
        self.post_skip = post_skip
        self.on_frame = on_frame
        self.payload_len = cols * rows
        self._buf = bytearray()

    def feed(self, data: bytes):
        if not data:
            return
        self._buf.extend(data)
        self._parse()

    def _parse(self):
        hdr = self.header
        hdr_len = len(hdr)
        payload_start = hdr_len + self.pre_skip
        while True:
            idx = self._buf.find(hdr)
            if idx < 0:
                # keep last (hdr_len - 1) bytes in case header straddles boundary
                if len(self._buf) > hdr_len - 1:
                    del self._buf[: len(self._buf) - (hdr_len - 1)]
                return
            if idx > 0:
                del self._buf[:idx]
            # A packet's end is only known once the *next* header shows up
            # (packets aren't a fixed length any more); wait for it.
            next_idx = self._buf.find(hdr, hdr_len)
            if next_idx < 0:
                return
            payload = bytes(self._buf[payload_start:next_idx])
            if len(payload) < self.payload_len:
                payload = payload + b"\x00" * (self.payload_len - len(payload))
            else:
                payload = payload[: self.payload_len]
            frame = np.frombuffer(payload, dtype=np.uint8).reshape(self.rows, self.cols)
            ts = time.time()
            try:
                self.on_frame(ts, frame)
            except Exception:
                pass
            del self._buf[:next_idx]
