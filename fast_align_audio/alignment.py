from typing import Optional

import numpy as np
import _fast_align_audio
from numpy._typing import NDArray


def fast_autocorr(original, delayed, t=1):
    """Only every 4th sample is considered in order to improve execution time"""
    if t == 0:
        return np.corrcoef([original[::4], delayed[::4]])[1, 0]
    elif t < 0:
        return np.corrcoef([original[-t::4], delayed[:t:4]])[1, 0]
    else:
        return np.corrcoef([original[:-t:4], delayed[t::4]])[1, 0]


def find_best_alignment_offset_with_corrcoef(
    original_signal,
    delayed_signal,
    min_offset_samples,
    max_offset_samples,
    lookahead_samples: Optional[int] = None,
):
    """Return the estimated delay (in samples) between the two sounds based on autocorrelation"""
    if lookahead_samples is not None and len(original_signal) > lookahead_samples:
        middle_of_signal_index = int(np.floor(len(original_signal) / 2))
        original_signal_slice = original_signal[
            middle_of_signal_index : middle_of_signal_index + lookahead_samples
        ]
        delayed_signal_slice = delayed_signal[
            middle_of_signal_index : middle_of_signal_index + lookahead_samples
        ]
    else:
        original_signal_slice = original_signal
        delayed_signal_slice = delayed_signal

    coefs = []
    for lag in range(min_offset_samples, max_offset_samples):
        correlation_coef = fast_autocorr(
            original_signal_slice, delayed_signal_slice, t=lag
        )
        coefs.append(correlation_coef)

    max_coef_index = int(np.argmax(coefs))
    offset = max_coef_index + min_offset_samples
    return offset


def find_best_alignment_offset(
    reference_signal: NDArray[np.float32],
    delayed_signal: NDArray[np.float32],
    max_offset_samples: int,
    lookahead_samples: Optional[int] = None,
    method: str = "mse",
):
    """
    Find best offset of `delayed_audio` w.r.t. `reference_audio`.

    Best = smallest mean squared error (mse).

    Args:
        reference_audio, delayed_audio (float32 C-contiguous NumPy arrays):
            The arrays to compare
        max_offset_samples (int > 0):
            Maximum expected offset. It will not find any larger offsets.
        lookahead_samples (int > 0, optional):
            Maximum number of array elements to use for each mse computation.
            If `None` (the default), there is no maximum.
        method: "mse" (fast) or "corr" (slow)
    """
    assert {reference_signal.dtype, delayed_signal.dtype} == {
        np.dtype("float32")
    }, "Arrays must be float32"

    if method == "mse":
        assert (
            reference_signal.flags["C_CONTIGUOUS"]
            and delayed_signal.flags["C_CONTIGUOUS"]
        ), "Arrays must be C-contiguous"
        if lookahead_samples is None:
            lookahead_samples = max(len(reference_signal), len(delayed_signal))
        return _fast_align_audio.lib.fast_find_alignment(
            len(delayed_signal),
            _fast_align_audio.ffi.cast("float *", delayed_signal.ctypes.data),
            len(reference_signal),
            _fast_align_audio.ffi.cast("float *", reference_signal.ctypes.data),
            max_offset_samples,
            lookahead_samples,
        )
    elif method == "corr":
        return find_best_alignment_offset_with_corrcoef(
            reference_signal, delayed_signal, -max_offset_samples, max_offset_samples
        )
    else:
        raise ValueError("Unknown method")


def align(a, b, max_offset, max_lookahead=None, *, align_mode, fix_length=None):
    """
    Align `a` and `b`. See the documentation of `find_best_alignment_offset` for most of the args.

    Args:
        align_mode (Either `"crop"` or `"pad"`): How to align `a` and `b`.
            If `crop`, "best_offset" number of elements are removed from the
            front of the "too-long" array. If `pad`, "best_offset" number of
            elements are padding to the front of the "too-short" array.
        fix_length (Either `"shortest"`, `"longest"` or `None`): How to fix the
            lengths of `a` and `b` after alignment. If `shortest`, the longer
            array is cropped (at the end/right) to the length of the shorter one.
            If `longest`, the shorter array is padded (to the end/right) to the
            length of the longest one.  If `None`, lengths are not changed.
    """
    offset = find_best_alignment_offset(a, b, max_offset, max_lookahead)
    if offset > 0:
        # mse(a[offset:], b) = min
        a, b = _align(a, b, offset, align_mode)
    else:
        # mse(a, b[offset:]) = min
        b, a = _align(b, a, -offset, align_mode)
    a, b = _fix(a, b, fix_length)
    return a, b


def _align(x, y, offset, align_mode):
    if align_mode == "crop":
        x = x[offset:]
    elif align_mode == "pad":
        y = np.pad(y, (offset, 0))
    return x, y


def _fix(x, y, fix_mode):
    if fix_mode is None:
        return x, y
    elif fix_mode == "shortest":
        min_len = min(len(x), len(y))
        x = x[:min_len]
        y = y[:min_len]
        return x, y
    elif fix_mode == "longest":
        max_len = max(len(x), len(y))
        x = np.pad(x, (0, max_len - len(x)))
        y = np.pad(y, (0, max_len - len(y)))
        return x, y
    else:
        raise ValueError(f"fix_length={fix_mode!r} not understood")
