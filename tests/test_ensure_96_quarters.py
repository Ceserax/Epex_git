import numpy as np

from run_daily import ensure_96_quarters


def test_returns_same_for_96_points():
    data = np.arange(96, dtype=float)
    out = ensure_96_quarters(data)
    assert np.array_equal(out, data)


def test_24_hours_expands_to_96_quarters():
    data = np.arange(24, dtype=float)
    out = ensure_96_quarters(data)
    assert len(out) == 96
    assert np.array_equal(out[:4], np.array([0.0, 0.0, 0.0, 0.0]))
    assert np.array_equal(out[-4:], np.array([23.0, 23.0, 23.0, 23.0]))


def test_48_halfhours_expands_to_96_quarters():
    data = np.arange(48, dtype=float)
    out = ensure_96_quarters(data)
    assert len(out) == 96
    assert np.array_equal(out[:2], np.array([0.0, 0.0]))
    assert np.array_equal(out[-2:], np.array([47.0, 47.0]))


def test_nonstandard_length_interpolation_stays_in_range_and_preserves_edges():
    data = np.arange(25, dtype=float)
    out = ensure_96_quarters(data)

    assert len(out) == 96
    assert out[0] == data[0]
    assert out[-1] == data[-1]
    assert out.min() >= data.min()
    assert out.max() <= data.max()


def test_empty_input_returns_empty_array():
    data = np.array([], dtype=float)
    out = ensure_96_quarters(data)
    assert out.size == 0
