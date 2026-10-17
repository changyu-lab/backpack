import time,subprocess
from pathlib import Path
while Path('/proc/1904454').exists():time.sleep(15)
b=Path('/data/vtmrc-vvenc-ai32-20261014')
if not (b/'summary.json').exists():subprocess.run(['python3','-u',str(b/'remote_ai32.py')],cwd=b,check=True)
