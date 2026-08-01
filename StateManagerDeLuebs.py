import cv2
import numpy as np
import os
import json
import time
from datetime import datetime


class HighscoreManager:
    """Adaptiert aus Shooting DeLübs: Verwaltet die highscore.json sicher."""
    def __init__(self, datei_manager):
        self.dm = datei_manager
        self.file_path = os.path.join("savegames", "highscore.json")
        os.makedirs("savegames", exist_ok=True)
        self.data = []
        self.readonly = False
        self.load_highscores()

    def save_highscore(self, highscore_entry):
        if self.readonly:
            self.dm.write_log("SYSTEM-FEHLER: Speichern blockiert! highscore.json ist defekt/schreibgeschützt.")
            print("❌ Speichern blockiert! (Siehe Log)")
            return

        self.data.append(highscore_entry)
        temp_file = self.file_path + ".tmp"
        
        try:
            with open(temp_file, "w", encoding="utf-8") as file:
                json.dump(self.data, file, indent=4)
            os.replace(temp_file, self.file_path)
            print("💾 Highscore sicher gespeichert.")
        except OSError as e:
            self.dm.write_log(f"KRITISCHER FEHLER beim Speichern: {e}")
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except OSError: pass

    def load_highscores(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                self.data = json.load(file)
            self.readonly = False
        except FileNotFoundError:
            self.data = []
            self.readonly = False
        except json.JSONDecodeError:
            self.data = []
            self.readonly = True
            self.dm.write_log("FEHLER: highscore.json beschädigt! Starte im Readonly-Modus.")
        except OSError as e:
            self.data = []
            self.readonly = True
            self.dm.write_log(f"FEHLER: Kein Zugriff auf Highscore ({e}). Readonly-Modus aktiv.")


class CameraState:
    def __init__(self, side, config):
        self.side = side
        self.prev_gray = None
        self.is_moving = False
        self.still_counter = 0
        self.target_present = False
        self.is_initialized = False 
        self.last_scan_time = 0 
        
        self.motion_threshold = config.getint('Erkennung', 'motion_threshold')
        self.motion_tolerance = config.getint('Erkennung', 'motion_tolerance', fallback=25)
        self.stillness_limit = config.getint('Timing', 'stillness_frames')
        
        bg_sec = 'Hintergrund_Links' if side == 'left' else 'Hintergrund_Rechts'
        r = config.getint(bg_sec, 'rgb_r')
        g = config.getint(bg_sec, 'rgb_g')
        b = config.getint(bg_sec, 'rgb_b')
        tol = config.getint(bg_sec, 'tolerance')
        
        self.min_area = config.getfloat(bg_sec, 'min_area_percent')
        self.lower_color = np.array([max(0, b-tol), max(0, g-tol), max(0, r-tol)])
        self.upper_color = np.array([min(255, b+tol), min(255, g+tol), min(255, r+tol)])
        
        self.cumulative_mask = None

    def is_background_visible(self, frame):
        mask = cv2.inRange(frame, self.lower_color, self.upper_color)
        total_pixels = frame.shape[0] * frame.shape[1]
        matching_pixels = cv2.countNonZero(mask)
        percent = (matching_pixels / total_pixels) * 100
        return (percent >= self.min_area), percent

    def check_motion(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        motion_detected = False
        if self.prev_gray is not None:
            diff = cv2.absdiff(self.prev_gray, gray)
            _, thresh = cv2.threshold(diff, self.motion_tolerance, 255, cv2.THRESH_BINARY)
            if cv2.countNonZero(thresh) > self.motion_threshold:
                motion_detected = True
        self.prev_gray = gray
        return motion_detected


class StateManager:
    def __init__(self, config, datei_manager):
        self.config = config
        self.dm = datei_manager
        self.hm = HighscoreManager(self.dm)
        
        use_left = config.getboolean('Kameras', 'nutze_kamera_links')
        use_right = config.getboolean('Kameras', 'nutze_kamera_rechts')
        
        self.state_left = CameraState('left', config) if use_left else None
        self.state_right = CameraState('right', config) if use_right else None
        
        self.match_start_mono = time.monotonic()
        self.current_match_id = self.get_next_match_id()
        self.shots = []
        
        self.dm.write_log(f"SYSTEM: 🔄 Neues Match initialisiert (ID: {self.get_formatted_match_id()})")

    def get_next_match_id(self):
        highest_id = 0
        log_dir = os.path.join("savegames", "logs")
        os.makedirs(log_dir, exist_ok=True) 
        
        for filename in os.listdir(log_dir): 
            if filename.startswith("MATCH") and filename.endswith(".zip"):
                try: 
                    number = int(filename[5:-4])
                    if number > highest_id: highest_id = number
                except ValueError: pass 
        
        if self.hm.data:
            highest_json_id = max([int(eintrag.get("match_id", 0) or 0) for eintrag in self.hm.data])
            if highest_json_id > highest_id: highest_id = highest_json_id
                
        return highest_id + 1

    def get_formatted_match_id(self):
        return f"{self.current_match_id:06d}"

    def add_shot(self, side, cx, cy, area):
        shot_data = {
            'side': side,
            'pos': (cx, cy),
            'area': area,
            'is_new': True,
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            't_mono': time.monotonic() - self.match_start_mono
        }
        for shot in self.shots:
            if shot['side'] == side:
                shot['is_new'] = False
                
        self.shots.append(shot_data)
        return shot_data

    def get_shots_for_side(self, side):
        return [s for s in self.shots if s['side'] == side]

    def reset_match(self, side):
        """Setzt das Match für eine Seite (oder 'all' für beide) zurück."""
        if side == 'all':
            self.shots = []
            if self.state_left: self.state_left.cumulative_mask = None
            if self.state_right: self.state_right.cumulative_mask = None
        else:
            self.shots = [s for s in self.shots if s['side'] != side]
            state = self.state_left if side == 'left' else self.state_right
            if state: state.cumulative_mask = None
            
        # Wenn die Schussliste leer ist, starten wir ein komplett neues Match
        if not self.shots:
            self.current_match_id = self.get_next_match_id()
            self.match_start_mono = time.monotonic()
            self.dm.write_log(f"SYSTEM: 🔄 Komplett neues Match gestartet (ID: {self.get_formatted_match_id()})")

    def save_current_match(self, player_name="Schütze 1"):
        """Erstellt die Match-JSON, packt sie ins ZIP und setzt das Match zurück."""
        if not self.shots:
            self.dm.write_log("SYSTEM: Speichern abgebrochen - Keine Treffer vorhanden.")
            return False

        # Prüfen, welche Kameras aktiv waren
        cam_l = self.config.getboolean('Kameras', 'nutze_kamera_links')
        cam_r = self.config.getboolean('Kameras', 'nutze_kamera_rechts')
        if cam_l and cam_r: cam_str = "Links & Rechts"
        elif cam_l: cam_str = "Nur Links"
        elif cam_r: cam_str = "Nur Rechts"
        else: cam_str = "Keine"

        # 1. Metadaten für Highscore und JSON
        metadata = {
            "spieler": player_name,  # <--- HIER DEN NAMEN ÜBERGEBEN
            "programm_name": "TargetVision",
            "kameras": cam_str,
            "treffer_links": len(self.get_shots_for_side('left')),
            "treffer_rechts": len(self.get_shots_for_side('right')),
            "gesamtpunkte": len(self.shots),
            "erkennungs_methode": self.config.get('Erkennung', 'erkennungs_methode'),
            "match_id": self.current_match_id,
            "version": self.dm.get_current_version(),
            "timestamp": datetime.now().strftime("%d.%m.%y %H:%M:%S")
        }

        # 2. Timeline
        timeline = []
        for s in self.shots:
            timeline.append({
                "t": round(s['t_mono'], 3),
                "s": "l" if s['side'] == 'left' else "r",
                "x": s['pos'][0],
                "y": s['pos'][1],
                "a": round(s['area'], 1)
            })

        match_data = {"metadata": metadata, "timeline": timeline}

        # 3. ZIP erstellen und die JSON-Daten direkt übergeben
        os.makedirs(os.path.join("savegames", "logs"), exist_ok=True)
        zip_filepath = os.path.join("savegames", "logs", f"MATCH{self.get_formatted_match_id()}.zip")
        
        # Aufruf mit dem neuen Parameter
        self.dm.create_zip_package(zip_filepath, match_data=match_data)

        # 4. Highscore speichern und Match auf null setzen
        self.hm.save_highscore(metadata)
        self.dm.write_log(f"SYSTEM: 🏆 Match {self.get_formatted_match_id()} gespeichert!")
        
        # ---> NEU: Das Match nach dem Speichern komplett abräumen <---
        self.reset_match('all')
        return True