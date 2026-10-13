"""Import every model so metadata is complete (Alembic, tests)."""
from melorin.modules.catalog.models import *  # noqa: F401,F403
from melorin.modules.identity.models import *  # noqa: F401,F403
from melorin.modules.notifications.models import *  # noqa: F401,F403
from melorin.modules.orders.models import *  # noqa: F401,F403
from melorin.modules.payments.models import *  # noqa: F401,F403
from melorin.modules.referral.models import *  # noqa: F401,F403
from melorin.modules.stores.models import *  # noqa: F401,F403
from melorin.modules.system.models import *  # noqa: F401,F403
from melorin.modules.tickets.models import *  # noqa: F401,F403
from melorin.modules.vpn.models import *  # noqa: F401,F403
from melorin.modules.vpn.baskets import *  # noqa: F401,F403
from melorin.modules.wallet.models import *  # noqa: F401,F403
from melorin.modules.webhooks.models import *  # noqa: F401,F403
from melorin.core.db import Base  # noqa: F401
