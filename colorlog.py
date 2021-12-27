"""Colored logging with logging and colorama."""
import logging

import colorama
from colorama import Fore

class ColoredFormatter(logging.Formatter):
    """Class implementing colored formatting for logging module."""
    def format(self, record: logging.LogRecord) -> str:
        if record.levelname == "INFO":
            record.msg = Fore.GREEN + record.msg + Fore.RESET
        elif record.levelname == "DEBUG":
            record.msg = Fore.CYAN + record.msg + Fore.RESET
        elif record.levelname == "ERROR":
            record.msg = Fore.RED + record.msg + Fore.RESET
        return logging.Formatter.format(self, record)

def setup(file_name: str = "") -> None:
    """Setup all the logging."""

    colorama.init()

    #standart setup
    logging.getLogger().setLevel(logging.DEBUG)

    #File logger first to prevent colorama's escape sequences in log file.
    if file_name:
        file_logger = logging.FileHandler(file_name)
        file_formatter = logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S")
        file_logger.setFormatter(file_formatter)
        logging.getLogger().addHandler(file_logger)

    #And now console logger
    console_formatter = ColoredFormatter("%(asctime)s %(message)s", "%H:%M:%S")
    console_logger = logging.StreamHandler()
    console_logger.setFormatter(console_formatter)
    logging.getLogger().addHandler(console_logger)
