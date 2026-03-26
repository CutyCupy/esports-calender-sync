from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import shutil

LOGS_FOLDER = Path(__file__).parent.parent / "logs"

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

    log_dir = os.path.join(LOGS_FOLDER, date_str)
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