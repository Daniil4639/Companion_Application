import logging
import sys


def setup_logger(name: str, level : int) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        formatter = logging.Formatter(
            '[%(asctime)s] - [%(name)s] - [%(levelname)s] - [%(message)s]',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


character_helper_logger = setup_logger('character_helper', logging.DEBUG)