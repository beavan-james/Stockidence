"""Compatibility shim: the service layer moved to stockidence.service.

The Reflex app and its tests keep importing from here during the React
migration; every name is the same module object as its canonical home, so
monkeypatching keeps working. This shim disappears with the Reflex cutover.
"""

from stockidence.service import demo  # noqa: F401
from stockidence.service import market  # noqa: F401
from stockidence.service import models  # noqa: F401
from stockidence.service import rating_service  # noqa: F401
from stockidence.service import sub_scores  # noqa: F401
from stockidence.service import warehouse  # noqa: F401
