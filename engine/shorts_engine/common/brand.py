"""Single source of truth for the product name.

The desktop side mirrors this in apps/desktop/src/shared/brand.ts. Keep both in sync;
scripts/gen-schemas refuses to run when they differ.
"""

PRODUCT_NAME = "Clipwright"
PROTOCOL_VERSION = 1
ENGINE_VERSION = "0.1.1"
