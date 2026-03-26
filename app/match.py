from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class Game(Enum):
    LOL = "LoL"
    RL = "RL"
    R6 = "R6"


@dataclass
class Match:
    game: Game
    our_team: str
    opponent_team: str
    id: str
    match_url: str
    ts: datetime
    match_id: Optional[str]
    our_score: str
    opponent_score: str