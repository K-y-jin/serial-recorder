import pytest

from server.grid import idx_to_rowcol


def test_basic_conversion():
    assert idx_to_rowcol([0, 1, 31, 32, 33], cols=32) == [
        [0, 0], [0, 1], [0, 31], [1, 0], [1, 1],
    ]


def test_empty_list():
    assert idx_to_rowcol([], cols=32) == []


def test_cols_one_boundary():
    assert idx_to_rowcol([0, 1, 2], cols=1) == [[0, 0], [1, 0], [2, 0]]


def test_rejects_non_positive_cols():
    with pytest.raises(ValueError):
        idx_to_rowcol([0, 1], cols=0)
