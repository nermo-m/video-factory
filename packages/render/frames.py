"""Which frame a moment falls on. One rule, used wherever seconds become frames."""

from __future__ import annotations


def frame_at(seconds: float, fps: int) -> int:
    """The frame nearest to a time.

    Times in a resolved spec are whole milliseconds, so the sum is done in whole numbers
    and the same moment always gives the same frame. A time exactly between two frames
    goes to the even one, as `round` does.

    With floating point, a scene's end (`start + duration`) and the next scene's start
    could land on different frames although they are the same moment, and the video then
    had one frame more or less than its length asks for.
    """
    whole, rest = divmod(round(seconds * 1000) * fps, 1000)
    if rest > 500 or (rest == 500 and whole % 2 == 1):
        whole += 1
    return whole
