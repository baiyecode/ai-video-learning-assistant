"""Imports every module's models so ``Base.metadata`` is complete before ``create_all``.

New modules must add their ``models`` import here (one line), never touch ``db.py``.
"""

from __future__ import annotations

from .modules.analysis import models as _analysis_models  # noqa: F401
from .modules.billing import models as _billing_models  # noqa: F401
from .modules.catalog import models as _catalog_models  # noqa: F401
from .modules.identity import models as _identity_models  # noqa: F401
from .modules.media import models as _media_models  # noqa: F401
from .modules.ops import models as _ops_models  # noqa: F401
