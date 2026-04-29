import time
import numpy as np


class FrameParser:
    def __init__(self, cols, rows, header_bytes, pre_skip, post_skip, on_frame):
        self.cols = cols
        self.rows = rows
        self.header = bytes(header_bytes)
        self.pre_skip = pre_skip
        self.post_skip = post_skip
        self.on_frame = on_frame
        self.payload_len = cols * rows
        self.packet_len = len(self.header) + pre_skip + self.payload_len + post_skip
        self._buf = bytearray()

    def feed(self, data: bytes):
        if not data:
            return
        self._buf.extend(data)
        self._parse()

    def _parse(self):
        hdr = self.header
        hdr_len = len(hdr)
        while True:
            idx = self._buf.find(hdr)
            if idx < 0:
                # keep last (hdr_len - 1) bytes in case header straddles boundary
                if len(self._buf) > hdr_len - 1:
                    del self._buf[: len(self._buf) - (hdr_len - 1)]
                return
            if idx > 0:
                del self._buf[:idx]
            if len(self._buf) < self.packet_len:
                return
            payload_start = hdr_len + self.pre_skip
            payload_end = payload_start + self.payload_len
            payload = bytes(self._buf[payload_start:payload_end])
            frame = np.frombuffer(payload, dtype=np.uint8).reshape(self.rows, self.cols)
            ts = time.time()
            try:
                self.on_frame(ts, frame)
            except Exception:
                pass
            del self._buf[: self.packet_len]
