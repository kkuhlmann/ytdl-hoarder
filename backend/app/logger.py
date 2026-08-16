import logging

from config import settings

logger = logging.getLogger('app')

handler = logging.StreamHandler()
logger.addHandler(handler)

level = logging.getLevelName(settings.logging.level.upper())
logger.setLevel(level)

formatter = logging.Formatter('[%(levelname)s] %(module)s:%(lineno)d: %(message)s')
handler.setFormatter(formatter)
