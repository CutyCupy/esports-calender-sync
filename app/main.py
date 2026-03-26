import json
import time
from datetime import datetime, timedelta

from googleapiclient.discovery import build

from logger import cleanup_logs
from parser import CALENDAR_SERVICE, GAME_TO_COLOR, GERMAN_WEEKDAYS, SHEETS_SERVICE, TZ, parse_url
from config import CONFIG

from logger import logger, log_file


from zoneinfo import ZoneInfo  # Python 3.9+
    




def make_uid(match):
    return match["id"]

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
            "timeZone": CONFIG["calendar"]["timezone"],
        },
        "end": {
            "dateTime": (match["ts"] + timedelta(hours=2)).isoformat(),
            "timeZone": CONFIG["calendar"]["timezone"],
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
        calendarId=CONFIG["calendar"]["id"],
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
                calendarId=CONFIG["calendar"]["id"],
                eventId=event_id,
                body=event,
            ).execute()
            logger.info("Das vorhandene Event '%s' wurde geupdated.", updated_event.get("htmlLink"))
    else:
        logger.info("Es existiert kein Eintrag für das Match.")
        new_event = CALENDAR_SERVICE.events().insert(
            calendarId=CONFIG["calendar"]["id"],
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
                spreadsheetId=CONFIG["casting-sheet-id"],
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
                    spreadsheetId=CONFIG["casting-sheet-id"],
                    range=f"A{idx}:M{idx}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [row_data]},
                ).execute()
                on_casting_calendar_row_change()
                return

    logger.info("Neue Zeile für Eintrag wird hinzugefügt.")
    insert_at = max(date_map[event_date]) + 1
    SHEETS_SERVICE.spreadsheets().batchUpdate(
        spreadsheetId=CONFIG["casting-sheet-id"],
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
        spreadsheetId=CONFIG["casting-sheet-id"],
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
        spreadsheetId=CONFIG["casting-sheet-id"],
        range="A2:M",
    ).execute()
    return result.get("values", [])


def parse_date(value):
    return datetime.strptime(value, "%d.%m.%Y").date()


def load_rows_with_index():
    result = SHEETS_SERVICE.spreadsheets().values().get(
        spreadsheetId=CONFIG["casting-sheet-id"],
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
            spreadsheetId=CONFIG["casting-sheet-id"],
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
            spreadsheetId=CONFIG["casting-sheet-id"],
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
            spreadsheetId=CONFIG["casting-sheet-id"],
            range=f"A{insert_at}:M{insert_at}" if insert_at else "A:M",
            valueInputOption="USER_ENTERED",
            body={"values": [empty_day_row(day)]},
        ).execute()

        rows.insert(insert_at - 2 if insert_at else len(rows), empty_day_row(day))


def get_sheet_id(title="Tabellenblatt1"):
    meta = SHEETS_SERVICE.spreadsheets().get(
        spreadsheetId=CONFIG["casting-sheet-id"],
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




def main():
    cleanup_logs(days=7)
    start = time.time()
    
    logger.info("Start der Verarbeitung")
    for url in CONFIG["teams"]:
        logger.info("Start der Verarbeitung von '%s'", url)
        try:
            matches = parse_url(url.strip())
        except Exception:
            logger.exception("Failed processing URL: %s", url, stack_info=True)
            continue

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
    logger.info("Verarbeitung nach %.2fs abgeschlossen.", time.time() - start)
    logger.info("Logfile: %s", log_file)


if __name__ == "__main__":
    main()