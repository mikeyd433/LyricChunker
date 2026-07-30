"""Fusion comp generation (spec addendum §6).

§7 findings so far, from the reference Salizar_Brenda comp (Resolve 21):
the production workflow is one Fusion comp per line, living on a
timeline clip with clip-local frames (0..N), media arriving as MediaIn
nodes from the Media Pool at 24fps. MediaIn nodes carry Media Pool IDs
that cannot be fabricated externally, so generation targets the §6.3
clipboard route with Loader nodes instead — still to verify: that
pasted Loaders render on the Fusion page of the target install. If not,
fallback is pasting the graph minus Loaders and hand-wiring MediaIns.

The animation pattern replicated by the generator (captured from the
reference comp's keyframes) lives in :mod:`settings_gen`.
"""

from .settings_gen import (
    DEFAULT_DIP_DEPTH,
    DEFAULT_DIP_IN,
    DEFAULT_DIP_OUT,
    DEFAULT_HIGHLIGHT_GAIN,
    generate_line_setting,
)
