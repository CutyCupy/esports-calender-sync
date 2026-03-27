from datetime import datetime, timedelta


from context import Context
from parser import GERMAN_WEEKDAYS, SHEETS_SERVICE, TZ

from match import CastInfo, Match

casting_calendar_rows: list[list[str]] = []
is_loaded = False
is_dirty = False

def load_casting_calendar(ctx: Context):
    global casting_calendar_rows, is_loaded

    if is_loaded:
        return

    casting_calendar_rows = load_rows(ctx)
    is_loaded = True

def get_row_data_for_match(match: Match) -> list[str]:
    date, weekday, time_value = format_date_fields(match.ts)

    return [
        date,
        weekday,
        match.id,
        time_value,
        match.game.value,
        "", # match.league
        match.url,
        match.our_team,
        match.cast_info.casters[0] if match.cast_info and len(match.cast_info.casters) > 0 else "",
        match.cast_info.casters[1] if match.cast_info and len(match.cast_info.casters) > 1 else "",
        match.cast_info.remark if match.cast_info else "",
        match.our_score,
        match.opponent_score,
    ]
    
def add_match_to_casting_calendar(ctx: Context, match: Match):
    global casting_calendar_rows, is_dirty

    load_casting_calendar(ctx)

    event_date = match.ts.date()
    ensure_date_range_for_day_local(event_date)

    row_data = get_row_data_for_match(match)

    for i, row in enumerate(casting_calendar_rows):
        if match.id != row[2]:
            continue

        match.cast_info = CastInfo(
            remark=row[10],
            casters=[c for c in row[8:10] if c]
        )

        if not match.our_score:
            match.our_score = row[11]
        if not match.opponent_score:
            match.opponent_score = row[12]

        new_row = get_row_data_for_match(match)

        if row == new_row:
            return

        casting_calendar_rows[i] = [row[0], row[1]] + [""] * 11
        is_dirty = True
        
        add_match_to_casting_calendar(ctx, match)
        return

    max_date_idx = None
    for i, row in enumerate(casting_calendar_rows):
        if row[0] != row_data[0]:
            continue
        row = casting_calendar_rows[i]
        if not row[2]:
            casting_calendar_rows[i] = row_data
            is_dirty = True
            return
        max_date_idx = i

    if max_date_idx == None:
        max_date_idx = len(casting_calendar_rows)

    casting_calendar_rows.insert(max_date_idx, row_data)
    is_dirty = True

def weekday_short_de(date_obj):
    return GERMAN_WEEKDAYS[date_obj.weekday()]


def format_date_fields(dt: datetime):
    dt = dt.astimezone(TZ)
    return (
        dt.strftime("%d.%m.%Y"),
        weekday_short_de(dt),
        dt.strftime("%H:%M"),
    )


def parse_date(value):
    return datetime.strptime(value, "%d.%m.%Y").date()


def load_rows(ctx: Context) -> list[list[str]]:
    result = SHEETS_SERVICE.spreadsheets().values().get(
        spreadsheetId=ctx.config.casting_calendar.sheet_id,
        range="A2:M",
    ).execute()

    values: list[list[str]] = result.get("values", [])

    return [
        row + [""] * (13 - len(row))
        for row in values
    ]


def analyze_sheet(rows: list[list[str]]):
    dates = {}
    ids = {}

    for i in range(len(rows)):
        row = rows[i]
        if len(row) > 0 and row[0]:
            try:
                parsed_date = parse_date(row[0])
                dates.setdefault(parsed_date, []).append(i)
            except ValueError:
                pass

        if len(row) > 2 and row[2]:
            ids[row[2]] = i

    return dates, ids

def ensure_date_range_for_day_local(target_day):
    global casting_calendar_rows

    if not casting_calendar_rows:
        row = empty_day_row(target_day)
        casting_calendar_rows.append(row)
        return
    
    first_known_date = parse_date(casting_calendar_rows[0][0])
    last_known_date = parse_date(casting_calendar_rows[-1][0])

    start = min(target_day, first_known_date)
    end = max(target_day, last_known_date)

    full_range = [
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
    ]

    for day in full_range:
        if day >= first_known_date and day <= last_known_date:
            continue

        casting_calendar_rows.append(empty_day_row(day))

def commit_casting_calendar(ctx: Context):
    global is_dirty, is_loaded, casting_calendar_rows
    if not is_loaded:
        return

    casting_calendar_rows = sorted(casting_calendar_rows, key=lambda x: parse_date(x[0]))
    
    i = 0    
    while i + 1 < len(casting_calendar_rows):
        i += 1
        prev = casting_calendar_rows[i-1]
        cur = casting_calendar_rows[i]
        
        if prev[0] != cur[0]:
            continue
        
        if not prev[2]:
            del casting_calendar_rows[i-1]
            i -= 1
            is_dirty = True
        elif not cur[2] or prev == cur: 
            del casting_calendar_rows[i]
            i -= 1 
            is_dirty = True

    if is_dirty:
        ctx.logger.info("Schreibe Casting Calendar zurück ins Sheet...")

        values = [row for row in casting_calendar_rows]

        SHEETS_SERVICE.spreadsheets().values().update(
            spreadsheetId=ctx.config.casting_calendar.sheet_id,
            range="A2:M",
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
    
    end_index = 1
    
    cmp_date = (datetime.now() - timedelta(days=10)).date()
    
    for i, row in enumerate(casting_calendar_rows):
        if cmp_date < parse_date(row[0]):
            end_index = i
            break
        
    SHEETS_SERVICE.spreadsheets().batchUpdate(
        spreadsheetId=ctx.config.casting_calendar.sheet_id,
        body={
            "requests": [
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": get_sheet_id(ctx),
                            "dimension": "ROWS",
                            "startIndex": 1,
                            "endIndex": end_index,
                        },
                        "properties": {
                            "hiddenByUser": True
                        },
                        "fields": "hiddenByUser",
                    }
                }
            ]
        },
    ).execute()
    
    is_dirty = False
    is_loaded = False

def get_sheet_id(ctx: Context, title="Tabellenblatt1"):
    meta = SHEETS_SERVICE.spreadsheets().get(
        spreadsheetId=ctx.config.casting_calendar.sheet_id,
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
