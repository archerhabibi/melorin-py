"""Import every model so metadata is complete (Alembic, tests). The tables live in :mod:`melorin.kernel.models`."""

from melorin.kernel.models.bundles import *  # noqa: F401,F403
from melorin.kernel.models.catalog import *  # noqa: F401,F403
from melorin.kernel.models.identity import *  # noqa: F401,F403
from melorin.kernel.models.notifications import *  # noqa: F401,F403
from melorin.kernel.models.orders import *  # noqa: F401,F403
from melorin.kernel.models.payments import *  # noqa: F401,F403
from melorin.kernel.models.referral import *  # noqa: F401,F403
from melorin.kernel.models.stores import *  # noqa: F401,F403
from melorin.kernel.models.system import *  # noqa: F401,F403
from melorin.kernel.models.tickets import *  # noqa: F401,F403
from melorin.kernel.models.vpn import *  # noqa: F401,F403
from melorin.kernel.models.wallet import *  # noqa: F401,F403
from melorin.kernel.models.webhooks import *  # noqa: F401,F403
from melorin.core.db import Base  # noqa: F401
