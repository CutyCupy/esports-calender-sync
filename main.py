import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

import pytz
import requests
import yaml
from bs4 import BeautifulSoup
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    from backports.zoneinfo import ZoneInfo  # Python <3.9
    
import logging
import os
import shutil

def cleanup_logs(days=7):
    base_dir = "logs"
    now = datetime.now()

    if not os.path.exists(base_dir):
        return

    for folder in os.listdir(base_dir):
        folder_path = os.path.join(base_dir, folder)

        try:
            folder_date = datetime.strptime(folder, "%Y-%m-%d")
        except ValueError:
            continue

        if now - folder_date > timedelta(days=days):
            shutil.rmtree(folder_path)


def setup_run_logger():
    now = datetime.now()

    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M-%S")

    log_dir = os.path.join("logs", date_str)
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"run_{time_str}.log")

    logger = logging.getLogger(f"run_{time_str}")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        '%Y-%m-%d %H:%M:%S'
    )

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(formatter)

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger, log_file


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


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_config(cfg, path="config.yaml"):
    with open(path, "w") as f:
        yaml.dump(cfg, f, indent=2)


config = load_config()

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES,
)
CALENDAR_SERVICE = build("calendar", "v3", credentials=creds)
SHEETS_SERVICE = build("sheets", "v4", credentials=creds)


def make_uid(match):
    return match["id"]


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


def parse_team_page(url):
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
    for match in matches:
        logger.info(
            "Match %s | %s vs %s",
            match.get("id"),
            match.get("our_team"),
            match.get("opponent_team"),
        )
        try:
            add_match_to_casting_calendar(match)
            add_match_to_calendar(match)
        except Exception:
            logger.exception(
                "Fehler bei Match %s\n%s",
                match.get("id"),
                json.dumps(match, indent=2, default=str)
            )


def parse_primeleague(url):
    pattern = r"^https://www\.primeleague\.gg/.*/matches/(\d+)-"
    match = re.match(pattern, url)
    if not match:
        raise ValueError("URL ist keine gültige Primeleague-Matches-URL")

    match_id = int(match.group(1))
    api_url = f"https://api.heartbase.gg/league_match_get?match_id={match_id}"
    return fetch_primeleague_match(api_url)


def fetch_primeleague_match(api_url: str):
    headers = {
        "Authorization": f"Bearer {config['primeleague_token']}",
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

    if re.match(config["prefix"], short1):
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
        "our_team": re.sub(config["prefix"], "", our_team),
        "opponent_team": re.sub(config["prefix"], "", opponent_team),
        "id": re.search(r"matches/(\d+)", match_url).group(1),
        "match_url": match_url,
        "ts": datetime.fromtimestamp(
            start_time,
            tz=pytz.timezone(config["calendar"]["timezone"]),
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
            if re.match(config["prefix"], left_team_match["short"])
            else right_team_match
        )
        opponent_team_match = (
            right_team_match
            if re.match(config["prefix"], left_team_match["short"])
            else left_team_match
        )

        matches.append({
            "game": "RL",
            "our_team": re.sub(config["prefix"], "", our_team_match["name"]),
            "opponent_team": re.sub(config["prefix"], "", opponent_team_match["name"]),
            "id": match_id,
            "match_url": url,
            "ts": dt,
            "team": url,
        })

    return matches


def compare_scores(str1: str, str2: str) -> str:
    s1 = str1.strip().lower()
    s2 = str2.strip().lower()

    win_tokens = {"w", "win"}
    lose_tokens = {"l", "lose", "loss"}

    if s1 in win_tokens or s2 in lose_tokens:
        return "Win"
    if s2 in win_tokens or s1 in lose_tokens:
        return "Defeat"

    if s1.isdigit() and s2.isdigit():
        n1 = int(s1)
        n2 = int(s2)

        if n1 > n2:
            return "Win"
        if n1 < n2:
            return "Defeat"
        return "Draw"

    return "???"


def describe_match_result(our_score: str, opponent_score: str) -> str:
    return f"{our_score}-{opponent_score}"


def add_match_to_calendar(match):
    logger.info("Start das Match zum Google Kalender hinzuzufügen")
    summary = f"{match['game']}: {match['our_team']} vs {match['opponent_team']}"
    description = ""

    is_upcoming_match = match["ts"] + timedelta(hours=2) > datetime.now(TZ)

    if is_upcoming_match and (match.get("cast_1") or match.get("cast_2")):
        summary = f"[Cast] {summary}"

    if match.get("our_score") or match.get("opponent_score"):
        result = compare_scores(match.get("our_score"), match.get("opponent_score"))
        summary = f"[{result}] {summary}"
        description += describe_match_result(
            match.get("our_score"),
            match.get("opponent_score"),
        )
    
    event = {
        "summary": summary,
        "location": match["match_url"],
        "description": description,
        "start": {
            "dateTime": match["ts"].isoformat(),
            "timeZone": config["calendar"]["timezone"],
        },
        "end": {
            "dateTime": (match["ts"] + timedelta(hours=2)).isoformat(),
            "timeZone": config["calendar"]["timezone"],
        },
        "colorId": GAME_TO_COLOR[match["game"]],
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 60}],
        },
        "iCalUID": make_uid(match),
    }
    
    logger.info("Ermittlung ob bereits Kalendereinträge für das Match existieren.")
    existing = CALENDAR_SERVICE.events().list(
        calendarId=config["calendar"]["id"],
        iCalUID=event["iCalUID"],
        showDeleted=True,
    ).execute()
    
    existing_events = existing.get("items", [])
    
    
    if len(existing_events) > 0:
        logger.info("Es existieren Einträge für das Match - Starte Überprüfung, ob Updates nötig sind.")
        for existing_event in existing_events:
            event_id = existing_event["id"]
            
            identical = True
            for key in event.keys():
                identical = identical and event.get(key, "") == existing_event.get(key, "") 
            
            if identical:
                logger.info("Das vorhandene Event '%s' ist identisch zum aktuellen Stand des Events. Kein Update nötig.", event_id)    
                continue
            updated_event = CALENDAR_SERVICE.events().update(
                calendarId=config["calendar"]["id"],
                eventId=event_id,
                body=event,
            ).execute()
            logger.info("Das vorhandene Event '%s' wurde geupdated.", updated_event.get("htmlLink"))
    else:
        logger.info("Es existiert kein Eintrag für das Match.")
        new_event = CALENDAR_SERVICE.events().insert(
            calendarId=config["calendar"]["id"],
            body=event,
        ).execute()
        logger.info("Event '%s' wurde erstellt.", new_event.get('htmlLink'))

def get_row_data_for_match(match):
    date, weekday, time_value = format_date_fields(match["ts"])

    return [
        date,
        weekday,
        match["id"],
        time_value,
        match.get("game", ""),
        match.get("league", ""),
        match.get("match_url", ""),
        match.get("our_team", ""),
        match.get("cast_1") or "",
        match.get("cast_2") or "",
        match.get("cast_remark") or "",
        match.get("our_score") or "",
        match.get("opponent_score") or "",
    ]
    

casting_calendar_rows = None
date_map = None
id_map = None

def on_casting_calendar_row_change():
    global casting_calendar_rows
    global date_map
    global id_map
    
    casting_calendar_rows = None
    date_map = None
    id_map = None

def add_match_to_casting_calendar(match):
    global casting_calendar_rows
    global date_map
    global id_map

    logger.info("Start das Match zum Casting Kalender hinzuzufügen.")
    if is_relevant_match(match["ts"]):
        logger.info("Das Match liegt bereits in der Vergangenheit und wird nicht weiter im Casting Kalender berücksichtigt.")
        return

    event_date = match["ts"].date()
    ensure_date_range_for_day(event_date)

    if not casting_calendar_rows:
        casting_calendar_rows = load_rows_with_index()
    if not date_map or not id_map:
        date_map, id_map = analyze_sheet(casting_calendar_rows)

    row_data = get_row_data_for_match(match)

    if match["id"] in id_map:
        logger.info("Suche vorhandenen Eintrag im Casting Kalender")
        idx = id_map[match["id"]]
        for row_index, row in casting_calendar_rows:
            if row_index != idx:
                continue
            logger.info("Vorhandenen Eintrag im Casting Kalender gefunden.")
            match["cast_1"] = row[8] if len(row) > 8 else ""
            match["cast_2"] = row[9] if len(row) > 9 else ""
            match["cast_remark"] = row[10] if len(row) > 10 else ""
            match["our_score"] = (
                row[11]
                if not match.get("our_score") and len(row) > 11
                else match.get("our_score")
            )
            match["opponent_score"] = (
                row[12]
                if not match.get("opponent_score") and len(row) > 12
                else match.get("opponent_score")
            )

            if row == get_row_data_for_match(match):
                logger.info("Aktuelle Match-Informationen decken sich mit den Informationen im Casting Kalender.")
                return

            logger.info("Aktuelle Zeile des Matches im Casting Kalender wird für das Update entfernt.")
            SHEETS_SERVICE.spreadsheets().values().update(
                spreadsheetId=config["casting-sheet-id"],
                range=f"C{idx}:M{idx}",
                valueInputOption="USER_ENTERED",
                body={"values": [["", "", "", "", "", "", "", "", "", "", ""]]},
            ).execute()
            on_casting_calendar_row_change()
            return add_match_to_casting_calendar(match)

    date = row_data[0]

    for idx in date_map.get(parse_date(date), []):
        for row_index, row in casting_calendar_rows:
            if row_index == idx and (len(row) < 3 or row[2] == ""):
                logger.info("Eintrag wird im Casting Kalender hinzugefügt.")
                SHEETS_SERVICE.spreadsheets().values().update(
                    spreadsheetId=config["casting-sheet-id"],
                    range=f"A{idx}:M{idx}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [row_data]},
                ).execute()
                on_casting_calendar_row_change()
                return

    logger.info("Neue Zeile für Eintrag wird hinzugefügt.")
    insert_at = max(date_map[event_date]) + 1
    SHEETS_SERVICE.spreadsheets().batchUpdate(
        spreadsheetId=config["casting-sheet-id"],
        body={
            "requests": [{
                "insertDimension": {
                    "range": {
                        "sheetId": get_sheet_id(),
                        "dimension": "ROWS",
                        "startIndex": insert_at - 1,
                        "endIndex": insert_at,
                    },
                    "inheritFromBefore": True,
                }
            }]
        },
    ).execute()
    on_casting_calendar_row_change()
    
    logger.info("Eintrag wird im Casting Kalender hinzugefügt.")
    SHEETS_SERVICE.spreadsheets().values().append(
        spreadsheetId=config["casting-sheet-id"],
        range=f"A{insert_at}:M{insert_at}",
        valueInputOption="USER_ENTERED",
        insertDataOption="OVERWRITE",
        body={"values": [row_data]},
    ).execute()
    on_casting_calendar_row_change()


def weekday_short_de(date_obj):
    return GERMAN_WEEKDAYS[date_obj.weekday()]


def format_date_fields(dt: datetime):
    dt = dt.astimezone(TZ)
    return (
        dt.strftime("%d.%m.%Y"),
        weekday_short_de(dt),
        dt.strftime("%H:%M"),
    )


def load_sheet_rows():
    result = SHEETS_SERVICE.spreadsheets().values().get(
        spreadsheetId=config["casting-sheet-id"],
        range="A2:M",
    ).execute()
    return result.get("values", [])


def parse_date(value):
    return datetime.strptime(value, "%d.%m.%Y").date()


def load_rows_with_index():
    result = SHEETS_SERVICE.spreadsheets().values().get(
        spreadsheetId=config["casting-sheet-id"],
        range="A2:M",
    ).execute()

    values = result.get("values", [])

    return [
        (index, row + [""] * (13 - len(row)))
        for index, row in enumerate(values, start=2)
    ]


def analyze_sheet(rows):
    dates = {}
    ids = {}

    for idx, row in rows:
        if len(row) > 0 and row[0]:
            try:
                parsed_date = parse_date(row[0])
                dates.setdefault(parsed_date, []).append(idx)
            except ValueError:
                pass

        if len(row) > 2 and row[2]:
            ids[row[2]] = idx

    return dates, ids


def is_relevant_match(dt: datetime, now=None) -> bool:
    if now is None:
        now = datetime.now(TZ)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)

    return dt < now - timedelta(days=7)


def ensure_date_range_for_day(target_day):
    rows = load_sheet_rows()
    existing_dates = get_existing_dates(rows)

    if not existing_dates:
        SHEETS_SERVICE.spreadsheets().values().append(
            spreadsheetId=config["casting-sheet-id"],
            range="A:M",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [empty_day_row(target_day)]},
        ).execute()
        return

    min_date = existing_dates[0]
    max_date = existing_dates[-1]
    start = min(target_day, min_date)
    end = max(target_day, max_date)

    full_range = [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    ]
    missing_days = [day for day in full_range if day not in existing_dates]

    for day in missing_days:
        insert_at = len(rows) + 2
        for idx, row in enumerate(rows):
            if row and row[0]:
                try:
                    if parse_date(row[0]) > day:
                        insert_at = idx + 2
                        break
                except ValueError:
                    pass

        SHEETS_SERVICE.spreadsheets().batchUpdate(
            spreadsheetId=config["casting-sheet-id"],
            body={
                "requests": [{
                    "insertDimension": {
                        "range": {
                            "sheetId": get_sheet_id(),
                            "dimension": "ROWS",
                            "startIndex": insert_at - 1,
                            "endIndex": insert_at,
                        },
                        "inheritFromBefore": False,
                    }
                }]
            },
        ).execute()

        SHEETS_SERVICE.spreadsheets().values().update(
            spreadsheetId=config["casting-sheet-id"],
            range=f"A{insert_at}:M{insert_at}" if insert_at else "A:M",
            valueInputOption="USER_ENTERED",
            body={"values": [empty_day_row(day)]},
        ).execute()

        rows.insert(insert_at - 2 if insert_at else len(rows), empty_day_row(day))


def get_sheet_id(title="Tabellenblatt1"):
    meta = SHEETS_SERVICE.spreadsheets().get(
        spreadsheetId=config["casting-sheet-id"],
    ).execute()

    for sheet in meta["sheets"]:
        if sheet["properties"]["title"] == title:
            return sheet["properties"]["sheetId"]

    raise RuntimeError("Sheet not found")


def get_existing_dates(rows):
    dates = []
    for row in rows:
        if row and row[0]:
            try:
                dates.append(parse_date(row[0]))
            except ValueError:
                pass
    return sorted(set(dates))


def empty_day_row(day):
    return [
        day.strftime("%d.%m.%Y"),
        weekday_short_de(day),
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ]


URL_TO_INFORMATION = {
    "primeleague.gg": parse_primeleague,
    "docs.google.com": parse_google_docs,
    "velos.gg": parse_velos,
    "api.heartbase.gg": fetch_primeleague_match,
}


def get_parser(url):
    try:
        parsed = urlparse(url)
        for site, parser in URL_TO_INFORMATION.items():
            if parsed.netloc.endswith(site):
                return parser
        return None
    except Exception:
        return None


def main():
    global logger
    
    cleanup_logs(days=7)
    logger, logfile = setup_run_logger()

    start = time.time()
    
    logger.info("Start der Verarbeitung")
    for url in config["teams"]:
        logger.info("Start der Verarbeitung von '%s'", url)
        try:
            parse_team_page(url.strip())
        except Exception:
            logger.exception("Failed processing URL: %s", url, stack_info=True)
            continue

    logger.info("Verarbeitung nach %.2fs abgeschlossen.", time.time() - start)
    logger.info("Logfile: %s", logfile)


if __name__ == "__main__":
    main()