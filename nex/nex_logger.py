"""
NEX Central Logger
All pipelines write to ~/.config/nex/pipeline.log
auto_check.py tails this file for streaming display
"""
import os
import sys
from pathlib import Path
from datetime import datetime

LOG_DIR = Path.home() / ".config/nex"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "pipeline.log"

# Color codes for terminal (optional, can be stripped for log file)
class C:
    RST  = "\033[0m"
    B    = "\033[1m"
    DIM  = "\033[2m"
    RED  = "\033[31m"
    GRN  = "\033[32m"
    YEL  = "\033[33m"
    BLU  = "\033[34m"
    MAG  = "\033[35m"
    CYN  = "\033[36m"
    BGRN = "\033[92m"
    BYEL = "\033[93m"
    BCYN = "\033[96m"

def log(source, message, level="INFO"):
    """Write a timestamped line to pipeline.log"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] [{level}] [{source}] {message}\n"
    
    # Write to log file (no colors)
    with open(LOG_FILE, "a") as f:
        f.write(line)
    
    # Also print to terminal with colors if this is being run directly
    if sys.stdout.isatty():
        color_map = {
            "GROQ": C.BGRN,
            "GEMINI": C.BCYN,
            "OPTIMIZER": C.BMAG if hasattr(C, 'BMAG') else C.MAG,
            "POST": C.BYEL,
            "AUTO": C.CYN,
            "ERROR": C.RED,
            "INFO": C.DIM
        }
        src_color = color_map.get(source, C.DIM)
        level_color = C.RED if level == "ERROR" else C.DIM
        print(f"  {src_color}[{source}]{C.RST} {level_color}[{level}]{C.RST} {message}")
