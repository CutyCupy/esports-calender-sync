from dataclasses import dataclass
from time import sleep

from fastapi import HTTPException, FastAPI, Query, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from pathlib import Path
import re
from datetime import datetime

from logger import LOGS_FOLDER
from config import Config  # type: ignore
from parser import get_parser

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

# --- API Endpoints ---

templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def ui(request: Request) -> HTMLResponse:
    cfg = Config.load()
    return templates.TemplateResponse(request, name="index.html", context={
        "request": request,
        "docs": [
            {
                "name": "Casting Kalender",
                "url": f"https://docs.google.com/spreadsheets/d/{cfg.casting_calendar.sheet_id}"
            },
            {
                "name": "Google Kalender",
                "url": f"https://calendar.google.com/calendar/embed?src={cfg.calendar.id}&ctz={cfg.calendar.timezone}"
            }
        ]
    })
    
def get_matches_response(request: Request) -> HTMLResponse:
    cfg = Config.load()
    return templates.TemplateResponse(request, "matches.html", {
        "request": request,
        "matches": cfg.teams,
    })

@app.get("/matches", response_class=HTMLResponse)
def get_matches(request: Request) -> HTMLResponse:
    return get_matches_response(request)


@dataclass
class LogResult:
    filename: str
    path: str
    timestamp: datetime
    warnings: int
    errors: int
    duration: str
    
@dataclass
class LogResultGroup:
    date: str
    logs: list[LogResult]

@app.get("/logs", response_class=HTMLResponse)
def get_logs(request: Request) -> HTMLResponse:
    base_dir = Path(LOGS_FOLDER)

    log_groups: list[LogResultGroup] = []

    if not base_dir.exists():
        return templates.TemplateResponse(
            request,
            "logs.html",
            {"request": request, "log_groups": []},
        )
    print(base_dir)

    # Datumsordner sortieren (neu -> alt)
    for date_dir in sorted(base_dir.iterdir(), reverse=True):
        print(date_dir)
        if not date_dir.is_dir():
            continue

        group = LogResultGroup(date=date_dir.name, logs=[])

        # Logfiles sortieren (neu -> alt)
        for log_file in sorted(date_dir.glob("*.log"), reverse=True):
            print(log_file)
            try:
                content = log_file.read_text(encoding="utf-8")

                warnings = len(re.findall(r"\[WARNING\]", content))
                errors = len(re.findall(r"\[ERROR\]", content))

                # Dauer extrahieren (falls vorhanden)
                duration_match = re.search(r"Verarbeitung nach ([\d.]+)s", content)
                duration = duration_match.group(1) + "s" if duration_match else "-"

                # Timestamp aus Dateiname
                time_part = log_file.stem.replace("run_", "")
                timestamp = datetime.strptime(
                    f"{date_dir.name} {time_part}",
                    "%Y-%m-%d %H-%M-%S",
                )

                group.logs.append(LogResult(
                    filename=log_file.name,
                    path=str(log_file),
                    timestamp=timestamp,
                    warnings=warnings,
                    errors=errors,
                    duration=duration,
                ))

            except Exception as e:
                print(e)
                continue

        log_groups.append(group)

    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "request": request,
            "log_groups": log_groups,
        },
    )


@app.get("/logs/view")
def view_log(path: str):
    file_path = Path(path).resolve()

    if not str(file_path).startswith(str(LOGS_FOLDER)):
        return PlainTextResponse("Forbidden", status_code=403)

    if not file_path.exists():
        return PlainTextResponse("Not found", status_code=404)

    return PlainTextResponse(file_path.read_text(encoding="utf-8"))

@app.post("/config")
def update_config(cfg: Config):
    cfg.save()
    return {"status": "ok"}


@app.post("/match/add", response_class=HTMLResponse)
def add_match(request: Request, url: str = Form()):
    parser = get_parser(url)
    if not parser:
        raise HTTPException(status_code=400, detail=f"Die URL '{url}' ist keine gültige URL für die Konfiguration.")
    
    cfg = Config.load()
    if url in cfg.teams:
        raise HTTPException(status_code=400, detail=f"Die URL '{url}' ist bereits Teil der Konfiguration.")        
    cfg.teams.append(url)
    cfg.save()
    return get_matches_response(request)

@app.post("/match/remove", response_class=HTMLResponse)
def remove_match(request: Request, url: str = Form()):
    cfg = Config.load()
    cfg.teams =  [m for m in cfg.teams if m != url]
    cfg.save()
    return get_matches_response(request)

@app.get("/preview", response_class=HTMLResponse)
def preview(
    request: Request,
    base_url: str = Query(...),
    is_preview: bool = Query(False)
):
    suffix = ""
    if "docs.google.com" in base_url:
        suffix = "/preview" if is_preview else "/edit"
    final_url = base_url.rstrip("/") + suffix

    return templates.TemplateResponse(request, name="preview.html", context={
        "request": request,
        "url": final_url
    })

@app.post("/run")
def run_processing():
    from main import main
    main()
    