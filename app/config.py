import os

import yaml
from pydantic import BaseModel
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"


class CalendarConfig(BaseModel):
    id: str
    timezone: str

class CastingCalendarConfig(BaseModel):
    sheet_id: str

class Config(BaseModel):
    prefix: str
    primeleague_token: str
    
    calendar: CalendarConfig
    casting_calendar: CastingCalendarConfig
    teams: list[str]
    
    @classmethod
    def load(cls) -> "Config":
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(**data)

    def save(self):
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(
                self.model_dump(),
                f,
                indent=2,
                allow_unicode=True
            )