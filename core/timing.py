"""Frame and time conversion (spec section 4).

.rbj is frame-based, never time-based. Frame numbers are integers in the source
application's own numbering. This module exists because one of the two hosts is
not: After Effects addresses keyframes and comp time in seconds, so every read
and write on that side crosses this boundary.

Pure functions, no host calls and no I/O.
"""

import math


def frame_to_seconds(frame, fps, start_frame=0):
    """Frame number to host time in seconds.

    `start_frame` is the frame number that sits at time zero - After Effects'
    `comp.displayStartTime` expressed as a frame. Nuke callers do not need this
    function at all.
    """
    return (float(frame) - float(start_frame)) / float(fps)


def seconds_to_frame(seconds, fps, start_frame=0):
    """Host time in seconds to the nearest frame number.

    Rounds half up, and never truncates. Host-reported key times are floating
    point and land just under the exact value - After Effects reported
    8.333333 s for frame 200 at 24 fps, which truncation turns into frame 199.
    Python's built-in `round` is not used because it rounds half to even, so a
    key at exactly x.5 frames would snap in a direction that depends on the
    parity of the frame number.
    """
    exact = float(seconds) * float(fps) + float(start_frame)
    return int(math.floor(exact + 0.5))


def snap_frame(value):
    """A host key time already in frames to the integer frame it belongs to.

    Nuke reports key times as floats and permits them off the integer grid,
    while spec section 9 requires every `keys[].frame` to be an integer that
    exists in `frames`. Same rounding rule as `seconds_to_frame`, and separate
    from it because the Nuke side never crosses seconds at all.
    """
    return int(math.floor(float(value) + 0.5))


def subframe_residual(seconds, fps, start_frame=0):
    """How far, in frames, `seconds` sits from the frame it snaps to.

    Signed, in the range [-0.5, 0.5). After Effects permits keyframes at
    non-frame times; spec section 9 requires every `keys[].frame` to exist in
    `frames`, so such a key must be snapped and warned about. This is the number
    that decides whether a warning is warranted and what it says.
    """
    exact = float(seconds) * float(fps) + float(start_frame)
    return exact - seconds_to_frame(seconds, fps, start_frame)


def frame_range(first, last):
    """The inclusive frame list a dense layer must cover (spec section 7.1)."""
    if first > last:
        raise ValueError("range is not ascending: [%d, %d]" % (first, last))
    return list(range(int(first), int(last) + 1))


def offset_to_start(src_first, dst_first):
    """The offset an importer adds to every source frame to land on `dst_first`.

    Direction is the easy thing to get backwards: the result is added to source
    frames, so `src_first + offset_to_start(src_first, dst_first) == dst_first`.
    """
    return int(dst_first) - int(src_first)
