# Order matters: the Pending SQL view reads the Phase 1 Project table, so that
# table has to exist before the view is created on install.
from . import quota_config
from . import project_mixin
from . import phase1_project
from . import unidentified
from . import phase1_pending
from . import sale_order
