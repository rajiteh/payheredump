import logging
import sys

requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True


class ExitOnCriticalHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        if record.levelno is logging.CRITICAL:
            exit(1)


def get_logger(name):
    logger = logging.getLogger(name)
    handler = ExitOnCriticalHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s]\t[%(name)s]\t%(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger
