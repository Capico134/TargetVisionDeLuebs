import cv2
import numpy as np
import os
import json
import time
import math
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
        self.is_fortsetzung = False
        self.last_scan_time = 0 
        
        self.motion_threshold = config.getint('Erkennung', 'motion_threshold')
        self.motion_tolerance = config.getint('Erkennung', 'motion_tolerance', fallback=25)
        self.stillness_frames = config.getint('Timing', 'stillness_frames')
        
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
        # ---> NEU: Speicher für die Nullpunkte beider Kameras
        self.nullpunkts = {'left': None, 'right': None}
        # --- NEU ---
        self.ringwertung_aktiv = config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
        
        #self.dm.write_log(f"SYSTEM: 🔄 Neues Match initialisiert (ID: {self.get_formatted_match_id()})")
        self.dm.write_log("\n" + "="*80)
        self.dm.write_log(f"SYSTEM: 🔄 Neues Match initialisiert (ID: {self.get_formatted_match_id()})")
        self.dm.write_log("="*80 + "\n")

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

    def set_nullpunkt(self, side, cx, cy):
        """Speichert den exakten weißen Punkt aus der Kalibrierung."""
        self.nullpunkts[side] = (cx, cy)

    # ---> NEU: Ausgelagerte Funktion für die Ringwert-Berechnung <---
    def calculate_score(self, side, cx, cy):
        """Berechnet den Ringwert für gegebene Koordinaten."""
        score = 0.0
        nullpunkt = self.nullpunkts.get(side)
        
        if self.ringwertung_aktiv and nullpunkt:
            seite_str = "links" if side == 'left' else "rechts"
            px_x = self.config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
            px_y = self.config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
            
            dx_px = abs(cx - nullpunkt[0])
            dy_px = abs(cy - nullpunkt[1])
            
            dx_mm = dx_px / px_x
            dy_mm = dy_px / px_y
            dist_mm = math.sqrt(dx_mm**2 + dy_mm**2)
            
            aktive_scheibe_id = self.config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
            print(f"aktive_scheibe_id {aktive_scheibe_id}")
            targets = self.dm.load_targets()
            
            if aktive_scheibe_id in targets:
                target_data = targets[aktive_scheibe_id]
                d_10 = target_data['ringe_durchmesser_mm']['10']
                d_9 = target_data['ringe_durchmesser_mm']['9']
                kaliber = target_data.get('kaliber_mm', 4.5)
                
                ring_abstand_radius_mm = (d_9 - d_10) / 2.0
                
                # Ab welchem Abstand vom Zentrum ist es exakt eine 10.0?
                # (Halber 10er-Ring + halbes Kaliber)
                radius_10_score = (d_10 + kaliber) / 2.0
                
                # Die universelle, physikalische Formel:
                raw_score = 10.0 + ((radius_10_score - dist_mm) / ring_abstand_radius_mm)
                
                score = math.floor(raw_score * 10) / 10.0
                
                if score > 10.9: score = 10.9
                if score < 1.0: score = 0.0
                
        return score

    def add_shot(self, side, cx, cy, area, cv_score=0.0):
        """Speichert einen neuen Schuss und berechnet die Ring-Zehntelwertung!"""
        # ---> NEU: Ruft einfach unsere saubere Hilfsfunktion auf <---
        score = self.calculate_score(side, cx, cy)
        
        shot_data = {
            'side': side,
            'pos': (cx, cy),
            'area': area,
            'score': score,
            'cv_score': cv_score,
            'timestamp': time.time(),
            't_mono': time.monotonic() - getattr(self, 'match_start_mono', time.monotonic()), 
            'is_new': True
        }
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
            # self.dm.write_log(f"SYSTEM: 🔄 Komplett neues Match gestartet...") <-- LÖSCHEN und ersetzen durch:
            self.dm.write_log("\n" + "="*80)
            self.dm.write_log(f"SYSTEM: 🔄 Komplett neues Match gestartet (ID: {self.get_formatted_match_id()})")
            self.dm.write_log("="*80 + "\n")

    def save_current_match(self, player_name_l="Schütze 1", player_name_r="Schütze 2"):
        """Erstellt die Match-JSON, packt sie ins ZIP und setzt das Match zurück."""
        if not self.shots:
            self.dm.write_log("SYSTEM: Speichern abgebrochen - Keine Treffer vorhanden.")
            return False

        # ---> ELA: Die gesamte Datenbeschaffung läuft nun über unsere zentrale Funktion! <---
        match_data = self.get_match_data(player_name_l, player_name_r)

        os.makedirs(os.path.join("savegames", "logs"), exist_ok=True)
        zip_filepath = os.path.join("savegames", "logs", f"MATCH{self.get_formatted_match_id()}.zip")
        
        self.dm.export_match_package(
            filepath=zip_filepath, 
            match_data=match_data,
            source_folder=self.dm.DEBUG_FOLDER,
            apply_diet_filter=False
        )

        self.hm.save_highscore(match_data["metadata"])
        ringe_str = match_data["metadata"]["gesamt_ringe_anzeige"]
        self.dm.write_log(f"SYSTEM: 🏆 Match {self.get_formatted_match_id()} gespeichert (Ringe: {ringe_str})!")
        
        self.reset_match('all')
        return True
        
    def get_match_data(self, player_name_l="Schütze 1", player_name_r="Schütze 2"):
        """Zentrale ELA-Funktion: Generiert das komplette JSON-Datenpaket für ein Match."""
        cam_l = self.config.getboolean('Kameras', 'nutze_kamera_links')
        cam_r = self.config.getboolean('Kameras', 'nutze_kamera_rechts')
        
        if cam_l and cam_r: cam_str = "Links & Rechts"
        elif cam_l: cam_str = "Nur Links"
        elif cam_r: cam_str = "Nur Rechts"
        else: cam_str = "Keine"

        shots_l = self.get_shots_for_side('left')
        shots_r = self.get_shots_for_side('right')
        gesamt_l = round(sum(s.get('score', 0.0) for s in shots_l), 1)
        gesamt_r = round(sum(s.get('score', 0.0) for s in shots_r), 1)

        if cam_l and cam_r and player_name_l != player_name_r:
            spieler_str = f"{player_name_l} / {player_name_r}"
            ringe_str = f"{gesamt_l} / {gesamt_r}"
        else:
            spieler_str = player_name_l if cam_l else player_name_r
            if cam_l and cam_r:
                ringe_str = f"{gesamt_l} / {gesamt_r}"
            elif cam_l:
                ringe_str = str(gesamt_l)
            else:
                ringe_str = str(gesamt_r)

        if cam_l and cam_r:
            schuesse_str = f"{len(shots_l)} / {len(shots_r)}"
        elif cam_l:
            schuesse_str = str(len(shots_l))
        else:
            schuesse_str = str(len(shots_r))

        center_l_raw = self.nullpunkts.get('left')
        center_r_raw = self.nullpunkts.get('right')

        dauer_sekunden = time.monotonic() - getattr(self, 'match_start_mono', time.monotonic())
        start_zeit_timestamp = time.time() - dauer_sekunden
        start_zeit_str = datetime.fromtimestamp(start_zeit_timestamp).strftime("%d.%m.%y %H:%M:%S")

        metadata = {
            "spieler": spieler_str,  
            "programm_name": "TargetVision",
            "kameras": cam_str,
            "treffer_links": int(len(shots_l)),
            "treffer_rechts": int(len(shots_r)),
            "gesamtpunkte": int(len(self.shots)),
            "gesamtpunkte_anzeige": schuesse_str, 
            "gesamt_ringe_anzeige": ringe_str,    
            "gesamt_ringe": float(gesamt_l + gesamt_r),  
            "erkennungs_methode": str(self.config.get('Erkennung', 'erkennungs_methode')),
            "match_id": int(self.current_match_id),
            "version": str(self.dm.get_current_version()),
            "start_zeit": start_zeit_str,
            "timestamp": datetime.now().strftime("%d.%m.%y %H:%M:%S"),
            "center_l": [int(center_l_raw[0]), int(center_l_raw[1])] if (cam_l and center_l_raw) else None,
            "center_r": [int(center_r_raw[0]), int(center_r_raw[1])] if (cam_r and center_r_raw) else None,
            "fortsetzung_links": bool(self.state_left.is_fortsetzung) if (cam_l and self.state_left) else False,
            "fortsetzung_rechts": bool(self.state_right.is_fortsetzung) if (cam_r and self.state_right) else False
        }

        timeline = []
        for s in self.shots:
            timeline.append({
                "t": round(float(s['t_mono']), 3),
                "s": "l" if s['side'] == 'left' else "r",
                "x": int(s['pos'][0]),
                "y": int(s['pos'][1]),
                "a": round(float(s['area']), 1),
                "score": float(s.get('score', 0.0)),
                "cv_score": round(float(s.get('cv_score', 0.0)), 1),
                "edited": bool(s.get('is_edited', False))
            })

        return {"metadata": metadata, "timeline": timeline}

    def load_match_state(self, match_data):
        """ELA: Überschreibt den aktuellen Live-Status mit Daten aus einer JSON."""
        self.shots = []
        meta = match_data.get('metadata', {})
        self.current_match_id = meta.get('match_id', self.current_match_id)
        
        # Nullpunkte wiederherstellen
        cl = meta.get('center_l')
        cr = meta.get('center_r')
        if cl: self.nullpunkts['left'] = tuple(cl)
        if cr: self.nullpunkts['right'] = tuple(cr)
        
        # Timeline wiederherstellen
        for h in match_data.get('timeline', []):
            side_str = 'left' if h['s'] == 'l' else 'right'
            self.shots.append({
                'side': side_str,
                'pos': (h['x'], h['y']),
                'area': h.get('a', 0.0),
                'score': h.get('score', 0.0),
                'cv_score': h.get('cv_score', 0.0),
                't_mono': h.get('t', 0.0),
                'timestamp': time.time(), # Optischer Dummy für die GUI
                'is_new': False, # WICHTIG: Alte Schüsse sollen nicht rot blinken!
                'is_edited': h.get('edited', False)
            })
        self.dm.write_log(f"SYSTEM: 🔄 Status aus Handover wiederhergestellt ({len(self.shots)} Treffer).")

    def update_shot(self, shot_ref, new_x, new_y, new_score):
        """Aktualisiert die Koordinaten und den Score eines existierenden Schusses."""
        if shot_ref in self.shots:
            old_x, old_y = shot_ref['pos']
            old_score = shot_ref.get('score', 0.0)
            
            # Wir runden beide Seiten auf 1 Nachkommastelle. 
            # So ignorieren wir mikroskopische Float-Abweichungen durch die GUI!
            if (round(float(old_x), 1) != round(new_x, 1) or 
                round(float(old_y), 1) != round(new_y, 1) or 
                round(float(old_score), 1) != round(new_score, 1)):
                
                shot_ref['pos'] = (new_x, new_y)
                shot_ref['score'] = new_score
                shot_ref['is_edited'] = True

    def remove_shots(self, shots_to_remove):
        """Löscht eine Liste von Schüssen sicher aus dem State."""
        count = 0
        for s in shots_to_remove:
            if s in self.shots:
                self.shots.remove(s)
                count += 1
        if count > 0:
            self.dm.write_log(f"SYSTEM: {count} Treffer manuell gelöscht.")    