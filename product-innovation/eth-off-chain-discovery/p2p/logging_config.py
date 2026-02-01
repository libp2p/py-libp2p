import logging
import sys

class ColoredFormatter(logging.Formatter):
    COLORS = {
        'INFO': '\033[32m',      
        'WARNING': '\033[33m',   
        'ERROR': '\033[31m',     
        'RESET': '\033[0m',
    }

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']
        
        levelname = f"{color}{record.levelname:8}{reset}"
        name = f"\033[90m{record.name}\033[0m"
        message = record.getMessage()
        
        return f"{levelname} {name} → {message}"

def setup_logging(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ColoredFormatter())
        logger.addHandler(handler)
    
    logger.propagate = False
    return logger
