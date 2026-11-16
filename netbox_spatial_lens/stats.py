"""
The figures in the strip above a drawing.
"""

from dataclasses import dataclass

__all__ = ('Stat',)


@dataclass
class Stat:
    """
    One figure in the strip above a drawing.

    `value` is the number somebody reads at a glance and `detail` is what makes it mean
    something: "38%" alone is not an answer, "38% full" and "772U free of 1 248" is. `tone`
    names a palette band where the figure carries one, so a floor near its limit is red in the
    strip as well as on the plan.
    """

    label: str
    value: str
    detail: str = ''
    tone: str = ''
