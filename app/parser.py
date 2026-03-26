import re
from datetime import datetime
from typing import Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
import pytz
import requests
from bs4 import BeautifulSoup

from match import Match
from google.oauth2 import service_account


    
from logger import logger
from config import CONFIG


SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]
TZ = ZoneInfo("Europe/Berlin")
GERMAN_WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
GAME_TO_COLOR = {
    "LoL": "5",
    "RL": "1",
    "OW": "6",
    "R6": "4",
}

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES,
)
CALENDAR_SERVICE = build("calendar", "v3", credentials=creds)
SHEETS_SERVICE = build("sheets", "v4", credentials=creds)

def get_parser(url):
    try:
        parsed = urlparse(url)
        for site, parser in URL_TO_INFORMATION.items():
            if parsed.netloc.endswith(site):
                return parser
        return None
    except Exception:
        return None


def get_soup(url):
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


def parse_url(url) -> list[Match]:
    parser = get_parser(url)
    if parser is None:
        logger.error("Kein parser für URL '%s' gefunden.", url)
        return

    matches = parser(url)
    if len(matches) == 0:
        logger.error("Keine matches für URL '%s' gefunden.", url)
        return

    is_one_match = len(matches) == 1
    logger.info("Für die URL '%s' %s %d %s gefunden", url, "wurde" if is_one_match else "wurden", len(matches), "Match" if is_one_match else "Matches")
    return matches


def parse_primeleague(url: str) -> list[Match]:
    pattern = r"^https://www\.primeleague\.gg/.*/matches/(\d+)-"
    match = re.match(pattern, url)
    if not match:
        raise ValueError("URL ist keine gültige Primeleague-Matches-URL")

    match_id = int(match.group(1))
    api_url = f"https://api.heartbase.gg/league_match_get?match_id={match_id}"
    return fetch_primeleague_match(api_url)


def fetch_primeleague_match(api_url: str):
    headers = {
        "Authorization": f"Bearer {CONFIG['primeleague_token']}",
        "Accept": "application/json",
    }
    response = requests.get(api_url, headers=headers, timeout=15)
    response.raise_for_status()
    return parse_primeleague_match(response.json())


def parse_primeleague_match(data: dict):
    opp1 = data.get("opp_1", {}) if data.get("opp_1", {}) != [] else {}
    opp2 = data.get("opp_2", {}) if data.get("opp_2", {}) != [] else {}

    team1 = opp1.get("_team", {})
    team2 = opp2.get("_team", {})

    name1 = team1.get("team_name", "???")
    name2 = team2.get("team_name", "???")

    short1 = opp1.get("_short", "???")
    score1 = data.get("match_score_1", 0)
    score2 = data.get("match_score_2", 0)

    if re.match(CONFIG["prefix"], short1):
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
    start_time = data.get("match_time")

    return [{
        "game": "LoL",
        "our_team": re.sub(CONFIG["prefix"], "", our_team),
        "opponent_team": re.sub(CONFIG["prefix"], "", opponent_team),
        "id": re.search(r"matches/(\d+)", match_url).group(1),
        "match_url": match_url,
        "ts": datetime.fromtimestamp(
            start_time,
            tz=pytz.timezone(CONFIG["calendar"]["timezone"]),
        ),
        "match_id": data.get("_id"),
        "our_score": f"{our_score}" if data.get("match_status") != "upcoming" else "",
        "opponent_score": (
            f"{opponent_score}" if data.get("match_status") != "upcoming" else ""
        ),
    }]


def parse_google_docs(url):
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        return []

    spreadsheet_id = match.group(1)
    matches = []

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
                matches.append({
                    "game": title,
                    "our_team": row[0],
                    "opponent_team": row[1],
                    "id": row[4],
                    "match_url": row[4],
                    "ts": datetime.strptime(
                        f"{row[2]} {row[3]}",
                        "%d.%m.%Y %H:%M",
                    ).replace(tzinfo=TZ),
                    "team": url,
                })
            except Exception:
                continue

    return matches


def parse_velos(url):
    soup = get_soup(url)
    our_team_id = url.rstrip("/").split("/")[-1]
    season = soup.select_one("#radix-_r_1m_").get_text(strip=True)

    matches = []
    for item in soup.select(".space-y-4 .p-5"):
        time_el = item.select_one("div>div:last-child>span")
        if not time_el:
            continue

        dt = datetime.strptime(time_el.get_text(strip=True)[4:], "%d.%m.%y %H:%M")
        match_week = item.select_one("div>div>span")
        match_id = f"velos/{our_team_id}/{season}/{match_week}"

        left_team_match = re.match(
            r"^(?P<name>.+?)\s*(?P<short>\[[^\]]+\])$",
            item.select_one(".grid>div>div:last-child").get_text(strip=True),
        )
        right_team_match = re.match(
            r"^(?P<name>.+?)\s*(?P<short>\[[^\]]+\])$",
            item.select_one(".grid>div:last-child>div:last-child").get_text(strip=True),
        )

        our_team_match = (
            left_team_match
            if re.match(CONFIG["prefix"], left_team_match["short"])
            else right_team_match
        )
        opponent_team_match = (
            right_team_match
            if re.match(CONFIG["prefix"], left_team_match["short"])
            else left_team_match
        )

        matches.append({
            "game": "RL",
            "our_team": re.sub(CONFIG["prefix"], "", our_team_match["name"]),
            "opponent_team": re.sub(CONFIG["prefix"], "", opponent_team_match["name"]),
            "id": match_id,
            "match_url": url,
            "ts": dt,
            "team": url,
        })

    return matches



Parser = Callable[[str], list[Match]]

# TODO: Irgendwann vlt mal durch eigene Parser Klassen ablösen
URL_TO_INFORMATION: dict[str, Parser] = {
    "primeleague.gg": parse_primeleague,
    "docs.google.com": parse_google_docs,
    "velos.gg": parse_velos,
    "api.heartbase.gg": fetch_primeleague_match,
}