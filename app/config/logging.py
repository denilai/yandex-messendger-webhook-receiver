from __future__ import annotations

import logging.config
from pathlib import Path

import yaml

_DEFAULT_CONFIG = Path(__file__).with_name("logging.yaml")


def setup_logging(
    level: str = "INFO",
    fmt: str = "console",
    config_path: str | None = None,
) -> None:
    path = Path(config_path) if config_path else _DEFAULT_CONFIG

    with path.open() as f:
        cfg = yaml.safe_load(f)

    cfg["root"]["level"] = level.upper()

    handler_name = fmt if fmt in cfg.get("handlers", {}) else "console"
    cfg["root"]["handlers"] = [handler_name]

    logging.config.dictConfig(cfg)
