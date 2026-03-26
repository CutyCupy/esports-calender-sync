from time import sleep

from fastapi import HTTPException, FastAPI, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from pathlib import Path
import re
from datetime import datetime

import main

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


# --- API Endpoints ---

templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def ui(request: Request):
    cfg = main.load_config()
    del cfg["primeleague_token"]
    del cfg["casting-sheet-id"]
    with open("cron.log", "r", encoding="utf-8") as f:
        log = f.read()
    return templates.TemplateResponse(request, name="index.html", context={
        "request": request,
        "log": log,
        "config": cfg
    })


@app.get("/logs", response_class=HTMLResponse)
def get_logs(request: Request):
    base_dir = Path("logs")

    log_groups = []

    if not base_dir.exists():
        return templates.TemplateResponse(
            request,
            "logs.html",
            {"request": request, "log_groups": []},
        )

    # Datumsordner sortieren (neu -> alt)
    for date_dir in sorted(base_dir.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue

        runs = []

        # Logfiles sortieren (neu -> alt)
        for log_file in sorted(date_dir.glob("*.log"), reverse=True):
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

                runs.append({
                    "filename": log_file.name,
                    "path": str(log_file),
                    "timestamp": timestamp,
                    "warnings": warnings,
                    "errors": errors,
                    "duration": duration,
                })

            except Exception:
                continue

        log_groups.append({
            "date": date_dir.name,
            "runs": runs,
        })

    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "request": request,
            "log_groups": log_groups,
        },
    )

BASE_LOG_DIR = Path("logs").resolve()

@app.get("/logs/view")
def view_log(path: str):
    file_path = Path(path).resolve()

    if not str(file_path).startswith(str(BASE_LOG_DIR)):
        return PlainTextResponse("Forbidden", status_code=403)

    if not file_path.exists():
        return PlainTextResponse("Not found", status_code=404)

    return PlainTextResponse(file_path.read_text(encoding="utf-8"))

@app.post("/config")
def update_config(cfg: dict):
    main.save_config(cfg)
    return {"status": "ok"}


@app.post("/match/add")
def add_match(url: str = Form()):
    parser = main.get_parser(url)
    if not parser:
        raise HTTPException(status_code=400, detail=f"Die URL '{url}' ist keine gültige URL für die Konfiguration.")
    
    cfg = main.load_config()
    teams = cfg.get("teams", [])
    if url in teams:
        raise HTTPException(status_code=400, detail=f"Die URL '{url}' ist bereits Teil der Konfiguration.")        
    teams.append(url)
    cfg["teams"] = teams
    main.save_config(cfg)
    return {"status": "added", "url": url}

@app.post("/match/remove")
def remove_match(url: str = Form()):
    cfg = main.load_config()
    cfg["teams"] = [m for m in cfg.get("teams", []) if m != url]
    main.save_config(cfg)
    return {"status": "removed"}


@app.post("/run")
def run_processing():
    from main import main
    main()
    