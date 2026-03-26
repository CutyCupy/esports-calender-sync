import os
import re
from datetime import datetime
from typing import Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
import pytz
import requests
from bs4 import BeautifulSoup

from context import Context
from config import Config # type: ignore
from match import Game, Match
from google.oauth2 import service_account


from pathlib import Path

Parser = Callable[[Context, str], list[Match]]



SERVICE_ACCOUNT_FILE = Path(__file__).parent.parent / "config" / "service_account.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]
TZ = ZoneInfo("Europe/Berlin")
GERMAN_WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

creds = service_account.Credentials.from_service_account_file( # type: ignore
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES,
)
CALENDAR_SERVICE = build("calendar", "v3", credentials=creds) # type: ignore
SHEETS_SERVICE = build("sheets", "v4", credentials=creds) # type: ignore

def get_parser(url: str) -> Parser | None:
    try:
        parsed = urlparse(url)
        for site, parser in URL_TO_INFORMATION.items():
            if parsed.netloc.endswith(site):
                return parser
        return None
    except Exception:
        return None


def get_soup(url: str) -> BeautifulSoup:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/118.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Referer": "https://www.primeleague.gg/",
        "Connection": "keep-alive",
        "DNT": "1",
    }
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def parse_url(ctx: Context, url: str) -> list[Match]:
    parser = get_parser(url)
    if parser is None:
        ctx.logger.error("Kein parser für URL '%s' gefunden.", url)
        return []

    matches = parser(ctx, url)
    if len(matches) == 0:
        ctx.logger.error("Keine matches für URL '%s' gefunden.", url)
        return []

    is_one_match = len(matches) == 1
    ctx.logger.info("Für die URL '%s' %s %d %s gefunden", url, "wurde" if is_one_match else "wurden", len(matches), "Match" if is_one_match else "Matches")
    return matches


def parse_primeleague(ctx: Context, url: str) -> list[Match]:
    pattern = r"^https://www\.primeleague\.gg/.*/matches/(\d+)-"
    match = re.match(pattern, url)
    if not match:
        raise ValueError("URL ist keine gültige Primeleague-Matches-URL")

    match_id = int(match.group(1))
    api_url = f"https://api.heartbase.gg/league_match_get?match_id={match_id}"
    return fetch_primeleague_match(ctx, api_url)


def fetch_primeleague_match(ctx: Context, api_url: str) -> list[Match]: 
    cfg = Config.load()
    headers = {
        "Authorization": f"Bearer {cfg.primeleague_token}",
        "Accept": "application/json",
    }
    response = requests.get(api_url, headers=headers, timeout=15)
    response.raise_for_status()
    return parse_primeleague_match(ctx, response.json())


def parse_primeleague_match(ctx: Context, data: dict[str]) -> list[Match]: # type: ignore
    opp1 = data.get("opp_1", {}) if data.get("opp_1", {}) != [] else {} # type: ignore
    opp2 = data.get("opp_2", {}) if data.get("opp_2", {}) != [] else {} # type: ignore

    team1 = opp1.get("_team", {})
    team2 = opp2.get("_team", {})

    name1 = team1.get("team_name", "???")
    name2 = team2.get("team_name", "???")

    short1 = opp1.get("_short", "???")
    score1 = data.get("match_score_1", 0)
    score2 = data.get("match_score_2", 0)
    
    cfg = Config.load()

    if re.match(cfg.prefix, short1):
        our_team = name1
        opponent_team = name2
        our_score = score1
        opponent_score = score2
    else:
        our_team = name2
        opponent_team = name1
        our_score = score2
        opponent_score = score1

    match_url = f"https://www.primeleague.gg/en/{data.get('_url')}"
    start_time = data.get("match_time", "")

    return [
        Match(
            game=Game.LOL,
            our_team= re.sub(cfg.prefix, "", our_team),
            opponent_team= re.sub(cfg.prefix, "", opponent_team),
            id= str(data.get("_id", "")),
            url= match_url,
            ts= datetime.fromtimestamp(
                start_time,
                tz=pytz.timezone(cfg.calendar.timezone),
            ),
            our_score= f"{our_score}" if data.get("match_status") != "upcoming" else "",
            opponent_score= (
                f"{opponent_score}" if data.get("match_status") != "upcoming" else ""
            ),
            cast_info=None
        )
    ]

def parse_google_docs(ctx: Context, url: str) -> list[Match]:
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        return []

    spreadsheet_id = match.group(1)
    matches: list[Match] = []

    spreadsheet = SHEETS_SERVICE.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
    ).execute()

    for sheet in spreadsheet.get("sheets", []):
        title = sheet["properties"]["title"]
        result = SHEETS_SERVICE.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{title}'",
        ).execute()

        for row in result.get("values", [])[1:]:
            try:
                matches.append(
                    Match(
                        cast_info=None,
                        game=Game[title],
                        our_team= row[0],
                        opponent_team= row[1],
                        id= row[4],
                        url= row[4],
                        ts= datetime.strptime(
                            f"{row[2]} {row[3]}",
                            "%d.%m.%Y %H:%M",
                        ).replace(tzinfo=TZ),
                        opponent_score="",
                        our_score=""
                    )
                )
            except Exception:
                continue

    return matches

_: Parser = parse_google_docs
_: Parser = parse_primeleague
_: Parser = fetch_primeleague_match

# TODO: Irgendwann vlt mal durch eigene Parser Klassen ablösen
URL_TO_INFORMATION: dict[str, Parser] = {
    "primeleague.gg": parse_primeleague,
    "docs.google.com": parse_google_docs,
    "api.heartbase.gg": fetch_primeleague_match,
}