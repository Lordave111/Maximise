"""Safe Render entrypoint for Merco.

The legacy app module references @login_required during import but its import
list omitted the decorator. Seed the symbol before loading merco_runtime so
both the legacy runtime and the production fixes can initialize normally.
"""

import builtins
from flask_login import login_required

builtins.login_required = login_required

from merco_runtime import app  # noqa: E402

application = app
