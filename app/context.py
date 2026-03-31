from dataclasses import dataclass
from logging import Logger

from config import Config # type: ignore


@dataclass
class Context:
    logger: Logger
    config: Config