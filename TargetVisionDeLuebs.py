import cv2
import numpy as np
import time
import subprocess
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

# --- NEU: Unsere sauberen Manager-Importe ---
from DateiManagerDeLuebs import DateiManager
from StateManagerDeLuebs import StateManager

class TargetTracker:
    def __init__(self, config, datei_manager, state_manager):
        self.config = config
        self.dm = datei_manager
        self.sm = state_manager  # <--- NEU: Der StateManager zieht ein
        
        self.version = self.dm.get_current_version()
        print(f"🎯 TargetVision DeLübs     [v{self.version}]")
        self.window_name = f"TargetVision DeLuebs - v{self.version}"
        
        self.use_left = config.getboolean('Kameras', 'nutze_kamera_links')
        self.use_right = config.getboolean('Kameras', 'nutze_kamera_rechts')
        
        self.min_hole_area = config.getint('Erkennung', 'min_hole_area')
        self.caliber_radius = config.getint('Erkennung', 'caliber_radius')
        self.hit_tolerance = config.getint('Erkennung', 'hit_tolerance', fallback=15)
        self.erkennungs_methode = config.get('Erkennung', 'erkennungs_methode', fallback='C').upper()
        self.hybrid_riss_faktor = config.getfloat('Erkennung', 'hybrid_riss_faktor', fallback=1.5)
        self.ausloeser_erschuetterung = config.getboolean('Erkennung', 'ausloeser_durch_erschuetterung', fallback=False)
        self.max_img_change = config.getfloat('Erkennung', 'max_image_change_percent', fallback=5.0)
        self.poll_ms = config.getint('Timing', 'poll_ms', fallback=33)
        self.fullscreen = config.getboolean('Anzeige', 'vollbild', fallback=False)
        self.enhance_display = config.getboolean('Anzeige', 'darstellung_ohne_weissabgleich', fallback=True)
        
        self.cap_left = cv2.VideoCapture(config.getint('Kameras', 'cam_left_index')) if self.use_left else None
        self.cap_right = cv2.VideoCapture(config.getint('Kameras', 'cam_right_index')) if self.use_right else None

        # --- NEU: Die States kommen jetzt direkt aus dem Manager ---
        self.state_left = self.sm.state_left
        self.state_right = self.sm.state_right

        self.ref_left = None
        self.ref_right = None
        
        # self.shots = [] <--- WURDE GELÖSCHT (Liegt jetzt im StateManager)
        
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
        self.btn_zip_coords = None
        
        self.trigger_reset_left = False
        self.trigger_reset_right = False
        self.trigger_exit = False

    def log(self, side, text):
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        log_msg = f"[{timestamp}] [{side.upper()}] {text}"
        
        print(log_msg)
        self.dm.write_log(log_msg)
            
        gui_text = text if len(text) <= 45 else text[:42] + "..."
        if side == 'left':
            self.msg_left = gui_text
        elif side == 'right':
            self.msg_right = gui_text

    def save_debug_image(self, name, image):
        self.dm.save_debug_image(name, image)
        self.log("SYSTEM", f"📸 Debug-Bild gespeichert: {name}")

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

        current_bgr_blur = cv2.GaussianBlur(frame, (7, 7), 0) 
        current_normalized = self.normalize_brightness(reference_bgr, current_bgr_blur)
        
        diff_bgr = cv2.absdiff(reference_bgr, current_normalized) 
        diff_gray = cv2.cvtColor(diff_bgr, cv2.COLOR_BGR2GRAY)
        _, thresh_raw = cv2.threshold(diff_gray, self.hit_tolerance, 255, cv2.THRESH_BINARY) 

        kernel = np.ones((5, 5), np.uint8)
        thresh_raw = cv2.morphologyEx(thresh_raw, cv2.MORPH_CLOSE, kernel)

        if state.cumulative_mask is not None:
            thresh_new = cv2.subtract(thresh_raw, state.cumulative_mask)
        else:
            thresh_new = thresh_raw.copy()
            state.cumulative_mask = np.zeros_like(thresh_raw)

        changed_pixels = cv2.countNonZero(thresh_new)
        total_pixels = thresh_new.shape[0] * thresh_new.shape[1]
        change_percent = (changed_pixels / total_pixels) * 100
        
        if change_percent > self.max_img_change:
            self.log(side, f"⚠️ SANITY CHECK FEHLGESCHLAGEN: Neuer Zuwachs zu {change_percent:.2f}%")
            self.log(side, "-> Ignoriere Frame.")
            return False 

        contours, _ = cv2.findContours(thresh_new, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        new_shots_found_this_frame = []
        if self.ausloeser_erschuetterung or len(contours) > 0:
            self.log(side, f"Analysiere Konturen... (Neuer Zuwachs: {change_percent:.2f}% | Konturen: {len(contours)})")

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > self.min_hole_area:
               
                if self.erkennungs_methode == 'C':
                    (circle_x, circle_y), radius = cv2.minEnclosingCircle(cnt)
                    # Wenn das gefundene Loch deutlich größer ist als das Kaliber (Riss / Doppelschuss)
                    if radius > (self.caliber_radius * self.hybrid_riss_faktor):  # <--- HIER GEÄNDERT
                        self.log(side, f"🛠️ Unsauberes Loch (Radius: {radius:.1f}px) -> Aktiviere HoughCircles...")
                        mask = np.zeros_like(thresh_new)
                        cv2.drawContours(mask, [cnt], -1, 255, -1)
                        min_r = max(2, int(self.caliber_radius * 0.5))
                        max_r = int(self.caliber_radius * 2.0)
                        circles = cv2.HoughCircles(mask, cv2.HOUGH_GRADIENT, dp=1, minDist=20,
                                                   param1=50, param2=10, 
                                                   minRadius=min_r, maxRadius=max_r)
                        if circles is not None:
                            cx, cy = int(circles[0][0][0]), int(circles[0][0][1])
                            self.log(side, "✅ HoughCircles erfolgreich: Zentrum wurde korrigiert.")
                        else:
                            cx, cy = int(circle_x), int(circle_y)
                            self.log(side, "⚠️ HoughCircles fand keinen Kreis. Fallback auf Standard-Zentrum.")
                    else:
                        cx, cy = int(circle_x), int(circle_y)
                elif self.erkennungs_methode == 'B':
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                    else:
                        continue 
                else:
                    (circle_x, circle_y), _ = cv2.minEnclosingCircle(cnt)
                    cx, cy = int(circle_x), int(circle_y)

                is_new = True
                # --- NEU: Prüfe Distanz jetzt in der Liste des StateManagers ---
                for shot in self.sm.shots:
                    if shot['side'] == side:
                        dist = np.hypot(shot['pos'][0] - cx, shot['pos'][1] - cy)

                if is_new:
                    # Sammeln wir erst, damit sie bei Mehrfachtreffern alle als "neu" gelten
                    new_shots_found_this_frame.append({'cx': cx, 'cy': cy, 'area': area})
                    self.log(side, f"-> NEUES LOCH GEFUNDEN: Pos ({cx}, {cy}) | Fläche {area:.1f}px")
                
        if new_shots_found_this_frame:
            # --- NEU: Wir nutzen jetzt die saubere Funktion des StateManagers! ---
            for sd in new_shots_found_this_frame:
                self.sm.add_shot(side, sd['cx'], sd['cy'], sd['area'])
            
            state.cumulative_mask = cv2.bitwise_or(state.cumulative_mask, thresh_raw)
            self.save_debug_image(f"diff_gesamt_{side}", state.cumulative_mask)
            self.log(side, f"🎯 {len(new_shots_found_this_frame)} neue(r) Treffer bestätigt!")
            self.save_debug_image(f"diff_letzter_treffer_{side}", thresh_new)
            self.save_debug_image(f"letzte_aufnahme_{side}", frame)
            return True
        else:
            if self.ausloeser_erschuetterung:
                self.log(side, "Keine validen neuen Treffer im Bild gefunden.")
            self.save_debug_image(f"diff_letzte_verworfene_auswertung_{side}", thresh_new)
            self.save_debug_image(f"letzte_verworfene_aufnahme_{side}", frame)
            return False

    def check_background_and_evaluate(self, frame, state, current_ref):
        bg_visible, bg_percent = state.is_background_visible(frame)
        diff = bg_percent - state.min_area 
        
        if bg_visible:
            if state.target_present:
                self.log(state.side, f"Hintergrund-Analyse: {bg_percent:.1f}% -> WAND (+{diff:.1f}% über Limit {state.min_area}%)")
                self.log(state.side, "ZIELSCHEIBE VERLASSEN. (Pausiert)")
                state.target_present = False
        else:
            if not state.target_present:
                self.log(state.side, f"Hintergrund-Analyse: {bg_percent:.1f}% -> SCHEIBE ({abs(diff):.1f}% unter Limit {state.min_area}%)")
                state.target_present = True
                if current_ref is None:
                    self.set_reference_image(frame, state.side)
                else:
                    self.detect_new_shot(frame, state.side)
            else:
                self.detect_new_shot(frame, state.side)

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

        if self.ausloeser_erschuetterung:
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
                        self.check_background_and_evaluate(frame, state, current_ref)
        else:
            current_time = time.time()
            if current_time - state.last_scan_time > 1.5:
                state.last_scan_time = current_time
                self.check_background_and_evaluate(frame, state, current_ref)
                
    def normalize_brightness(self, ref, live):
        mean_ref = cv2.mean(ref)[:3]
        mean_live = cv2.mean(live)[:3]
        diff = np.array(mean_ref) - np.array(mean_live)
        live_float = live.astype(np.float32)
        live_float += diff
        return np.clip(live_float, 0, 255).astype(np.uint8)

    def enhance_color_for_display(self, frame):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.5, 0, 255) 
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.1, 0, 255) 
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
        # --- NEU: Reset läuft jetzt blitzsauber über den StateManager ---
        self.sm.reset_match(side)
        
        state = self.state_left if side == 'left' else self.state_right
        if frame is not None:
            self.set_reference_image(frame, side)
            state.target_present = True
            
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
        
        disp_l = self.enhance_color_for_display(frame_l) if (self.use_left and frame_l is not None and self.enhance_display) else frame_l
        disp_r = self.enhance_color_for_display(frame_r) if (self.use_right and frame_r is not None and self.enhance_display) else frame_r
        
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
        
        # --- NEU: Wir iterieren jetzt über die Liste aus dem StateManager ---
        for shot in self.sm.shots:
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
        
        # Beenden Button
        ex1, ey1 = win_w - 110, 10
        ex2, ey2 = win_w - 10, 40
        cv2.rectangle(combined_view, (ex1, ey1), (ex2, ey2), (60, 60, 60), -1) 
        cv2.rectangle(combined_view, (ex1, ey1), (ex2, ey2), (255, 255, 255), 1) 
        cv2.putText(combined_view, "Beenden", (ex1 + 18, ey1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        self.btn_exit_coords = (ex1, ey1, ex2, ey2)

        # Bug ZIP Button
        zx1, zy1 = win_w - 230, 10
        zx2, zy2 = win_w - 120, 40
        cv2.rectangle(combined_view, (zx1, zy1), (zx2, zy2), (40, 120, 40), -1)
        cv2.rectangle(combined_view, (zx1, zy1), (zx2, zy2), (255, 255, 255), 1) 
        cv2.putText(combined_view, "Bug ZIP", (zx1 + 20, zy1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        self.btn_zip_coords = (zx1, zy1, zx2, zy2)
        
        # ---> NEU: Highscore Button (Ganz Links) <---
        hx1, hy1 = win_w - 560, 10
        hx2, hy2 = win_w - 420, 40
        cv2.rectangle(combined_view, (hx1, hy1), (hx2, hy2), (50, 150, 200), -1) # Gold/Gelblich
        cv2.rectangle(combined_view, (hx1, hy1), (hx2, hy2), (255, 255, 255), 1) 
        cv2.putText(combined_view, "Highscore", (hx1 + 30, hy1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        self.btn_highscore_coords = (hx1, hy1, hx2, hy2)
        
        # ---> NEU: Match Speichern Button (Links) <---
        sx1, sy1 = win_w - 410, 10
        sx2, sy2 = win_w - 240, 40
        cv2.rectangle(combined_view, (sx1, sy1), (sx2, sy2), (180, 70, 70), -1) # Blau
        cv2.rectangle(combined_view, (sx1, sy1), (sx2, sy2), (255, 255, 255), 1) 
        cv2.putText(combined_view, "Match Speichern", (sx1 + 15, sy1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        self.btn_save_coords = (sx1, sy1, sx2, sy2)

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
            
            if getattr(self, 'btn_zip_coords', None):
                zx1, zy1, zx2, zy2 = self.btn_zip_coords
                if zx1 <= x <= zx2 and zy1 <= y <= zy2:
                    self.log("SYSTEM", "Generiere Debug-Paket... Bitte warten.")
                    self.dm.create_debug_zip()
                    self.log("SYSTEM", "Debug-ZIP wurde erfolgreich gespeichert!")
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
            
            if getattr(self, 'btn_highscore_coords', None):
                hx1, hy1, hx2, hy2 = self.btn_highscore_coords
                if hx1 <= x <= hx2 and hy1 <= y <= hy2:
                    self.log("SYSTEM", "Öffne Highscore-Tabelle...")
                    # Startet das Tkinter-Fenster als eigenen Prozess
                    subprocess.Popen(["python", "HighscoreViewDeLuebs.py"])
                    return
                        
            if getattr(self, 'btn_save_coords', None):
                sx1, sy1, sx2, sy2 = self.btn_save_coords
                if sx1 <= x <= sx2 and sy1 <= y <= sy2:
                    self.log("SYSTEM", "Frage nach Spielername...")
                    
                    # 1. Spieler-Historie auslesen und zählen (Wer spielt am meisten?)
                    player_counts = {}
                    for entry in self.sm.hm.data:
                        p = entry.get("spieler", "Unbekannt")
                        player_counts[p] = player_counts.get(p, 0) + 1
                    
                    # Sortieren nach Häufigkeit (absteigend) -> Zara steht ganz oben!
                    sorted_players = sorted(player_counts.keys(), key=lambda x: player_counts[x], reverse=True)
                    if not sorted_players:
                        sorted_players = ["Schütze 1"] # Fallback, falls die Highscore noch komplett leer ist
                        
                    # 2. Standardwert bestimmen (Der Letzte, oder der Häufigste)
                    default_name = getattr(self, 'last_player_name', sorted_players[0])
                    
                    # 3. Maßgeschneidertes Pop-up Fenster bauen
                    root_dialog = tk.Tk()
                    root_dialog.withdraw()
                    
                    dialog = tk.Toplevel(root_dialog)
                    dialog.title("Match Speichern")
                    dialog.geometry("380x170")
                    dialog.attributes('-topmost', True) # Bleibt immer im Vordergrund
                    
                    tk.Label(dialog, text="Wer hat geschossen?\n(Name tippen oder aus Liste wählen)", font=('Arial', 11)).pack(pady=10)
                    
                    # Die intelligente Combobox
                    name_var = tk.StringVar(value=default_name)
                    combo = ttk.Combobox(dialog, textvariable=name_var, values=sorted_players, font=('Arial', 12))
                    combo.pack(pady=5, padx=30, fill='x')
                    combo.focus_set() # Cursor direkt ins Feld setzen
                    
                    result = [None] # Speicher für das Ergebnis
                    
                    def on_ok(e=None):
                        result[0] = name_var.get().strip()
                        dialog.destroy()
                        
                    def on_cancel(e=None):
                        dialog.destroy()
                        
                    # Buttons
                    btn_frame = tk.Frame(dialog)
                    btn_frame.pack(pady=10)
                    tk.Button(btn_frame, text="Speichern", command=on_ok, font=('Arial', 11), bg='#4CAF50', fg='white', width=12).pack(side=tk.LEFT, padx=10)
                    tk.Button(btn_frame, text="Abbrechen", command=on_cancel, font=('Arial', 11), width=12).pack(side=tk.LEFT, padx=10)
                    
                    # Tasten-Steuerung (Enter = Speichern, Esc = Abbrechen)
                    dialog.bind('<Return>', on_ok)
                    dialog.bind('<Escape>', on_cancel)
                    
                    # Code wartet hier, bis das kleine Fenster geschlossen wird
                    root_dialog.wait_window(dialog)
                    player_name = result[0]
                    root_dialog.destroy()
                    
                    # 4. Speichern ausführen
                    if player_name:
                        self.last_player_name = player_name
                        self.log("SYSTEM", f"Speichere Match und Highscore für {player_name}...")
                        
                        if self.sm.save_current_match(player_name):
                            self.log("SYSTEM", "Match erfolgreich gespeichert!")
                        else:
                            self.log("SYSTEM", "Speichern abgebrochen (Keine Treffer).")
                            
                            # --- NEU: Warn-Popup für den Schützen ---
                            msg_root = tk.Tk()
                            msg_root.withdraw() # Hauptfenster unsichtbar machen
                            msg_root.attributes('-topmost', True) # Zwingt die Warnung in den Vordergrund
                            messagebox.showwarning(
                                "Speichern abgebrochen", 
                                "Das Match enthält noch keine Treffer!\nEs wurde nichts gespeichert.", 
                                parent=msg_root
                            )
                            msg_root.destroy()
                    else:
                        self.log("SYSTEM", "Speichern vom Benutzer abgebrochen.")
                    return

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
    # --- NEU: Die Drei Musketiere treten an ---
    dm = DateiManager()
    config = dm.load_or_create_config()
    sm = StateManager(config, dm)
    
    tracker = TargetTracker(config, dm, sm)
    tracker.run()