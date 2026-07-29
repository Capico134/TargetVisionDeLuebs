import cv2
import numpy as np
import time
import configparser
import os
import subprocess
from datetime import datetime

CONFIG_FILE = 'config.ini'
DEBUG_FOLDER = 'debug_bilder'
LOG_FILE = 'treffer_log.txt'

# Ordner für Debug-Bilder anlegen
if not os.path.exists(DEBUG_FOLDER):
    os.makedirs(DEBUG_FOLDER)

# Log-Datei beim Start leeren/neu anlegen
with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write(f"=== DIGITALE TREFFERANZEIGE LOG - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")

def get_current_version():
    try:
        raw_git = subprocess.check_output(
            ["git", "describe", "--tags", "--always", "--dirty"], 
            stderr=subprocess.DEVNULL
        ).strip().decode("utf-8")
        clean_version = raw_git.lstrip('v') 
        return clean_version
    except Exception:
        return "1.0.0-zip"

def update_ini_value(filepath, target_section, target_key, new_value):
    if not os.path.exists(filepath):
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    in_target_section = False
    section_found = False
    key_found = False
    insert_idx = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if stripped == f"[{target_section}]":
                in_target_section = True
                section_found = True
                insert_idx = i + 1
            else:
                if in_target_section:
                    in_target_section = False
                    insert_idx = i
        elif in_target_section and not stripped.startswith('#') and '=' in stripped:
            k, _ = line.split('=', 1)
            if k.strip() == target_key:
                lines[i] = f"{target_key} = {new_value}\n"
                key_found = True
                break
            insert_idx = i + 1

    if section_found and not key_found:
        if insert_idx == -1: insert_idx = len(lines)
        lines.insert(insert_idx, f"{target_key} = {new_value}\n")
    elif not section_found:
        if lines and not lines[-1].endswith('\n'):
            lines.append('\n')
        lines.append(f"\n[{target_section}]\n{target_key} = {new_value}\n")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"💾 config.ini Update: [{target_section}] {target_key} = {new_value}")

def load_or_create_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.write("""[Kameras]
# Aktiviert oder deaktiviert die jeweilige Kameraansicht
nutze_kamera_links = yes
nutze_kamera_rechts = yes
# Kamera-Indizes im System (0 ist meist die Standard-Webcam/OBS Virtual Cam)
cam_left_index = 0
cam_right_index = 1

[Erkennung]
# Mindestfläche in Pixeln, die eine Farb/Helligkeitsänderung haben muss, um als Loch zu gelten.
min_hole_area = 16
# Sperr-Radius um bestehende Treffer (in Pixeln) gegen Doppelzählungen.
caliber_radius = 14
# Anzahl veränderter Pixel im Bild, ab der eine Bewegung (Vibration/Fahrt) erkannt wird.
motion_threshold = 2000
# Farb/Helligkeits-Toleranz für die Bewegungserkennung.
motion_tolerance = 40
# Empfindlichkeit für Löcher (Referenz vs. Live).
hit_tolerance = 20
# Notbremse gegen Standbild/Ruckler in Prozent.
max_image_change_percent = 5.0

[Timing]
# Bildwiederholrate/Haupttakt in Millisekunden (33 ms entspricht ca. 30 FPS).
poll_ms = 33
# Wie viele Frames am Stück absolute Ruhe herrschen muss, damit das Bild als "stabil" gilt.
stillness_frames = 10

[Hintergrund_Links]
rgb_r = 234
rgb_g = 241
rgb_b = 190
tolerance = 30
min_area_percent = 40

[Hintergrund_Rechts]
rgb_r = 220
rgb_g = 135
rgb_b = 114
tolerance = 30
min_area_percent = 40

[Crop_Links]
cut_top = 0
cut_bottom = 0
cut_left = 175
cut_right = 20

[Crop_Rechts]
cut_top = 0
cut_bottom = 0
cut_left = 175
cut_right = 20

[Anzeige]
# Skalierungsfaktor für das Hauptfenster der Anzeige.
fenster_skalierung = 1.0
# Kiosk-Modus für den Schießstand (yes/no)
vollbild = no
""")
        print("Standard config.ini mit Kommentaren erstellt.")

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE, encoding='utf-8')
    return config

class CameraState:
    def __init__(self, side, config):
        self.side = side
        self.prev_gray = None
        self.is_moving = False
        self.still_counter = 0
        self.target_present = False
        self.last_motion_log = 0 
        self.is_initialized = False 
        
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
        
        # FIX: Das "Alte Diff-Bild" (Akkumulierte Maske für bekannte Treffer) initialisieren
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

class TargetTracker:
    def __init__(self, config):
        self.config = config
        self.version = get_current_version()
        print(f"🎯 TargetVision DeLübs     [v{self.version}]")
        self.window_name = f"TargetVision DeLuebs - v{self.version}"
        
        self.use_left = config.getboolean('Kameras', 'nutze_kamera_links')
        self.use_right = config.getboolean('Kameras', 'nutze_kamera_rechts')
        
        self.min_hole_area = config.getint('Erkennung', 'min_hole_area')
        self.caliber_radius = config.getint('Erkennung', 'caliber_radius')
        self.hit_tolerance = config.getint('Erkennung', 'hit_tolerance', fallback=15)
        self.max_img_change = config.getfloat('Erkennung', 'max_image_change_percent', fallback=5.0)
        self.poll_ms = config.getint('Timing', 'poll_ms', fallback=33)
        self.fullscreen = config.getboolean('Anzeige', 'vollbild', fallback=False)
        self.enhance_display = config.getboolean('Anzeige', 'darstellung_ohne_weissabgleich', fallback=True)
        
        self.cap_left = cv2.VideoCapture(config.getint('Kameras', 'cam_left_index')) if self.use_left else None
        self.cap_right = cv2.VideoCapture(config.getint('Kameras', 'cam_right_index')) if self.use_right else None

        self.state_left = CameraState('left', config) if self.use_left else None
        self.state_right = CameraState('right', config) if self.use_right else None

        self.ref_left = None
        self.ref_right = None
        self.shots = []
        
        self.current_crops = {'left': (0,0,0,0), 'right': (0,0,0,0)}
        self.raw_dims = {'left': (1,1), 'right': (1,1)}
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.w_left_displayed = 0
        
        self.msg_left = "System gestartet. Warte..."
        self.msg_right = "System gestartet. Warte..."
        
        self.btn_left_coords = None
        self.btn_right_coords = None
        self.btn_exit_coords = None
        
        self.trigger_reset_left = False
        self.trigger_reset_right = False
        self.trigger_exit = False

    def log(self, side, text):
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        log_msg = f"[{timestamp}] [{side.upper()}] {text}"
        print(log_msg)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
            
        gui_text = text if len(text) <= 45 else text[:42] + "..."
        if side == 'left':
            self.msg_left = gui_text
        elif side == 'right':
            self.msg_right = gui_text

    def save_debug_image(self, name, image):
        path = os.path.join(DEBUG_FOLDER, f"{name}.jpg")
        cv2.imwrite(path, image)
        self.log("SYSTEM", f"📸 Debug-Bild gespeichert: {name}.jpg")

    def apply_crop(self, frame, side):
        if frame is None: return None
        h, w = frame.shape[:2]
        self.raw_dims[side] = (h, w)
        sec = 'Crop_Links' if side == 'left' else 'Crop_Rechts'
        top = self.config.getint(sec, 'cut_top')
        bottom = self.config.getint(sec, 'cut_bottom')
        left = self.config.getint(sec, 'cut_left')
        right = self.config.getint(sec, 'cut_right')
        self.current_crops[side] = (top, bottom, left, right)
        y1 = max(0, top)
        y2 = max(0, h - bottom)
        x1 = max(0, left)
        x2 = max(0, w - right)
        if y1 >= y2 or x1 >= x2: return frame 
        return frame[y1:y2, x1:x2]

    def set_reference_image(self, frame, side):
        bgr_blur = cv2.GaussianBlur(frame, (7, 7), 0)
        if side == 'left':
            self.ref_left = bgr_blur
        else:
            self.ref_right = bgr_blur
        self.save_debug_image(f"referenz_{side}", frame)

    def detect_new_shot(self, frame, side):
        state = self.state_left if side == 'left' else self.state_right
        reference_bgr = self.ref_left if side == 'left' else self.ref_right
        if reference_bgr is None or frame is None: 
            self.log(side, "Fehler: Keine Referenz vorhanden!")
            return False

        # 1. Live-Bild weichzeichnen und Helligkeit an die Referenz angleichen
        current_bgr_blur = cv2.GaussianBlur(frame, (7, 7), 0) 
        current_normalized = self.normalize_brightness(reference_bgr, current_bgr_blur)
        
        # 2. ROHES DIFF-BILD: Neues Bild vs. Eingefrorenes Referenzbild (Weiß = Änderung)
        diff_bgr = cv2.absdiff(reference_bgr, current_normalized) 
        diff_gray = cv2.cvtColor(diff_bgr, cv2.COLOR_BGR2GRAY)
        _, thresh_raw = cv2.threshold(diff_gray, self.hit_tolerance, 255, cv2.THRESH_BINARY) 

        # ---> NEU: Der 4x4 Pixel Closing-Kleber <---
        kernel = np.ones((5, 5), np.uint8)
        thresh_raw = cv2.morphologyEx(thresh_raw, cv2.MORPH_CLOSE, kernel)

        # 3. ALTES DIFF-BILD ABZIEHEN (Mathematische Subtraktion der bekannten Bereiche)
        if state.cumulative_mask is not None:
            # Weißer Bereich im alten Diff zieht weißen Bereich im rohen Diff ab -> wird schwarz (ignoriert)
            thresh_new = cv2.subtract(thresh_raw, state.cumulative_mask)
        else:
            thresh_new = thresh_raw.copy()
            state.cumulative_mask = np.zeros_like(thresh_raw)

        # 4. NOTBREMSE (Sanity Check) prüft JETZT nur noch den echten Neuzuwachs
        changed_pixels = cv2.countNonZero(thresh_new)
        total_pixels = thresh_new.shape[0] * thresh_new.shape[1]
        change_percent = (changed_pixels / total_pixels) * 100
        
        if change_percent > self.max_img_change:
            self.log(side, f"⚠️ SANITY CHECK FEHLGESCHLAGEN: Neuer Zuwachs zu {change_percent:.2f}%")
            self.log(side, "-> Ignoriere Frame.")
            return False 

        # 5. KONTUREN-ANALYSE auf dem bereinigten thresh_new
        contours, _ = cv2.findContours(thresh_new, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        new_shots_found_this_frame = []
        self.log(side, f"Analysiere Konturen... (Neuer Zuwachs: {change_percent:.2f}% | Konturen: {len(contours)})")

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > self.min_hole_area:
                
                # =========================================================
                # VARIANTE A: minEnclosingCircle (Aktuell aktiv für V1.0.0 Test)
                # Legt einen perfekten Kreis um die Form. Zentriert sich besser, 
                # wenn abgerissene Papiersplitter ("Rattenlöcher") das Loch verzerren.
                # =========================================================
                (circle_x, circle_y), radius = cv2.minEnclosingCircle(cnt)
                cx = int(circle_x)
                cy = int(circle_y)

                # =========================================================
                # VARIANTE B: Schwerpunkt / Center of Mass (Auskommentiert)
                # Zieht bei "Rattenlöchern" oft in Richtung des abgerissenen Papiers.
                # =========================================================
                # M = cv2.moments(cnt)
                # if M["m00"] != 0:
                #     cx = int(M["m10"] / M["m00"])
                #     cy = int(M["m01"] / M["m00"])
                # else:
                #     continue # Überspringt ungültige Konturen
                # =========================================================

                is_new = True
                for shot in self.shots:
                    if shot['side'] == side:
                        dist = np.hypot(shot['pos'][0] - cx, shot['pos'][1] - cy)
                        if dist < self.caliber_radius:
                            is_new = False
                            break

                if is_new:
                    new_shots_found_this_frame.append({'side': side, 'pos': (cx, cy), 'is_new': True})
                    # NEU: X/Y-Koordinaten direkt im Log protokollieren für die Feinanalyse
                    self.log(side, f"-> NEUES LOCH GEFUNDEN: Pos ({cx}, {cy}) | Fläche {area:.1f}px")
                
        if new_shots_found_this_frame:
            for shot in self.shots:
                if shot['side'] == side:
                    shot['is_new'] = False
            self.shots.extend(new_shots_found_this_frame)
            
            # Altes Diff-Bild (die Maske) aktualisieren
            state.cumulative_mask = cv2.bitwise_or(state.cumulative_mask, thresh_raw)
            
            # --- NEU: Gesamtes Diff-Bild (Gedächtnis) als Debug-Bild ausgeben ---
            self.save_debug_image(f"diff_gesamt_{side}", state.cumulative_mask)
            
            self.log(side, f"🎯 {len(new_shots_found_this_frame)} neue(r) Treffer bestätigt!")
            self.save_debug_image(f"diff_letzter_treffer_{side}", thresh_new)
            self.save_debug_image(f"letzte_aufnahme_{side}", frame)
            return True
        else:
            self.log(side, "Keine validen neuen Treffer im Bild gefunden.")
            return False

    def process_camera(self, frame, state):
        if frame is None: return

        current_ref = self.ref_left if state.side == 'left' else self.ref_right
        if not state.is_initialized:
            bg_visible, bg_percent = state.is_background_visible(frame)
            self.log(state.side, f"STARTUP-CHECK: Hintergrund zu {bg_percent:.1f}% sichtbar.")
            
            if bg_visible:
                self.log(state.side, "Status: Keine Scheibe vorhanden (Warte auf Einfahren).")
                state.target_present = False
            else:
                self.log(state.side, "Status: Scheibe direkt im Bild erkannt! Speichere Initial-Referenz.")
                state.target_present = True
                self.set_reference_image(frame, state.side)
            state.is_initialized = True
            return

        has_motion = state.check_motion(frame)

        if has_motion:
            if not state.is_moving:
                self.log(state.side, "Bewegung (Erschütterung/Fahrt) gestartet.")
            state.is_moving = True
            state.still_counter = 0
        else:
            if state.is_moving:
                state.still_counter += 1
                if state.still_counter >= state.stillness_limit:
                    state.is_moving = False
                    self.log(state.side, "Bewegung beendet (Bild stabil).")
                    
                    # Hintergrund-Automatik ist immer aktiv
                    bg_visible, bg_percent = state.is_background_visible(frame)
                    
                    # Berechnet, wie knapp es war
                    diff = bg_percent - state.min_area 
                    
                    if bg_visible:
                        self.log(state.side, f"Hintergrund-Analyse: {bg_percent:.1f}% -> WAND (+{diff:.1f}% über Limit {state.min_area}%)")
                        if state.target_present:
                            self.log(state.side, "ZIELSCHEIBE VERLASSEN. (Pausiert)")
                            state.target_present = False
                    else:
                        self.log(state.side, f"Hintergrund-Analyse: {bg_percent:.1f}% -> SCHEIBE ({abs(diff):.1f}% unter Limit {state.min_area}%)")
                        if not state.target_present:
                            state.target_present = True
                            if current_ref is None:
                                self.set_reference_image(frame, state.side)
                            else:
                                self.detect_new_shot(frame, state.side) # KEIN REFERENZ-UPDATE!
                        else:
                            self.detect_new_shot(frame, state.side) # KEIN REFERENZ-UPDATE!

    # =========================================================================
    # HILFSFUNKTIONEN (Clean Code)
    # =========================================================================

    def normalize_brightness(self, ref, live):
        mean_ref = cv2.mean(ref)[:3]
        mean_live = cv2.mean(live)[:3]
        diff = np.array(mean_ref) - np.array(mean_live)
        live_float = live.astype(np.float32)
        live_float += diff
        return np.clip(live_float, 0, 255).astype(np.uint8)

    def enhance_color_for_display(self, frame):
        # Wandelt das Bild in den HSV-Farbraum um (Hue, Saturation, Value)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
        
        # Sättigung (Kanal 1) um 50% erhöhen -> aus "staubig" wird "leuchtend"
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.5, 0, 255) 
        # Helligkeit (Kanal 2) leicht um 10% anheben
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.1, 0, 255) 
        
        # HIER WAR DER FEHLER: Es muss cv2.COLOR_HSV2BGR heißen
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    def read_frames(self):
        frame_l, frame_r = None, None
        if self.use_left: 
            ret_l, raw_l = self.cap_left.read()
            frame_l = self.apply_crop(raw_l, 'left') if ret_l else None
        if self.use_right: 
            ret_r, raw_r = self.cap_right.read()
            frame_r = self.apply_crop(raw_r, 'right') if ret_r else None
        return frame_l, frame_r

    def execute_manual_reset(self, side, frame):
        self.shots = [s for s in self.shots if s['side'] != side]
        state = self.state_left if side == 'left' else self.state_right
        
        # Altes Diff-Bild beim Reset leeren
        state.cumulative_mask = None
        
        if frame is not None:
            self.set_reference_image(frame, side)
            state.target_present = True
            # HIER WAR DER FEHLER: state.auto_background = False wurde entfernt!
            
        self.log(side, "MANUELLER RESET: Referenz gelockt (Pausenerkennung bleibt AKTIV).")

    def process_resets(self, frame_l, frame_r):
        if self.trigger_reset_left:
            self.execute_manual_reset('left', frame_l)
            self.trigger_reset_left = False
        if self.trigger_reset_right:
            self.execute_manual_reset('right', frame_r)
            self.trigger_reset_right = False

    def draw_camera_overlay(self, view, side, start_x, frame_w, total_h):
        cv2.rectangle(view, (start_x, total_h - 40), (start_x + frame_w, total_h), (30, 30, 30), -1)
        msg = self.msg_left if side == 'left' else self.msg_right
        cv2.putText(view, msg, (start_x + 10, total_h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA)
        
        bx1, by1 = start_x + frame_w - 110, total_h - 35
        bx2, by2 = start_x + frame_w - 10, total_h - 5
        cv2.rectangle(view, (bx1, by1), (bx2, by2), (70, 70, 180), -1)
        cv2.rectangle(view, (bx1, by1), (bx2, by2), (255, 255, 255), 1)
        cv2.putText(view, "Reset", (bx1 + 25, by1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        
        if side == 'left':
            self.btn_left_coords = (bx1, by1, bx2, by2)
        else:
            self.btn_right_coords = (bx1, by1, bx2, by2)

    def update_gui(self, frame_l, frame_r, blink_state):
        frames_to_stack = []
        
        # --- NEU: Optische Aufhübschung für die Anzeige ---
        # Wenn der Schalter in der INI auf 'yes' steht, pushen wir die Farben für das GUI
        disp_l = self.enhance_color_for_display(frame_l) if (self.use_left and frame_l is not None and self.enhance_display) else frame_l
        disp_r = self.enhance_color_for_display(frame_r) if (self.use_right and frame_r is not None and self.enhance_display) else frame_r
        
        # Wir legen jetzt die aufbereiteten Bilder (disp_l, disp_r) in den Stapel für die Anzeige
        if self.use_left and disp_l is not None: frames_to_stack.append(disp_l)
        if self.use_right and disp_r is not None: frames_to_stack.append(disp_r)

        if not frames_to_stack: return

        max_h = max([f.shape[0] for f in frames_to_stack])
        padded_frames = []
        for f in frames_to_stack:
            h, w = f.shape[:2]
            if h < max_h:
                pad = np.zeros((max_h, w, 3), dtype=np.uint8)
                pad[0:h, 0:w] = f
                padded_frames.append(pad)
            else:
                padded_frames.append(f)
                
        combined_view = np.hstack(padded_frames)
        orig_h, orig_w = combined_view.shape[:2]
        self.w_left_displayed = frames_to_stack[0].shape[1] if (self.use_left and frame_l is not None) else 0
        
        self.scale_x, self.scale_y = 1.0, 1.0
        try:
            rect = cv2.getWindowImageRect(self.window_name)
            if rect[2] > 0 and rect[3] > 0:
                win_w, win_h = rect[2], rect[3]
                combined_view = cv2.resize(combined_view, (win_w, win_h))
                self.scale_x = win_w / orig_w
                self.scale_y = win_h / orig_h
            else:
                win_w, win_h = orig_w, orig_h
        except Exception:
            win_w, win_h = orig_w, orig_h
            
        avg_scale = (self.scale_x + self.scale_y) / 2
        final_radius = max(2, int(self.caliber_radius * avg_scale))
        
        for shot in self.shots:
            x, y = shot['pos']
            if shot['side'] == 'right' and self.use_left and frame_l is not None:
                x += self.w_left_displayed
                
            final_x = int(x * self.scale_x)
            final_y = int(y * self.scale_y)
            
            color = (0, 0, 255) if (shot.get('is_new', False) and blink_state) else (255, 100, 0)
            cv2.circle(combined_view, (final_x, final_y), final_radius, color, 2)
            cv2.circle(combined_view, (final_x, final_y), max(1, int(2*avg_scale)), color, -1)

        scaled_w_left = int(self.w_left_displayed * self.scale_x)
        
        if self.use_left and frame_l is not None:
            self.draw_camera_overlay(combined_view, 'left', 0, scaled_w_left, win_h)
        if self.use_right and frame_r is not None:
            self.draw_camera_overlay(combined_view, 'right', scaled_w_left, win_w - scaled_w_left, win_h)
        
        ex1, ey1 = win_w - 110, 10
        ex2, ey2 = win_w - 10, 40
        cv2.rectangle(combined_view, (ex1, ey1), (ex2, ey2), (60, 60, 60), -1) 
        cv2.rectangle(combined_view, (ex1, ey1), (ex2, ey2), (255, 255, 255), 1) 
        cv2.putText(combined_view, "Beenden", (ex1 + 18, ey1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        self.btn_exit_coords = (ex1, ey1, ex2, ey2)

        cv2.imshow(self.window_name, combined_view)

    def check_keys(self):
        key = cv2.waitKey(self.poll_ms) & 0xFF
        
        if getattr(self, 'trigger_exit', False):
            return True
            
        try:
            if cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1:
                return True 
        except cv2.error:
            return True 

        if key == ord('q'): 
            return True
        elif key == ord('r'):
            if self.use_left: self.trigger_reset_left = True
            if self.use_right: self.trigger_reset_right = True
            
        return False

    def cleanup(self):
        if self.use_left: self.cap_left.release()
        if self.use_right: self.cap_right.release()
        cv2.destroyAllWindows()

    def on_mouse_click(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            if getattr(self, 'btn_exit_coords', None):
                ex1, ey1, ex2, ey2 = self.btn_exit_coords
                if ex1 <= x <= ex2 and ey1 <= y <= ey2:
                    self.trigger_exit = True
                    return
            
            if self.use_left and getattr(self, 'btn_left_coords', None):
                bx1, by1, bx2, by2 = self.btn_left_coords
                if bx1 <= x <= bx2 and by1 <= y <= by2:
                    self.trigger_reset_left = True
                    return
            
            if self.use_right and getattr(self, 'btn_right_coords', None):
                bx1, by1, bx2, by2 = self.btn_right_coords
                if bx1 <= x <= bx2 and by1 <= y <= by2:
                    self.trigger_reset_right = True
                    return

            orig_x = int(x / self.scale_x)
            orig_y = int(y / self.scale_y)

    def run(self):
        blink_timer = time.time()
        blink_state = True
        
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        
        if self.fullscreen:
            cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        else:
            cv2.resizeWindow(self.window_name, 1280, 720) 
            
        cv2.setMouseCallback(self.window_name, self.on_mouse_click)
        self.log("SYSTEM", "=== PROGRAMM GESTARTET ===")

        while True:
            frame_l, frame_r = self.read_frames()
            self.process_resets(frame_l, frame_r)

            if self.use_left: self.process_camera(frame_l, self.state_left)
            if self.use_right: self.process_camera(frame_r, self.state_right)

            if time.time() - blink_timer > 0.3:
                blink_state = not blink_state
                blink_timer = time.time()

            self.update_gui(frame_l, frame_r, blink_state)

            if self.check_keys():
                break

        self.cleanup()

if __name__ == "__main__":
    config = load_or_create_config()
    tracker = TargetTracker(config)
    tracker.run()