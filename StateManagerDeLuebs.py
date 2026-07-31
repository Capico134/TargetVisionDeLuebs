import time
import cv2
import numpy as np
import os
import json
from datetime import datetime

class CameraState:
    def __init__(self, side, config):
        self.side = side
        self.prev_gray = None
        self.is_moving = False
        self.still_counter = 0
        self.target_present = False
        self.last_motion_log = 0 
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
        is_visible = percent >= self.min_area
        return is_visible, percent

    def check_motion(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        
        motion_detected = False
        if self.prev_gray is not None:
            diff = cv2.absdiff(self.prev_gray, gray)
            _, thresh = cv2.threshold(diff, self.motion_tolerance, 255, cv2.THRESH_BINARY)
            motion_pixels = cv2.countNonZero(thresh)
            
            if motion_pixels > self.motion_threshold:
                motion_detected = True
                
        self.prev_gray = gray
        return motion_detected

class StateManager:
    def __init__(self, config, datei_manager):
        self.config = config
        self.dm = datei_manager
        
        use_left = config.getboolean('Kameras', 'nutze_kamera_links')
        use_right = config.getboolean('Kameras', 'nutze_kamera_rechts')
        
        self.state_left = CameraState('left', config) if use_left else None
        self.state_right = CameraState('right', config) if use_right else None
        
        # --- Match-Datenbank für Highscores ---
        self.current_match_id = self.get_next_match_id()
        self.match_start_time = datetime.now()
        self.shots = []
        
        self.dm.write_log(f"SYSTEM: 🔄 Neues Match initialisiert (ID: {self.get_formatted_match_id()})")

    def get_next_match_id(self):
        """Ermittelt die nächste freie Match-ID basierend auf ZIP-Dateien und Highscore-Liste."""
        highest_id = 0
        log_dir = os.path.join("savegames", "logs")
        os.makedirs(log_dir, exist_ok=True) 
        
        # 1. Zip-Dateien prüfen
        for filename in os.listdir(log_dir): 
            if filename.startswith("MATCH") and filename.endswith(".zip"):
                try: 
                    # Schneidet "MATCH" (5 Zeichen) vorne und ".zip" (4 Zeichen) hinten ab
                    number_str = filename[5:-4] 
                    number = int(number_str)
                    if number > highest_id:
                        highest_id = number
                except ValueError:
                    pass 
        
        # 2. Highscore.json prüfen (Fallback, da der Highscore-Manager noch nicht existiert)
        highscore_path = os.path.join("savegames", "highscore.json")
        if os.path.exists(highscore_path):
            try:
                with open(highscore_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data:
                        highest_json_id = max([int(eintrag.get("match_id", 0) or 0) for eintrag in data])
                        if highest_json_id > highest_id:
                            highest_id = highest_json_id
            except (json.JSONDecodeError, ValueError):
                pass
                
        return highest_id + 1

    def get_formatted_match_id(self):
        """Gibt die ID als formatierten String zurück, z.B. '000434'"""
        return f"{self.current_match_id:06d}"

    def add_shot(self, side, cx, cy, area):
        """Fügt einen neuen Schuss zur aktuellen Match-Historie hinzu."""
        shot_data = {
            'side': side,
            'pos': (cx, cy),
            'area': area,
            'is_new': True,
            'timestamp': datetime.now().strftime("%H:%M:%S")
        }
        
        for shot in self.shots:
            if shot['side'] == side:
                shot['is_new'] = False
                
        self.shots.append(shot_data)
        return shot_data

    def get_shots_for_side(self, side):
        """Gibt alle Treffer für eine bestimmte Kameraseite zurück."""
        return [s for s in self.shots if s['side'] == side]

    def reset_match(self, side):
        """Setzt das Match für eine Seite zurück (Referenz neu setzen, Historie löschen)."""
        self.shots = [s for s in self.shots if s['side'] != side]
        
        state = self.state_left if side == 'left' else self.state_right
        if state:
            state.cumulative_mask = None
            
        if not self.shots:
            self.current_match_id = self.get_next_match_id()
            self.match_start_time = datetime.now()
            self.dm.write_log(f"SYSTEM: 🔄 Komplett neues Match gestartet (ID: {self.get_formatted_match_id()})")