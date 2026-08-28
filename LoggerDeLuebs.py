import os
import sys

# 1. Ordner sicherstellen
os.makedirs("savegames", exist_ok=True)
log_file = os.path.join("savegames", "console_log.txt")
old_log_file = os.path.join("savegames", "console_log_old.txt")

# 2. Log-Rotation: Das Log vom vorherigen Start als "old" aufbewahren!
if os.path.exists(log_file):
    if os.path.exists(old_log_file):
        try: os.remove(old_log_file)
        except Exception: pass
    try: os.rename(log_file, old_log_file)
    except Exception: pass 
    # (Hinweis: Wenn TargetVision schon läuft und die Highscore gestartet wird,
    # schlägt das Umbenennen hier sanft fehl und die Highscore hängt ihre 
    # Logs einfach nahtlos unten an die aktuelle Datei an. Perfekt!)

# 3. Unsere Klasse, die beides gleichzeitig macht (Terminal + Datei)
class DualLogger:
    def __init__(self, filepath, stream):
        self.terminal = stream
        self.log = open(filepath, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

# 4. Standard-Ausgabe (print) und Fehler-Ausgabe (Exceptions) umleiten!
sys.stdout = DualLogger(log_file, sys.stdout)
sys.stderr = DualLogger(log_file, sys.stderr)