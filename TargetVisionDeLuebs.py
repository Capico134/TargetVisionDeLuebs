import cv2
import numpy as np
import time
import subprocess
import os
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

# --- NEU: Unsere sauberen Manager-Importe ---
from DateiManagerDeLuebs import DateiManager
from StateManagerDeLuebs import StateManager
from DetectionDeLuebs import TargetDetector  # <--- HIER ZIEHT DER NEUE DETECTOR EIN!

class TargetTracker:
    def __init__(self, config, datei_manager, state_manager):
        self.config = config
        self.dm = datei_manager
        self.sm = state_manager
        
        self.version = self.dm.get_current_version()
        print(f"🎯 TargetVision DeLübs     [v{self.version}]")
        self.window_name = f"TargetVision DeLuebs - v{self.version}"
        
        self.use_left = config.getboolean('Kameras', 'nutze_kamera_links')
        self.use_right = config.getboolean('Kameras', 'nutze_kamera_rechts')
        
        # --- Nur noch Variablen, die wir explizit für die GUI/Steuerung brauchen ---
        self.caliber_radius = config.getint('Erkennung', 'caliber_radius')
        self.ausloeser_erschuetterung = config.getboolean('Erkennung', 'ausloeser_durch_erschuetterung', fallback=False)
        self.poll_ms = config.getint('Timing', 'poll_ms', fallback=33)
        self.fullscreen = config.getboolean('Anzeige', 'vollbild', fallback=False)
        self.enhance_display = config.getboolean('Anzeige', 'darstellung_ohne_weissabgleich', fallback=True)
        self.ringwertung_aktiv = config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
        
        # ---> NEU: Wir instanziieren den Detector und übergeben unsere log-Funktion als Callback! <---
        self.detector = TargetDetector(config, datei_manager, state_manager, self.log)
        
        slowstart = False
        if slowstart:
            self.cap_left = cv2.VideoCapture(config.getint('Kameras', 'cam_left_index')) if self.use_left else None
            self.cap_right = cv2.VideoCapture(config.getint('Kameras', 'cam_right_index')) if self.use_right else None
        else:
            cam_left_idx = config.getint('Kameras', 'cam_left_index')
            cam_right_idx = config.getint('Kameras', 'cam_right_index')
            self.cap_left = cv2.VideoCapture(cam_left_idx, cv2.CAP_DSHOW) if self.use_left else None
            self.cap_right = cv2.VideoCapture(cam_right_idx, cv2.CAP_DSHOW) if self.use_right else None

        self.state_left = self.sm.state_left
        self.state_right = self.sm.state_right
        
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
        self.btn_highscore_coords = None
        self.btn_save_coords = None
        
        self.trigger_reset_left = False
        self.trigger_reset_right = False
        self.trigger_exit = False
        
    def log(self, side, text):
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        log_msg = f"[{timestamp}] [{side.upper()}] {text}"
        
        print(log_msg)
        self.dm.write_log(log_msg)
            
        gui_text = text if len(text) <= 45 else text[:42] + "..."
        if side == 'left' or side == 'SYSTEM':
            self.msg_left = gui_text
        if side == 'right' or side == 'SYSTEM':
            self.msg_right = gui_text

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

    def process_camera(self, frame, state):
        if frame is None: return

        if not state.is_initialized:
            bg_visible, bg_percent = state.is_background_visible(frame)
            self.log(state.side, f"STARTUP-CHECK: Hintergrund zu {bg_percent:.1f}% sichtbar.")
            
            if bg_visible:
                self.log(state.side, "Status: Keine Scheibe vorhanden (Warte auf Einfahren).")
                state.target_present = False
            else:
                self.log(state.side, "Status: Scheibe direkt im Bild erkannt! Speichere Initial-Referenz.")
                state.target_present = True
                self.detector.set_reference_image(frame, state.side) # <--- Delegiert an den Detector!
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
                        self.detector.check_background_and_evaluate(frame, state) # <--- Delegiert an den Detector!
        else:
            current_time = time.time()
            if current_time - state.last_scan_time > 1.5:
                state.last_scan_time = current_time
                self.detector.check_background_and_evaluate(frame, state) # <--- Delegiert an den Detector!

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
        self.sm.reset_match(side)
        
        if hasattr(self.dm, 'clear_debug_images'):
            self.dm.clear_debug_images(side)
        
        state = self.state_left if side == 'left' else self.state_right
        
        # ---> NEU: Wir merken uns, dass dieses Match auf einer sauberen Scheibe beginnt
        state.is_fortsetzung = False 
        
        if frame is not None:
            self.detector.set_reference_image(frame, side) 
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
        
        ref_h, ref_w = 480, 640
        if disp_l is not None: ref_h, ref_w = disp_l.shape[:2]
        elif disp_r is not None: ref_h, ref_w = disp_r.shape[:2]

        def create_dummy_frame(side_name):
            dummy = np.zeros((ref_h, ref_w, 3), dtype=np.uint8)
            text = f"KAMERA GETRENNT ({side_name})"
            cv2.putText(dummy, text, (30, ref_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)
            return dummy

        if self.use_left:
            frames_to_stack.append(disp_l if disp_l is not None else create_dummy_frame("LINKS"))
        
        if self.use_right:
            frames_to_stack.append(disp_r if disp_r is not None else create_dummy_frame("RECHTS"))

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
        
        self.w_left_displayed = frames_to_stack[0].shape[1] if self.use_left else 0
        
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
        
        # ---> GEÄNDERT: TREFFER ZEICHNEN (Nach Seite getrennt, Nummer mittig im Kreis) <---
        for side in ['left', 'right']:
            side_shots = self.sm.get_shots_for_side(side)
            for idx, shot in enumerate(side_shots):
                x, y = shot['pos']
                
                if shot['side'] == 'right' and self.use_left:
                    x += self.w_left_displayed
                    
                final_x = int(x * self.scale_x)
                final_y = int(y * self.scale_y)
                
                color = (0, 0, 255) if (shot.get('is_new', False) and blink_state) else (255, 100, 0)
                
                # Zuerst den Kreis und den Mittelpunkt malen
                cv2.circle(combined_view, (final_x, final_y), final_radius, color, 2)
                cv2.circle(combined_view, (final_x, final_y), max(1, int(2*avg_scale)), color, -1)
                
                # Dann die Treffer-Nummer absolut mittig darüberlegen
                if getattr(self, 'ringwertung_aktiv', False):
                    id_str = str(idx + 1)
                    
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.5
                    thickness = 1
                    
                    # Berechnet die Pixelbreite/-höhe des Textes, um ihn mathematisch zu zentrieren
                    (text_w, text_h), _ = cv2.getTextSize(id_str, font, font_scale, thickness)
                    text_x = final_x - (text_w // 2)
                    text_y = final_y + (text_h // 2)
                    
                    # Schwarzer Schatten-Rand für perfekte Lesbarkeit
                    cv2.putText(combined_view, id_str, (text_x, text_y), font, font_scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
                    # Weiße oder leicht blaue Schrift
                    text_color = (255, 255, 255) if not shot.get('is_new', False) else (200, 200, 255)
                    cv2.putText(combined_view, id_str, (text_x, text_y), font, font_scale, text_color, thickness, cv2.LINE_AA)

        scaled_w_left = int(self.w_left_displayed * self.scale_x)
        
        if self.use_left:
            self.draw_camera_overlay(combined_view, 'left', 0, scaled_w_left, win_h)
        if self.use_right:
            self.draw_camera_overlay(combined_view, 'right', scaled_w_left, win_w - scaled_w_left, win_h)
        
        # --- VISUELLES FEEDBACK ---
        current_time = time.time()
        for s, feedback in [('left', getattr(self.detector, 'calib_feedback_left', None)), 
                            ('right', getattr(self.detector, 'calib_feedback_right', None))]:
            if feedback and (current_time - feedback['time'] < 8.0):
                use_cam = self.use_left if s == 'left' else self.use_right
                if use_cam:
                    offset_x = 0 if s == 'left' else scaled_w_left
                    
                    fb_cx = int(feedback['cx'] * self.scale_x) + offset_x
                    fb_cy = int(feedback['cy'] * self.scale_y)
                    fb_ideal_rx = int(feedback['ideal_rx'] * self.scale_x)
                    fb_ideal_ry = int(feedback['ideal_ry'] * self.scale_y)
                    fb_red_cx = int(feedback['red_cx'] * self.scale_x) + offset_x
                    fb_red_cy = int(feedback['red_cy'] * self.scale_y)
                    fb_red_rx = int(feedback['red_rx'] * self.scale_x)
                    fb_red_ry = int(feedback['red_ry'] * self.scale_y)

                    if feedback['show_red']:
                        cv2.ellipse(combined_view, (fb_red_cx, fb_red_cy), (fb_red_rx, fb_red_ry), 0, 0, 360, (0, 0, 255), 1, cv2.LINE_AA)
                    
                    cv2.ellipse(combined_view, (fb_cx, fb_cy), (fb_ideal_rx, fb_ideal_ry), 0, 0, 360, (0, 255, 0), 2, cv2.LINE_AA)
        
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
        
        # Highscore Button
        hx1, hy1 = win_w - 560, 10
        hx2, hy2 = win_w - 420, 40
        cv2.rectangle(combined_view, (hx1, hy1), (hx2, hy2), (50, 150, 200), -1) 
        cv2.rectangle(combined_view, (hx1, hy1), (hx2, hy2), (255, 255, 255), 1) 
        cv2.putText(combined_view, "Highscore", (hx1 + 30, hy1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        self.btn_highscore_coords = (hx1, hy1, hx2, hy2)
        
        # Match Speichern Button
        sx1, sy1 = win_w - 410, 10
        sx2, sy2 = win_w - 240, 40
        cv2.rectangle(combined_view, (sx1, sy1), (sx2, sy2), (180, 70, 70), -1) 
        cv2.rectangle(combined_view, (sx1, sy1), (sx2, sy2), (255, 255, 255), 1) 
        cv2.putText(combined_view, "Match Speichern", (sx1 + 15, sy1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        self.btn_save_coords = (sx1, sy1, sx2, sy2)
        
        # ---> GEÄNDERT: HUD / Trefferliste (Getrennt für beide Seiten) <---
        if getattr(self, 'ringwertung_aktiv', False):
            start_y = 80  
            line_h = 25   
            max_items = max(5, (win_h - start_y - 80) // line_h)
            box_w = 110  

            for side in ['left', 'right']:
                side_shots = self.sm.get_shots_for_side(side)
                if not side_shots: 
                    continue # Wenn diese Scheibe noch leer ist, kein HUD zeichnen!
                    
                # Geister-HUDs verhindern, falls eine Kamera physisch aus ist
                if side == 'left' and not self.use_left: continue
                if side == 'right' and not self.use_right: continue

                display_shots = side_shots[-max_items:] if len(side_shots) > max_items else side_shots
                start_idx = len(side_shots) - len(display_shots)
                
                # Links dockt links an, rechts dockt rechts an!
                if side == 'left':
                    #box_x = 10 #ALT HIER LINKS 
                    box_x = max(10, scaled_w_left - box_w - 10)
                else:
                    box_x = win_w - box_w - 10
                    
                box_h = (len(display_shots) + 2) * line_h
                
                hud_overlay = combined_view.copy()
                cv2.rectangle(hud_overlay, (box_x - 10, start_y - 25), (box_x + box_w, start_y + box_h), (20, 20, 20), -1)
                cv2.addWeighted(hud_overlay, 0.4, combined_view, 0.6, 0, combined_view)
                
                titel = "Treffer (L)" if side == 'left' else "Treffer (R)"
                cv2.putText(combined_view, titel, (box_x - 5, start_y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.line(combined_view, (box_x - 5, start_y - 2), (box_x + box_w - 5, start_y - 2), (100, 100, 100), 1)
                
                for i, shot in enumerate(display_shots):
                    shot_num = start_idx + i + 1
                    score_val = shot.get('score', 0.0)
                    text_color = (0, 255, 255) if score_val < 10.0 else (0, 255, 0)
                    text = f" {shot_num}:"
                    score_str = f"{score_val:.1f}"
                    y_pos = start_y + 20 + (i * line_h)
                    
                    cv2.putText(combined_view, text, (box_x - 5, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
                    cv2.putText(combined_view, score_str, (box_x + 50, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.55, text_color, 1, cv2.LINE_AA)

                cv2.line(combined_view, (box_x - 5, start_y + 8 + len(display_shots) * line_h), (box_x + box_w - 5, start_y + 8 + len(display_shots) * line_h), (100, 100, 100), 1)
                gesamt = sum(s.get('score', 0.0) for s in side_shots)
                gesamt_text = "Ges.:"
                gesamt_val = f"{gesamt:.1f}"
                y_sum = start_y + 28 + len(display_shots) * line_h
                
                cv2.putText(combined_view, gesamt_text, (box_x - 5, y_sum), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(combined_view, gesamt_val, (box_x + 45, y_sum), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (50, 200, 255), 2, cv2.LINE_AA)

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

        if key == ord('q'): return True
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
            # Beenden Button
            if getattr(self, 'btn_exit_coords', None):
                ex1, ey1, ex2, ey2 = self.btn_exit_coords
                if ex1 <= x <= ex2 and ey1 <= y <= ey2:
                    self.trigger_exit = True
                    return
            
            # Bug ZIP Button
            if getattr(self, 'btn_zip_coords', None):
                zx1, zy1, zx2, zy2 = self.btn_zip_coords
                if zx1 <= x <= zx2 and zy1 <= y <= zy2:
                    self.log("SYSTEM", "Generiere Debug-Paket... Bitte warten.")
                    self.dm.create_debug_zip()
                    self.log("SYSTEM", "Debug-ZIP wurde erfolgreich gespeichert!")
                    return
            
            # Reset Button (Links)
            if self.use_left and getattr(self, 'btn_left_coords', None):
                bx1, by1, bx2, by2 = self.btn_left_coords
                if bx1 <= x <= bx2 and by1 <= y <= by2:
                    self.trigger_reset_left = True
                    return
            
            # Reset Button (Rechts)
            if self.use_right and getattr(self, 'btn_right_coords', None):
                bx1, by1, bx2, by2 = self.btn_right_coords
                if bx1 <= x <= bx2 and by1 <= y <= by2:
                    self.trigger_reset_right = True
                    return
            
            # Highscore Button
            if getattr(self, 'btn_highscore_coords', None):
                hx1, hy1, hx2, hy2 = self.btn_highscore_coords
                if hx1 <= x <= hx2 and hy1 <= y <= hy2:
                    self.log("SYSTEM", "Öffne Highscore-Tabelle...")
                    subprocess.Popen(["python", "HighscoreViewDeLuebs.py"])
                    return
                        
            # Match Speichern Button (mit Single/Multiplayer Logik)
            if getattr(self, 'btn_save_coords', None):
                sx1, sy1, sx2, sy2 = self.btn_save_coords
                if sx1 <= x <= sx2 and sy1 <= y <= sy2:
                    self.log("SYSTEM", "Frage nach Spielername...")
                    
                    player_counts = {}
                    for entry in self.sm.hm.data:
                        # Auch geteilte Namen wie "Jan / Vater" wieder für die Vorschlagsliste trennen
                        names = entry.get("spieler", "Unbekannt").split(" / ")
                        for p in names:
                            p = p.strip()
                            player_counts[p] = player_counts.get(p, 0) + 1
                    
                    sorted_players = sorted(player_counts.keys(), key=lambda x: player_counts[x], reverse=True)
                    if not sorted_players: sorted_players = ["Schütze 1"]
                        
                    default_name_l = getattr(self, 'last_player_name_l', sorted_players[0])
                    default_name_r = getattr(self, 'last_player_name_r', "")
                    
                    root_dialog = tk.Tk()
                    root_dialog.withdraw()
                    
                    dialog = tk.Toplevel(root_dialog)
                    dialog.title("Match Speichern")
                    dialog.geometry("400x260")
                    dialog.attributes('-topmost', True)
                    
                    tk.Label(dialog, text="Wer hat geschossen?\n(Name aus Liste wählen oder tippen)", font=('Arial', 11)).pack(pady=(10, 5))
                    
                    tk.Label(dialog, text="Spieler 1 (Links oder Allein):", font=('Arial', 10, 'bold')).pack()
                    name_var_l = tk.StringVar(value=default_name_l)
                    combo_l = ttk.Combobox(dialog, textvariable=name_var_l, values=sorted_players, font=('Arial', 12))
                    combo_l.pack(pady=(0, 10), padx=30, fill='x')
                    combo_l.focus_set()
                    
                    tk.Label(dialog, text="Spieler 2 (Rechts - Optional):", font=('Arial', 10, 'bold')).pack()
                    name_var_r = tk.StringVar(value=default_name_r)
                    combo_r = ttk.Combobox(dialog, textvariable=name_var_r, values=[""] + sorted_players, font=('Arial', 12))
                    combo_r.pack(pady=(0, 10), padx=30, fill='x')
                    
                    result = [None, None]
                    
                    def on_ok(e=None):
                        result[0] = name_var_l.get().strip()
                        result[1] = name_var_r.get().strip()
                        dialog.destroy()
                        
                    def on_cancel(e=None):
                        dialog.destroy()
                        
                    btn_frame = tk.Frame(dialog)
                    btn_frame.pack(pady=5)
                    tk.Button(btn_frame, text="Speichern", command=on_ok, font=('Arial', 11), bg='#4CAF50', fg='white', width=12).pack(side=tk.LEFT, padx=10)
                    tk.Button(btn_frame, text="Abbrechen", command=on_cancel, font=('Arial', 11), width=12).pack(side=tk.LEFT, padx=10)
                    
                    dialog.bind('<Return>', on_ok)
                    dialog.bind('<Escape>', on_cancel)
                    
                    root_dialog.wait_window(dialog)
                    player_name_l = result[0]
                    player_name_r = result[1]
                    root_dialog.destroy()
                    
                    # Einzelspieler-Logik
                    # Wenn das rechte Feld leer gelassen wurde, setzen wir beide auf Spieler 1.
                    if player_name_l and not player_name_r:
                        player_name_r = player_name_l
                    
                    if player_name_l and player_name_r:
                        self.last_player_name_l = player_name_l
                        # Wir merken uns das leere Feld fürs nächste Mal, falls es ein Einzelspieler war
                        self.last_player_name_r = player_name_r if player_name_l != player_name_r else ""
                        
                        log_msg = f"Speichere Match für {player_name_l} / {player_name_r}..." if player_name_l != player_name_r else f"Speichere Match für {player_name_l}..."
                        self.log("SYSTEM", log_msg)
                        
                        backup_mask_l = self.state_left.cumulative_mask.copy() if (self.use_left and self.state_left and self.state_left.cumulative_mask is not None) else None
                        backup_mask_r = self.state_right.cumulative_mask.copy() if (self.use_right and self.state_right and self.state_right.cumulative_mask is not None) else None
                        
                        if self.sm.save_current_match(player_name_l, player_name_r):
                            self.log("SYSTEM", "Match erfolgreich gespeichert!")
                            
                            # 1. Den Ordner fegen (löscht alle Schüsse/Diffs des alten Matches)
                            if self.use_left: self.dm.clear_debug_images('left', keep_startmask=True)
                            if self.use_right: self.dm.clear_debug_images('right', keep_startmask=True)
                            
                            # 2. Die Masken wiederherstellen UND speichern
                            if self.use_left and self.state_left:
                                self.state_left.cumulative_mask = backup_mask_l
                                if backup_mask_l is not None:
                                    self.dm.save_debug_image("cumulative_startmask_left", backup_mask_l)
                                    self.state_left.is_fortsetzung = True  # Flag für JSON setzen
                                    
                            if self.use_right and self.state_right:
                                self.state_right.cumulative_mask = backup_mask_r
                                if backup_mask_r is not None:
                                    self.dm.save_debug_image("cumulative_startmask_right", backup_mask_r)
                                    self.state_right.is_fortsetzung = True 
                            
                            self.log("SYSTEM", "Leere Kamera-Puffer nach Pause...")
                            for _ in range(10): 
                                if self.use_left: self.cap_left.read()
                                if self.use_right: self.cap_right.read()
                        else:
                            self.log("SYSTEM", "Speichern abgebrochen (Keine Treffer).")
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
    dm = DateiManager()
    config = dm.load_or_create_config()
    sm = StateManager(config, dm)
    
    tracker = TargetTracker(config, dm, sm)
    tracker.run()