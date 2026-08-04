"""Conversion helpers between the flat cell-index vectors the client sends
(risky_idx, pressure_mask_idx) and 2D (row, col) grid coordinates for the
dashboard.

Matches client/risk.py's convention: pressure_vector = frame.reshape(-1)
where frame = frame.reshape(rows, cols) (row-major), so a flat index i maps
to row = i // cols, col = i % cols.
"""


def idx_to_rowcol(idx_list, cols):
    if cols <= 0:
        raise ValueError(f"cols must be positive, got {cols}")
    return [[i // cols, i % cols] for i in idx_list]
