"""Fusion comp generation (spec addendum §6) — NOT YET IMPLEMENTED.

Gated on the §7 blocking research: Resolve's Fusion page and standalone
Fusion Studio handle media differently (MediaIn/MediaOut vs
Loader/Saver), and the comp target decision (A11) must come from
hands-on testing in Resolve, not documentation. Do not write generator
code here until that research lands.

When it does: the per-line JSON manifest is the complete input — one
media node per chunk pointing at its PNG, positioned at ``start_frame``,
hold-until-end-of-line visibility, a merge chain in chunk order, and
resolution/fps from the manifest's ``render`` block. Full-frame output
means no Transform nodes. Delivery is either a written ``.comp`` file or
comp text on the clipboard (§6.3) — evaluate both.
"""


def generate_comp(manifest_doc):
    raise NotImplementedError(
        "Comp generation is gated on the §7 comp-target research (A11)"
    )
