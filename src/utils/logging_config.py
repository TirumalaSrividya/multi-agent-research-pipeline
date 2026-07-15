"""Central logging setup. INFO shows lifecycle events; DEBUG shows every
message published/consumed on the bus and per-agent internals."""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    fmt = "%(asctime)s.%(msecs)03dZ %(levelname)-7s %(name)-16s %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # keep noisy third-party libs quieter unless we're in DEBUG globally
    if level.upper() != "DEBUG":
        logging.getLogger("asyncio").setLevel(logging.WARNING)
    _CONFIGURED = True
