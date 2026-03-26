from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class Game(Enum):
    LOL = "LoL"
    OW = "OW"
    RL = "RL"
    R6 = "R6"
    
    def get_google_color_id(self) -> str:
        match self:
            case Game.LOL: 
                return "5"
            case Game.RL: 
                return "1"
            case Game.OW: 
                return "6"
            case Game.R6: 
                return "4"
            case _:
                return ""
    
    
@dataclass
class CastInfo:
    casters: list[str]
    remark: str

@dataclass
class Match:
    game: Game
    our_team: str
    opponent_team: str
    id: str
    url: str
    ts: datetime
    our_score: str
    opponent_score: str
    cast_info: Optional[CastInfo]