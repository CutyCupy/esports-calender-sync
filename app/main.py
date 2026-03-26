import json
import time
from datetime import datetime, timedelta


from context import Context
from google_calendar import add_match_to_google_calendar
from casting_calendar import add_match_to_casting_calendar, commit_casting_calendar
from config import Config # type: ignore
from logger import cleanup_logs, setup_run_logger
from parser import CALENDAR_SERVICE, GERMAN_WEEKDAYS, SHEETS_SERVICE, TZ, parse_url

from match import CastInfo, Match


    
def main():
    logger, log_file = setup_run_logger()
    
    ctx = Context(
        logger=logger, log_file=log_file, config=Config.load()
    )
    
    cleanup_logs(days=7)
    start = time.time()
    
    logger.info("Start der Verarbeitung")
    for url in ctx.config.teams:
        logger.info("Start der Verarbeitung von '%s'", url)
        try:
            matches = parse_url(ctx, url.strip())
        except Exception:
            logger.exception("Failed processing URL: %s", url, stack_info=True)
            continue

        for match in matches:
            logger.info(
                "Match %s | %s vs %s",
                match.id,
                match.our_team,
                match.opponent_team,
            )
            try:
                add_match_to_casting_calendar(ctx, match)
                add_match_to_google_calendar(ctx, match)
            except Exception:
                logger.exception(
                    "Fehler bei Match %s\n%s",
                    match.id,
                    json.dumps(match, indent=2, default=str)
                )
        
    commit_casting_calendar(ctx)
    logger.info("Verarbeitung nach %.2fs abgeschlossen.", time.time() - start)
    logger.info("Logfile: %s", log_file)


if __name__ == "__main__":
    main()