from datetime import datetime, timedelta


from context import Context
from parser import CALENDAR_SERVICE, TZ

from match import Match

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


def add_match_to_google_calendar(ctx: Context, match: Match):
    ctx.logger.info("Start das Match zum Google Kalender hinzuzufügen")
    summary = f"{match.game.value}: {match.our_team} vs {match.opponent_team}"
    description = ""

    is_upcoming_match = match.ts + timedelta(hours=2) > datetime.now(TZ)

    if is_upcoming_match and match.cast_info and len(match.cast_info.casters) > 0:
        summary = f"[Cast] {summary}"

    if match.our_score or match.opponent_score:
        result = compare_scores(match.our_score, match.opponent_score)
        summary = f"[{result}] {summary}"
        description += describe_match_result(
            match.our_score,
            match.opponent_score,
        )
    
    event = {
        "summary": summary,
        "location": match.url,
        "description": description,
        "start": {
            "dateTime": match.ts.isoformat(),
            "timeZone": ctx.config.calendar.timezone,
        },
        "end": {
            "dateTime": (match.ts + timedelta(hours=2)).isoformat(),
            "timeZone": ctx.config.calendar.timezone,
        },
        "colorId": match.game.get_google_color_id(),
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 60}],
        },
        "iCalUID": match.id,
    }
    
    ctx.logger.info("Ermittlung ob bereits Kalendereinträge für das Match existieren.")
    existing = CALENDAR_SERVICE.events().list(
        calendarId=ctx.config.calendar.id,
        iCalUID=event["iCalUID"],
        showDeleted=True,
    ).execute()
    
    existing_events = existing.get("items", [])
    
    
    if len(existing_events) > 0:
        ctx.logger.info("Es existieren Einträge für das Match - Starte Überprüfung, ob Updates nötig sind.")
        for existing_event in existing_events:
            event_id = existing_event["id"]
            
            identical = True
            for key in event.keys():
                identical = identical and event.get(key, "") == existing_event.get(key, "") 
            
            if identical:
                ctx.logger.info("Das vorhandene Event '%s' ist identisch zum aktuellen Stand des Events. Kein Update nötig.", event_id)    
                continue
            updated_event = CALENDAR_SERVICE.events().update(
                calendarId=ctx.config.calendar.id,
                eventId=event_id,
                body=event,
            ).execute()
            ctx.logger.info("Das vorhandene Event '%s' wurde geupdated.", updated_event.get("htmlLink"))
    else:
        ctx.logger.info("Es existiert kein Eintrag für das Match.")
        new_event = CALENDAR_SERVICE.events().insert(
            calendarId=ctx.config.calendar.id,
            body=event,
        ).execute()
        ctx.logger.info("Event '%s' wurde erstellt.", new_event.get('htmlLink'))

