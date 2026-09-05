import platform
import cv2
import numpy as np
import time
import subprocess
import os
import sys #für log-Ausgabe
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

# --- NEU: Unsere sauberen Manager-Importe ---
from DateiManagerDeLuebs import DateiManager
from StateManagerDeLuebs import StateManager
from DetectionDeLuebs import TargetDetector  # <--- HIER ZIEHT DER NEUE DETECTOR EIN!

import LoggerDeLuebs

class TargetTracker:
    def __init__(self, config, datei_manager, state_manager):
        self.config = config
        self.dm = datei_manager
        self.sm = state_manager
        
        self.version = self.dm.get_current_version()
        print(f"🎯 TargetVision DeLübs     [v{self.version}]")
        self.window_name = f"TargetVision DeLuebs - v{self.version}"
        
        # Erkennt automatisch das Betriebssystem ('Windows', 'Linux', 'Darwin' für Mac)
        is_windows = platform.system() == 'Windows'
        self.nutze_kamera_links = config.getboolean('Kameras', 'nutze_kamera_links')
        self.nutze_kamera_rechts = config.getboolean('Kameras', 'nutze_kamera_rechts')
        # ---> NEU: Kameraindizes aus der Config laden <---
        cam_left_idx = config.getint('Kameras', 'cam_left_index')
        cam_right_idx = config.getint('Kameras', 'cam_right_index')

        width_l = config.getint('Kameras', 'cam_width_links', fallback=1280)
        height_l = config.getint('Kameras', 'cam_height_links', fallback=720)
        width_r = config.getint('Kameras', 'cam_width_rechts', fallback=1280)
        height_r = config.getint('Kameras', 'cam_height_rechts', fallback=720)        
        
        # Erkennt automatisch das Betriebssystem ('Windows', 'Linux', 'Darwin' für Mac)
        if is_windows:
            # Unter Windows DirectShow für schnellen Start nutzen
            self.cap_left = cv2.VideoCapture(cam_left_idx, cv2.CAP_DSHOW) if self.nutze_kamera_links else None
            self.cap_right = cv2.VideoCapture(cam_right_idx, cv2.CAP_DSHOW) if self.nutze_kamera_rechts else None
        else:
            # Unter Linux/Mac den nativen Standard-Treiber (V4L2) verwenden
            self.cap_left = cv2.VideoCapture(cam_left_idx) if self.nutze_kamera_links else None
            self.cap_right = cv2.VideoCapture(cam_right_idx) if self.nutze_kamera_rechts else None
        
        # ---> NEU: OpenCV mit den Werten aus der Config zwingen <---
        if self.nutze_kamera_links and self.cap_left:
            self.cap_left.set(cv2.CAP_PROP_FRAME_WIDTH, width_l)
            self.cap_left.set(cv2.CAP_PROP_FRAME_HEIGHT, height_l)
            
        if self.nutze_kamera_rechts and self.cap_right:
            self.cap_right.set(cv2.CAP_PROP_FRAME_WIDTH, width_r)
            self.cap_right.set(cv2.CAP_PROP_FRAME_HEIGHT, height_r)
        
        
        # --- Nur noch Variablen, die wir explizit für die GUI/Steuerung brauchen ---
        #self.caliber_radius = config.getfloat('Erkennung', 'caliber_radius')
        self.ausloeser_durch_erschuetterung = config.getboolean('Erkennung', 'ausloeser_durch_erschuetterung', fallback=False)
        self.poll_ms = config.getint('Timing', 'poll_ms', fallback=33)
        self.vollbild = config.getboolean('Anzeige', 'vollbild', fallback=False)
        self.darstellung_ohne_weissabgleich = config.getboolean('Anzeige', 'darstellung_ohne_weissabgleich', fallback=True)
        self.ringwertung_aktiv = config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
        
        # ---> NEU: Wir instanziieren den Detector und übergeben unsere log-Funktion als Callback! <---
        self.detector = TargetDetector(config, datei_manager, state_manager, self.log)

        #self.state_left = self.sm.state_left
        #self.state_right = self.sm.state_right
        
        self.current_crops = {'left': (0,0,0,0), 'right': (0,0,0,0)}
        self.raw_dims = {'left': (1,1), 'right': (1,1)}
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.w_left_displayed = 0
        self.last_frame_l = None
        self.last_frame_r = None
        
        # ---> NEU: Das Kurzzeitgedächtnis gehört in die GUI! <---
        self.calib_feedback_left = None
        self.calib_feedback_right = None
        
        self.msg_left = "System gestartet. Warte..."
        self.msg_right = "System gestartet. Warte..."
        
        self.btn_left_coords = None
        self.btn_right_coords = None
        self.btn_edit_left_coords = None  # <--- NEU
        self.btn_edit_right_coords = None # <--- NEU
        self.btn_exit_coords = None
        self.btn_zip_coords = None
        self.btn_highscore_coords = None
        self.btn_save_coords = None
        
        self.trigger_reset_left = False
        self.trigger_reset_right = False
        self.trigger_edit_left = False    # <--- NEU
        self.trigger_edit_right = False   # <--- NEU
        self.trigger_exit = False
        self.active_picker = None  # <--- NEU: Speichert, welche Zeile gerade auf einen Klick wartet
        
    # ---> NEU: Der Parameter show_gui=False <---
    def log(self, side, text, show_gui=False):
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        log_msg = f"[{timestamp}] [{side.upper()}] {text}"
        
        #print(log_msg)
        self.dm.write_log(log_msg)
            
        if show_gui:
            # ---> NEU: Filtert alle Emojis (Zeichen mit sehr hohem Unicode-Wert) heraus, 
            # lässt aber normale Buchstaben und deutsche Umlaute (ä, ö, ü) in Ruhe! <---
            gui_text = "".join(c for c in text if ord(c) < 1000).strip()
            
            # Text kürzen, falls zu lang
            gui_text = gui_text if len(gui_text) <= 45 else gui_text[:42] + "..."
            
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
                self.log(state.side, "Status: Scheibe direkt im Bild erkannt! Speichere Initial-Referenz.", True)
                state.target_present = True
                
                # ---> NEU: Rückgabewert fangen und speichern <---
                feedback = self.detector.set_reference_image(frame, state.side)
                if state.side == 'left': self.calib_feedback_left = feedback
                else: self.calib_feedback_right = feedback
                
                self.log(state.side, "-" * 60)
            state.is_initialized = True
            return

        if self.ausloeser_durch_erschuetterung:
            has_motion = state.check_motion(frame)
            if has_motion:
                if not state.is_moving:
                    self.log(state.side, "Bewegung (Erschütterung/Fahrt) gestartet.", True)
                state.is_moving = True
                state.still_counter = 0
            else:
                if state.is_moving:
                    state.still_counter += 1
                    if state.still_counter >= state.stillness_frames:
                        state.is_moving = False
                        self.log(state.side, "Bewegung beendet (Bild stabil).")
                        self.detector.check_background_and_evaluate(frame, state) 
                        self.log(state.side, "-" * 60) # <--- NEU: Block der Frame-Auswertung abschließen
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
        if self.nutze_kamera_links: 
            ret_l, raw_l = self.cap_left.read()
            frame_l = self.apply_crop(raw_l, 'left') if ret_l else None
        if self.nutze_kamera_rechts: 
            ret_r, raw_r = self.cap_right.read()
            frame_r = self.apply_crop(raw_r, 'right') if ret_r else None
        return frame_l, frame_r
    
    def apply_handover(self, zip_path):
        """Liest das Handover-Paket des Labors und injiziert die perfektionierte Historie ins Live-System."""
        package = self.dm.import_match_package(zip_path)
        if not package: return
        
        # 1. Config.ini NEU in den RAM laden und GUI-Variablen updaten
        self.config.read(self.dm.CONFIG_FILE, encoding='utf-8')
        #self.caliber_radius = self.config.getint('Erkennung', 'caliber_radius')
        self.ausloeser_durch_erschuetterung = self.config.getboolean('Erkennung', 'ausloeser_durch_erschuetterung', fallback=False)
        self.ringwertung_aktiv = self.config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
        
        # 2. Alte Referenzbilder aus dem RAM retten (Die Scheibe hat sich ja nicht bewegt)
        # Referenzen wieder einpflanzen und Feedback aktualisieren
        if old_ref_l is not None:
            self.calib_feedback_left = self.detector.set_reference_image(old_ref_l, 'left')
        if old_ref_r is not None:
            self.calib_feedback_right = self.detector.set_reference_image(old_ref_r, 'right')
        
        # 3. Engine neu starten, damit sie die neuen Config-Werte frisst
        self.detector = TargetDetector(self.config, self.dm, self.sm, self.log)
        
        # Referenzen wieder einpflanzen
        if old_ref_l is not None:
            self.detector.set_reference_image(old_ref_l, 'left')
        if old_ref_r is not None:
            self.detector.set_reference_image(old_ref_r, 'right')

        # 4. Alle Bilder aus dem Labor physisch auf die Festplatte legen
        for img_name, img_data in package['images'].items():
            base_name = os.path.basename(img_name)
            clean_name = base_name.replace('.png', '').replace('.jpg', '')
            self.dm.save_debug_image(clean_name, img_data)
            
        # =========================================================================
        # 5. DIE NEUE WAHRHEIT AKZEPTIEREN (JSON & Diff-Gesamt übernehmen!)
        # =========================================================================
        if package['match_data']:
            self.sm.load_match_state(package['match_data'])
            
        for s in ['left', 'right']:
            state = self.sm.state_left if s == 'left' else self.sm.state_right
            if not state: continue
            
            # ---> NEU: Kurzzeitgedächtnis löschen! Verhindert Absturz und macht Crop-Änderungen live-fähig! <---
            state.prev_gray = None
            state.is_moving = False
            state.still_counter = 0
            
            # Das korrigierte Diff-Gesamt aus dem Labor suchen und einpflanzen!
            mask_name = next((f for f in package['images'] if f"diff_gesamt_{s}" in f or f"cumulative_startmask_{s}" in f), None)
            if mask_name:
                mask_bgr = package['images'][mask_name]
                state.cumulative_mask = cv2.cvtColor(mask_bgr, cv2.COLOR_BGR2GRAY)
                # Direkt als Startmaske für den laufenden Prozess sichern
                self.dm.save_debug_image(f"cumulative_startmask_{s}", state.cumulative_mask)
                state.is_fortsetzung = True
    
    def execute_manual_reset(self, side, frame):
        self.sm.reset_match(side)
        
        if hasattr(self.dm, 'clear_debug_images'):
            self.dm.clear_debug_images(side)
        
        state = self.sm.state_left if side == 'left' else self.sm.state_right
        
        # ---> NEU: Wir merken uns, dass dieses Match auf einer sauberen Scheibe beginnt
        state.is_fortsetzung = False 
        
        if frame is not None:
            feedback = self.detector.set_reference_image(frame, side) 
            if side == 'left': self.calib_feedback_left = feedback
            else: self.calib_feedback_right = feedback
            state.target_present = True
            
        self.log(side, "MANUELLER RESET: Referenz gelockt (Pausenerkennung bleibt AKTIV).", True)
        self.log(side, "-" * 60) # <--- NEU: Trenner für Reset-Referenz

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
        
        # ---> NEU: Edit-Button links daneben <---
        ex1, ey1 = start_x + frame_w - 220, total_h - 35
        ex2, ey2 = start_x + frame_w - 120, total_h - 5
        cv2.rectangle(view, (ex1, ey1), (ex2, ey2), (70, 150, 70), -1)
        cv2.rectangle(view, (ex1, ey1), (ex2, ey2), (255, 255, 255), 1)
        cv2.putText(view, "Edit", (ex1 + 35, ey1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        
        if side == 'left':
            self.btn_left_coords = (bx1, by1, bx2, by2)
            self.btn_edit_left_coords = (ex1, ey1, ex2, ey2)  # <--- HIER FEHLTE DIE ZUWEISUNG
        else:
            self.btn_right_coords = (bx1, by1, bx2, by2)
            self.btn_edit_right_coords = (ex1, ey1, ex2, ey2) # <--- UND HIER

    def update_gui(self, frame_l, frame_r, blink_state):
        frames_to_stack = []
        
        disp_l = self.enhance_color_for_display(frame_l) if (self.nutze_kamera_links and frame_l is not None and self.darstellung_ohne_weissabgleich) else frame_l
        disp_r = self.enhance_color_for_display(frame_r) if (self.nutze_kamera_rechts and frame_r is not None and self.darstellung_ohne_weissabgleich) else frame_r
        
        ref_h, ref_w = 480, 640
        if disp_l is not None: ref_h, ref_w = disp_l.shape[:2]
        elif disp_r is not None: ref_h, ref_w = disp_r.shape[:2]

        def create_dummy_frame(side_name):
            dummy = np.zeros((ref_h, ref_w, 3), dtype=np.uint8)
            text = f"KAMERA GETRENNT ({side_name})"
            cv2.putText(dummy, text, (30, ref_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)
            return dummy

        if self.nutze_kamera_links:
            frames_to_stack.append(disp_l if disp_l is not None else create_dummy_frame("LINKS"))
        
        if self.nutze_kamera_rechts:
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
                
        # ... (vorheriger Code bleibt gleich, wo combined_view gebaut wird)
        combined_view = np.hstack(padded_frames)
        orig_h, orig_w = combined_view.shape[:2]
        
        self.w_left_displayed = frames_to_stack[0].shape[1] if self.nutze_kamera_links else 0
        
        self.scale_x, self.scale_y = 1.0, 1.0
        try:
            rect = cv2.getWindowImageRect(self.window_name)
            if rect[2] > 0 and rect[3] > 0:
                win_w, win_h = rect[2], rect[3]
                
                # =========================================================
                # ---> NEU: Proportionale Skalierung (Letterboxing) <---
                # =========================================================
                # Berechne den maximalen Skalierungsfaktor (damit es ins Fenster passt, aber nicht verzerrt)
                scale = min(win_w / orig_w, win_h / orig_h)
                
                # Neue, proportionale Größe berechnen
                new_w = int(orig_w * scale)
                new_h = int(orig_h * scale)
                
                # Das Bild proportional vergrößern
                resized_view = cv2.resize(combined_view, (new_w, new_h))
                
                # Einen schwarzen Hintergrund (Leinwand) in der tatsächlichen Fenstergröße erstellen
                #canvas = np.zeros((win_h, win_w, 3), dtype=np.uint8)
                # Einen dunklen Grauhintergrund (z. B. BGR 40, 40, 40) statt reinem Schwarz erstellen
                canvas = np.full((win_h, win_w, 3), (35, 35, 35), dtype=np.uint8)
                
                # Berechne die Position, um das Bild zu zentrieren (Letterbox-Ränder)
                x_offset = (win_w - new_w) // 2
                y_offset = (win_h - new_h) // 2
                
                # Das vergrößerte Bild auf den schwarzen Hintergrund kleben
                canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized_view
                
                # Die Variable austauschen, damit der Rest des Codes mit der Leinwand weiterarbeitet
                combined_view = canvas
                
                # X und Y Scale sind nun identisch (da proportional) UND wir müssen den Offset speichern!
                self.scale_x = scale
                self.scale_y = scale
                self.pad_x = x_offset # WICHTIG für das Zeichnen von Treffern und Klicks!
                self.pad_y = y_offset
            else:
                win_w, win_h = orig_w, orig_h
                self.pad_x = 0
                self.pad_y = 0
        except Exception:
            win_w, win_h = orig_w, orig_h
            self.pad_x = 0
            self.pad_y = 0
            
        # Den Offset müssen wir im Kopf behalten, da die Skalierung (avg_scale) jetzt proportional ist
        avg_scale = self.scale_x # self.scale_x und _y sind identisch
        #final_radius = max(2, int(self.caliber_radius * avg_scale))
        
        # ---> TREFFER ZEICHNEN (Nach Seite getrennt, Nummer mittig im Kreis) <---
        for side in ['left', 'right']:
            # ---> NEU: Holt sich den perfekten, linsenkorrigierten Radius aus der Engine! <---
            cal_r = self.detector.get_caliber_radius(side)
            final_radius = max(2, int(cal_r * self.scale_x))
            
            side_shots = self.sm.get_shots_for_side(side)
            for idx, shot in enumerate(side_shots):
                x, y = shot['pos']
                
                if shot['side'] == 'right' and self.nutze_kamera_links:
                    x += self.w_left_displayed
                    
                # ---> OFFSET ADDIEIREN! <---
                final_x = int(x * self.scale_x) + self.pad_x
                final_y = int(y * self.scale_y) + self.pad_y
                
                color = (0, 0, 255) if (shot.get('is_new', False) and blink_state) else (255, 100, 0)
                
                # Zuerst den Kreis und den Mittelpunkt malen
                cv2.circle(combined_view, (final_x, final_y), final_radius, color, 1)
                #cv2.circle(combined_view, (final_x, final_y), max(1, int(2*avg_scale)), color, -1)
                
                # Dann die Treffer-Nummer absolut mittig darüberlegen
                if self.ringwertung_aktiv:
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

        # ---> OFFSET ADDIEIREN! <---
        scaled_w_left = int(self.w_left_displayed * self.scale_x)
        
        if self.nutze_kamera_links:
            # Wir rücken es um pad_x ein und nutzen new_h statt win_h, damit die Balken nicht übermalt werden
            new_h = int(orig_h * self.scale_y)
            self.draw_camera_overlay(combined_view, 'left', self.pad_x, scaled_w_left, self.pad_y + new_h)
        if self.nutze_kamera_rechts:
            self.draw_camera_overlay(combined_view, 'right', self.pad_x + scaled_w_left, int((orig_w - self.w_left_displayed) * self.scale_x), self.pad_y + new_h)
        
        # --- VISUELLES FEEDBACK ---
        current_time = time.time()
        # ---> NEU: Wir lesen unsere EIGENEN Variablen! <---
        for s, feedback in [('left', self.calib_feedback_left), 
                            ('right', self.calib_feedback_right)]:
            if feedback and (current_time - feedback['time'] < 8.0):
                use_cam = self.nutze_kamera_links if s == 'left' else self.nutze_kamera_rechts
                if use_cam:
                    offset_x = 0 if s == 'left' else scaled_w_left
                    
                    # ---> NEU: self.pad_x und self.pad_y auf die Zentren addieren! <---
                    fb_cx = int(feedback['cx'] * self.scale_x) + offset_x + getattr(self, 'pad_x', 0)
                    fb_cy = int(feedback['cy'] * self.scale_y) + getattr(self, 'pad_y', 0)
                    
                    fb_ideal_rx = int(feedback['ideal_rx'] * self.scale_x)
                    fb_ideal_ry = int(feedback['ideal_ry'] * self.scale_y)
                    
                    # ---> NEU: Auch beim roten Fehler-Kreis den Offset addieren! <---
                    fb_red_cx = int(feedback['red_cx'] * self.scale_x) + offset_x + getattr(self, 'pad_x', 0)
                    fb_red_cy = int(feedback['red_cy'] * self.scale_y) + getattr(self, 'pad_y', 0)
                    
                    fb_red_rx = int(feedback['red_rx'] * self.scale_x)
                    fb_red_ry = int(feedback['red_ry'] * self.scale_y)

                    if feedback['show_red']:
                        cv2.ellipse(combined_view, (fb_red_cx, fb_red_cy), (fb_red_rx, fb_red_ry), 0, 0, 360, (0, 0, 255), 1, cv2.LINE_AA)
                    
                    cv2.ellipse(combined_view, (fb_cx, fb_cy), (fb_ideal_rx, fb_ideal_ry), 0, 0, 360, (0, 255, 0), 2, cv2.LINE_AA)
        
        # --- BUTTON-LEISTE OBEN RECHTS ---
        gap = 10     # Abstand zwischen den Buttons
        start_y = 10
        
        # Hilfsfunktion für zentrierten Text mit dynamischer Button-Breite
        def draw_button(view, text, right_x, bg_color):
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            thickness = 1
            
            # 1. Textgröße berechnen
            (text_w, text_h), _ = cv2.getTextSize(text, font, font_scale, thickness)
            
            # 2. Button-Breite anpassen (Textbreite + 20 Pixel Puffer)
            btn_w = text_w + 20
            btn_h = 30
            
            # 3. Koordinaten berechnen (Wir zeichnen von rechts nach links)
            x1 = right_x - btn_w
            y1 = start_y
            x2 = right_x
            y2 = start_y + btn_h
            
            # Button Hintergrund und Rand
            cv2.rectangle(view, (x1, y1), (x2, y2), bg_color, -1)
            cv2.rectangle(view, (x1, y1), (x2, y2), (255, 255, 255), 1)
            
            # Text zentrieren
            text_x = x1 + (btn_w - text_w) // 2
            text_y = y1 + (btn_h + text_h) // 2
            
            cv2.putText(view, text, (text_x, text_y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
            
            # Gibt die Klick-Koordinaten zurück UND den neuen X-Startpunkt für den nächsten Button
            return (x1, y1, x2, y2), x1 - gap

        # Startpunkt ganz rechts am Fensterrand
        x_cursor = win_w - 10
        
        # Buttons von rechts nach links aufbauen
        # 1. Beenden (Grau)
        self.btn_exit_coords, x_cursor = draw_button(combined_view, "Beenden", x_cursor, (60, 60, 60))
        
        # ---> NEU: 2. Handbuch (Warmes Blau) <---
        self.btn_hilfe_coords, x_cursor = draw_button(combined_view, "Handbuch", x_cursor, (30, 140, 255))
        
        # 3. Bug ZIP (Grün)
        self.btn_zip_coords, x_cursor = draw_button(combined_view, "Bug ZIP", x_cursor, (40, 120, 40))
        
        # 4. Highscore (Blau)
        self.btn_highscore_coords, x_cursor = draw_button(combined_view, "Highscore", x_cursor, (50, 150, 200))
        
        # 5. Match Speichern (Rot)
        self.btn_save_coords, x_cursor = draw_button(combined_view, "Match Speichern", x_cursor, (180, 70, 70))
        
        # 6. Offline Labor (Lila)
        self.btn_labor_coords, x_cursor = draw_button(combined_view, "Labor & Einstellungen", x_cursor, (150, 50, 150))
        
        
        # ---> HUD / Trefferliste (Getrennt für beide Seiten) <---
        if self.ringwertung_aktiv:
            start_y_hud = 80  
            line_h = 25   
            max_items = max(5, (win_h - start_y_hud - 80) // line_h)
            box_w = 110  

            for side in ['left', 'right']:
                side_shots = self.sm.get_shots_for_side(side)
                if not side_shots: 
                    continue # Wenn diese Scheibe noch leer ist, kein HUD zeichnen!
                    
                # Geister-HUDs verhindern, falls eine Kamera physisch aus ist
                if side == 'left' and not self.nutze_kamera_links: continue
                if side == 'right' and not self.nutze_kamera_rechts: continue

                # ---> NEU: Liste umdrehen und Zählung anpassen <---
                total_shots = len(side_shots)
                display_shots = side_shots[-max_items:] if total_shots > max_items else side_shots
                display_shots_rev = list(reversed(display_shots)) 
                
                # Links dockt links an, rechts dockt rechts an!
                if side == 'left':
                    box_x = max(10, scaled_w_left - box_w - 10)
                else:
                    box_x = win_w - box_w - 10
                    
                box_h = (len(display_shots_rev) + 2) * line_h
                
                hud_overlay = combined_view.copy()
                cv2.rectangle(hud_overlay, (box_x - 10, start_y_hud - 25), (box_x + box_w, start_y_hud + box_h), (20, 20, 20), -1)
                cv2.addWeighted(hud_overlay, 0.4, combined_view, 0.6, 0, combined_view)
                
                titel = "Treffer (L)" if side == 'left' else "Treffer (R)"
                cv2.putText(combined_view, titel, (box_x - 5, start_y_hud - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.line(combined_view, (box_x - 5, start_y_hud - 2), (box_x + box_w - 5, start_y_hud - 2), (100, 100, 100), 1)
                
                # ---> NEU: Die umgedrehte Liste iterieren <---
                for i, shot in enumerate(display_shots_rev):
                    shot_num = total_shots - i  # Zählt jetzt rückwärts (z.B. 17, 16, 15...)
                    score_val = shot.get('score', 0.0)
                    text_color = (0, 255, 255) if score_val < 10.0 else (0, 255, 0)
                    text = f" {shot_num}:"
                    score_str = f"{score_val:.1f}"
                    y_pos = start_y_hud + 20 + (i * line_h)
                    
                    # ---> NEU: Den aktuellsten Schuss als Headliner hervorheben <---
                    if i == 0:
                        f_scale_num = 0.55
                        f_scale_score = 0.65
                        thick = 2
                        color_num = (255, 255, 255) # Leuchtendes reines Weiß
                    else:
                        f_scale_num = 0.5
                        f_scale_score = 0.55
                        thick = 1
                        color_num = (200, 200, 200) # Gedimmtes Grau für die Historie

                    cv2.putText(combined_view, text, (box_x - 5, y_pos), cv2.FONT_HERSHEY_SIMPLEX, f_scale_num, color_num, thick, cv2.LINE_AA)
                    cv2.putText(combined_view, score_str, (box_x + 50, y_pos), cv2.FONT_HERSHEY_SIMPLEX, f_scale_score, text_color, thick, cv2.LINE_AA)
                    
                    # ---> NEU: Dezente Trennlinie unter dem ersten Treffer <---
                    if i == 0 and len(display_shots_rev) > 1:
                        cv2.line(combined_view, (box_x - 5, y_pos + 8), (box_x + box_w - 5, y_pos + 8), (70, 70, 70), 1)

                cv2.line(combined_view, (box_x - 5, start_y_hud + 8 + len(display_shots_rev) * line_h), (box_x + box_w - 5, start_y_hud + 8 + len(display_shots_rev) * line_h), (100, 100, 100), 1)
                gesamt = sum(s.get('score', 0.0) for s in side_shots)
                gesamt_text = "Ges.:"
                gesamt_val = f"{gesamt:.1f}"
                y_sum = start_y_hud + 28 + len(display_shots_rev) * line_h
                
                cv2.putText(combined_view, gesamt_text, (box_x - 5, y_sum), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(combined_view, gesamt_val, (box_x + 45, y_sum), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (50, 200, 255), 2, cv2.LINE_AA)
        cv2.imshow(self.window_name, combined_view)

    def check_keys(self):
        key = cv2.waitKey(self.poll_ms) & 0xFF
        if self.trigger_exit:
            return True
            
        try:
            if cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1:
                return True 
        except cv2.error:
            return True 

        if key == ord('q'): return True
        elif key == ord('r'):
            if self.nutze_kamera_links: self.trigger_reset_left = True
            if self.nutze_kamera_rechts: self.trigger_reset_right = True
            
        return False

    def cleanup(self):
        # ---> NEU: Koch fertig arbeiten lassen vor dem Feierabend <---
        self.dm.flush_image_queue()
        if self.nutze_kamera_links: self.cap_left.release()
        if self.nutze_kamera_rechts: self.cap_right.release()
        cv2.destroyAllWindows()

    def on_mouse_click(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            # ---> NEU: Befinden wir uns im "Pick-Koordinaten"-Modus? <---
            if getattr(self, 'active_picker', None) is not None:
                s = self.active_picker['side']
                
                # ---> OFFSET ABZIEHEN! <---
                raw_x = (x - getattr(self, 'pad_x', 0)) / self.scale_x
                raw_y = (y - getattr(self, 'pad_y', 0)) / self.scale_y
                
                # Wenn wir rechts sind, müssen wir die Breite des linken Bildes abziehen
                if s == 'right' and self.nutze_kamera_links:
                    raw_x -= self.w_left_displayed
                    
                # Sicherheits-Check: Wurde auch auf die richtige Seite geklickt?
                if (s == 'left' and raw_x > self.w_left_displayed and self.nutze_kamera_rechts) or \
                   (s == 'right' and raw_x < 0):
                    self.log("SYSTEM", "⚠️ Klick war auf der falschen Seite! Bitte nochmal.", True)
                    return
                
                raw_x = max(0.0, raw_x) # Verhindert negative Werte
                
                # ---> NEU: Briefkasten füllen, statt Tkinter direkt zu berühren! <---
                self.picked_coords = (int(raw_x), int(raw_y)) # Wir nutzen saubere ganze Zahlen
                self.picked_coords_ready = True
                
                self.log("SYSTEM", f"✅ Koordinaten für Treffer übernommen!", True)
                return
                
        if event == cv2.EVENT_LBUTTONDOWN:
            # Beenden Button
            if self.btn_exit_coords:
                ex1, ey1, ex2, ey2 = self.btn_exit_coords
                if ex1 <= x <= ex2 and ey1 <= y <= ey2:
                    self.trigger_exit = True
                    return
            
            # Bug ZIP Button
            if getattr(self, 'btn_zip_coords', None):
                zx1, zy1, zx2, zy2 = self.btn_zip_coords
                if zx1 <= x <= zx2 and zy1 <= y <= zy2:
                    self.log("SYSTEM", "Generiere Debug-Paket... Bitte warten.", True)
                    imestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    zip_filepath = os.path.join(self.dm.ZIP_FOLDER, f"Debug_Paket_{timestamp}.zip")
                    # ---> NEU: Warten bis alle Bilder gespeichert sind! <---
                    self.dm.flush_image_queue()
                    # ---> ELA: Auch der Bug-Zip nutzt jetzt die einheitliche Funktion <---
                    success = self.dm.export_match_package(
                        filepath=zip_filepath,
                        source_folder=self.dm.DEBUG_FOLDER,
                        apply_diet_filter=False
                    )
                    if success:
                        self.log("SYSTEM", "Debug-ZIP wurde erfolgreich gespeichert!", True)
                    else:
                        self.log("SYSTEM", "Fehler beim Erstellen der Debug-ZIP!", True)
                    return
            
            # Reset Button (Links)
            if self.nutze_kamera_links and getattr(self, 'btn_left_coords', None):
                bx1, by1, bx2, by2 = self.btn_left_coords
                if bx1 <= x <= bx2 and by1 <= y <= by2:
                    self.trigger_reset_left = True
                    return
            
            # Reset Button (Rechts)
            if self.nutze_kamera_rechts and getattr(self, 'btn_right_coords', None):
                bx1, by1, bx2, by2 = self.btn_right_coords
                if bx1 <= x <= bx2 and by1 <= y <= by2:
                    self.trigger_reset_right = True
                    return
            
            # Edit Button (Links)
            if self.nutze_kamera_links and getattr(self, 'btn_edit_left_coords', None):
                ex1, ey1, ex2, ey2 = self.btn_edit_left_coords
                if ex1 <= x <= ex2 and ey1 <= y <= ey2:
                    self.trigger_edit_left = True
                    return
            
            # Edit Button (Rechts)
            if self.nutze_kamera_rechts and getattr(self, 'btn_edit_right_coords', None):
                ex1, ey1, ex2, ey2 = self.btn_edit_right_coords
                if ex1 <= x <= ex2 and ey1 <= y <= ey2:
                    self.trigger_edit_right = True
                    return
            
            # Highscore Button
            if getattr(self, 'btn_highscore_coords', None):
                hx1, hy1, hx2, hy2 = self.btn_highscore_coords
                if hx1 <= x <= hx2 and hy1 <= y <= hy2:
                    self.log("SYSTEM", "Öffne Highscore-Tabelle...", True)
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
                        self.log("SYSTEM", log_msg, True)
                        
                        backup_mask_l = self.sm.state_left.cumulative_mask.copy() if (self.nutze_kamera_links and self.sm.state_left and self.sm.state_left.cumulative_mask is not None) else None
                        backup_mask_r = self.sm.state_right.cumulative_mask.copy() if (self.nutze_kamera_rechts and self.sm.state_right and self.sm.state_right.cumulative_mask is not None) else None
                        
                        # ---> NEU: Warten bis alle Bilder sicher auf der Platte sind <---
                        self.dm.flush_image_queue()
                        if self.sm.save_current_match(player_name_l, player_name_r):
                            self.log("SYSTEM", "Match erfolgreich gespeichert!", True)
                            
                            # 1. Den Ordner fegen (löscht alle Schüsse/Diffs des alten Matches)
                            if self.nutze_kamera_links: self.dm.clear_debug_images('left', keep_startmask=True)
                            if self.nutze_kamera_rechts: self.dm.clear_debug_images('right', keep_startmask=True)
                            
                            # 2. Die Masken wiederherstellen UND speichern
                            if self.nutze_kamera_links and self.sm.state_left:
                                self.sm.state_left.cumulative_mask = backup_mask_l
                                if backup_mask_l is not None:
                                    self.dm.save_debug_image("cumulative_startmask_left", backup_mask_l)
                                    # ---> NEU: Das echte Kamerabild als Optik-Referenz mitspeichern <---
                                    if self.last_frame_l is not None:
                                        self.dm.save_debug_image("cumulative_orig_left", self.last_frame_l)
                                    self.sm.state_left.is_fortsetzung = True  # Flag für JSON setzen
                                    
                            if self.nutze_kamera_rechts and self.sm.state_right:
                                self.sm.state_right.cumulative_mask = backup_mask_r
                                if backup_mask_r is not None:
                                    self.dm.save_debug_image("cumulative_startmask_right", backup_mask_r)
                                    # ---> NEU: Das echte Kamerabild als Optik-Referenz mitspeichern <---
                                    if self.last_frame_r is not None:
                                        self.dm.save_debug_image("cumulative_orig_right", self.last_frame_r)
                                    self.sm.state_right.is_fortsetzung = True
                            
                            self.log("SYSTEM", "Leere Kamera-Puffer nach Pause...")
                            for _ in range(10): 
                                if self.nutze_kamera_links: self.cap_left.read()
                                if self.nutze_kamera_rechts: self.cap_right.read()
                        else:
                            self.log("SYSTEM", "Speichern abgebrochen (Keine Treffer).", True)
                    return

            # ---> NEU: Offline Labor Button (Der Brückenschlag) <---
            if getattr(self, 'btn_labor_coords', None):
                lx1, ly1, lx2, ly2 = self.btn_labor_coords
                if lx1 <= x <= lx2 and ly1 <= y <= ly2:
                    
                    # 1. DOPPELKLICK-SCHUTZ: Ignoriere weitere Klicks, solange das Labor lädt
                    if getattr(self, 'labor_is_opening', False): 
                        return
                    self.labor_is_opening = True
                    
                    ref_l = self.sm.state_left and self.sm.state_left.is_initialized
                    ref_r = self.sm.state_right and self.sm.state_right.is_initialized
                    
                    if not ref_l and not ref_r:
                        self.log("SYSTEM", "Labor startet leer (Noch keine Scheibe erkannt).", True)
                        subprocess.Popen(["python", "offline_labor.py"])
                        self.labor_is_opening = False
                        return
                    
                    # 2. LOG SETZEN UND SOFORTIGES NEUZEICHNEN ERZWINGEN!
                    self.log("SYSTEM", "Generiere Live-Snapshot und pausiere System...", True)
                    self.update_gui(self.last_frame_l, self.last_frame_r, True)
                    cv2.waitKey(50) # Gibt OpenCV Zeit, das Bild wirklich auf den Monitor zu schieben
                    
                    if self.nutze_kamera_links and self.last_frame_l is not None:
                        self.dm.save_debug_image("ZZZ_Live_Snapshot_left_orig", self.last_frame_l)
                    if self.nutze_kamera_rechts and self.last_frame_r is not None:
                        self.dm.save_debug_image("ZZZ_Live_Snapshot_right_orig", self.last_frame_r)
                    
                    self.dm.flush_image_queue()
                    match_data = self.sm.get_match_data("Live-Tuning", "Live-Tuning")
                    export_dir = "labor_export"
                    os.makedirs(export_dir, exist_ok=True)
                    zip_filepath = os.path.join(export_dir, "Live_Tuning_Bridge.zip")
                    
                    success = self.dm.export_match_package(
                        filepath=zip_filepath,
                        match_data=match_data,
                        source_folder=self.dm.DEBUG_FOLDER,
                        apply_diet_filter=False
                    )
                    
                    if success:
                        self.log("SYSTEM", f"Labor gestartet. TargetVision pausiert!", True)
                        self.update_gui(self.last_frame_l, self.last_frame_r, True)
                        cv2.waitKey(50)
                        
                        # 3. DER HERZSCHLAG-TRICK: Parallel starten und Fenster am Leben halten
                        proc = subprocess.Popen(["python", "offline_labor.py", zip_filepath])
                        
                        while proc.poll() is None:
                            # Hält die GUI reaktionsfähig für Windows (verhindert den "Absturz")
                            cv2.waitKey(100) 
                        
                        # =========================================================
                        # ---> DAS AUFWACHEN (Staffelstab greifen) <---
                        # =========================================================
                        handover_path = os.path.join(export_dir, "Live_Tuning_Handover.zip")
                        if os.path.exists(handover_path):
                            self.log("SYSTEM", "Labor-Handover gefunden! Lade Parameter...", True)
                            self.apply_handover(handover_path)
                            os.remove(handover_path) # Beweise vernichten!
                            self.log("SYSTEM", "Live-System erfolgreich aktualisiert!", True)
                        else:
                            self.log("SYSTEM", "Labor ohne Übernahme geschlossen.", True)
                            
                        # Kleine Pause für die Kameras, um Puffer-Müll (Standbilder) zu leeren
                        for _ in range(10): 
                            if self.nutze_kamera_links: self.cap_left.read()
                            if self.nutze_kamera_rechts: self.cap_right.read()
                            
                    else:
                        self.log("SYSTEM", "Fehler beim ZIP-Export. Starte Labor leer.", True)
                        subprocess.Popen(["python", "offline_labor.py"])
                        
                    # 4. DOPPELKLICK-SCHUTZ AUFHEBEN
                    self.labor_is_opening = False
                    return
            
            # ---> NEU: Handbuch Button <---
            if getattr(self, 'btn_hilfe_coords', None):
                hx1, hy1, hx2, hy2 = self.btn_hilfe_coords
                if hx1 <= x <= hx2 and hy1 <= y <= hy2:
                    self.log("SYSTEM", "Öffne Handbuch...", True)
                    # WICHTIG: Dateiname angepasst!
                    subprocess.Popen(["python", "HandbuchDeLuebs.py"]) 
                    return

            
    def process_edits(self):
        if self.trigger_edit_left:
            self.open_edit_dialog('left')
            self.trigger_edit_left = False
        if self.trigger_edit_right:
            self.open_edit_dialog('right')
            self.trigger_edit_right = False

    def open_edit_dialog(self, side):
        side_shots = self.sm.get_shots_for_side(side)
        if not side_shots:
            self.log("SYSTEM", f"Keine Treffer auf {'links' if side=='left' else 'rechts'} zum Editieren.", True)
            return

        # Basis-Dialog erstellen
        root_dialog = tk.Tk()
        root_dialog.withdraw()
        dialog = tk.Toplevel(root_dialog)
        dialog.title(f"Treffer bearbeiten - {'Links' if side=='left' else 'Rechts'}")
        dialog.geometry("550x450")
        dialog.attributes('-topmost', True)

        # "Alle markieren" Kopfzeile
        top_frame = tk.Frame(dialog)
        top_frame.pack(fill="x", padx=10, pady=5)
        
        select_all_var = tk.BooleanVar(value=False)
        check_vars = []
        entries = []  # Speichert: (shot_ref, x_var, y_var, score_var, check_var)

        def toggle_all():
            state = select_all_var.get()
            for var in check_vars:
                var.set(state)

        tk.Checkbutton(top_frame, text="Alle markieren", variable=select_all_var, command=toggle_all).pack(side="left")

        # Scrollbarer Bereich
        canvas_frame = tk.Frame(dialog)
        canvas_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        canvas = tk.Canvas(canvas_frame)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Tabellen-Header
        header_frame = tk.Frame(scrollable_frame)
        header_frame.pack(fill="x", pady=(0, 5))
        tk.Label(header_frame, text="Löschen", width=7).grid(row=0, column=0)
        tk.Label(header_frame, text="Nr.", width=4).grid(row=0, column=1)
        tk.Label(header_frame, text="X (px)", width=10).grid(row=0, column=2)
        tk.Label(header_frame, text="Y (px)", width=10).grid(row=0, column=3)
        tk.Label(header_frame, text="Ringe", width=10).grid(row=0, column=4)
        tk.Label(header_frame, text="Pick", width=5).grid(row=0, column=5) # <--- NE

        # Tabellen-Zeilen (Mit Entry für Editieren/Copy-Paste)
        for i, shot in enumerate(side_shots):
            row_frame = tk.Frame(scrollable_frame)
            row_frame.pack(fill="x", pady=2)

            c_var = tk.BooleanVar(value=False)
            check_vars.append(c_var)
            tk.Checkbutton(row_frame, variable=c_var, width=5).grid(row=0, column=0)

            tk.Label(row_frame, text=str(i+1), width=4).grid(row=0, column=1)

            # X Koordinate
            x_var = tk.StringVar(value=str(round(float(shot['pos'][0]), 1)))
            tk.Entry(row_frame, textvariable=x_var, width=10).grid(row=0, column=2, padx=5)

            # Y Koordinate
            y_var = tk.StringVar(value=str(round(float(shot['pos'][1]), 1)))
            tk.Entry(row_frame, textvariable=y_var, width=10).grid(row=0, column=3, padx=5)

            # Ringwert
            score_var = tk.StringVar(value=str(shot.get('score', 0.0)))
            tk.Entry(row_frame, textvariable=score_var, width=10).grid(row=0, column=4, padx=5)

            # ---> NEU: score_var (sv) wird mit in den Briefkasten gelegt <---
            def make_pick_cmd(xv, yv, sv, s_name):
                def cmd():
                    self.active_picker = {'x_var': xv, 'y_var': yv, 'score_var': sv, 'side': s_name}
                    self.log("SYSTEM", f"🎯 Klicke nun in das {s_name.upper()} Kamerabild!", True)
                return cmd

            tk.Button(row_frame, text="🎯", bg="#5bc0de", fg="black", command=make_pick_cmd(x_var, y_var, score_var, side)).grid(row=0, column=5, padx=2)
            entries.append((shot, x_var, y_var, score_var, c_var))
            #entries.append((shot, x_var, y_var, score_var, c_var))

        # Buttons Unten
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(fill="x", pady=10)

        def apply_changes():
            to_delete = []
            for item in entries:
                shot_ref, x_var, y_var, score_var, c_var = item
                if c_var.get():
                    to_delete.append(shot_ref)
                else:
                    # Werte auslesen und speichern
                    try:
                        new_x = float(x_var.get())
                        new_y = float(y_var.get())
                        new_score = float(score_var.get())
                        self.sm.update_shot(shot_ref, new_x, new_y, new_score)
                    except ValueError:
                        self.log("SYSTEM", "Fehlerhafte Eingabe ignoriert.")

            if to_delete:
                self.sm.remove_shots(to_delete)

            # ---> NEU: Polling stoppen bevor zerstört wird! <---
            if hasattr(dialog, 'poll_job'):
                dialog.after_cancel(dialog.poll_job)
            dialog.destroy()

        def cancel():
            # ---> NEU: Polling stoppen bevor zerstört wird! <---
            if hasattr(dialog, 'poll_job'):
                dialog.after_cancel(dialog.poll_job)
            dialog.destroy()
            
        # ---> NEU: Fängt den Klick auf das rote 'X' des Fensters ab! <---
        dialog.protocol("WM_DELETE_WINDOW", cancel)

        tk.Button(btn_frame, text="Übernehmen & Löschen", command=apply_changes, bg="#4CAF50", fg="white", font=('Arial', 10, 'bold')).pack(side="left", padx=20)
        tk.Button(btn_frame, text="Abbrechen", command=cancel, font=('Arial', 10)).pack(side="right", padx=20)

        # ---> NEU: Der sichere Tkinter-Briefkasten-Prüfer <---
        def poll_picker():
            try:
                # 1. Sicherheits-Check: Gibt es das Fenster überhaupt noch?
                if not dialog.winfo_exists(): 
                    return
                    
                if getattr(self, 'picked_coords_ready', False) and getattr(self, 'active_picker', None):
                    px, py = self.picked_coords
                    side_name = self.active_picker['side']
                    
                    self.active_picker['x_var'].set(str(px))
                    self.active_picker['y_var'].set(str(py))
                    
                    new_score = self.sm.calculate_score(side_name, px, py)
                    self.active_picker['score_var'].set(str(new_score))
                    
                    self.picked_coords_ready = False
                    self.active_picker = None 
                    
                # 2. Den "Wecker" stellen UND den Ausweis (poll_job) speichern, damit wir ihn abbrechen können
                dialog.poll_job = dialog.after(100, poll_picker)
            except Exception:
                pass # Falls das Fenster genau in dieser Millisekunde zerstört wird, sanft ignorieren
                
        poll_picker() # Polling-Schleife starten

        # Dialog blockierend ausführen
        root_dialog.wait_window(dialog)
        root_dialog.destroy()
        
        # Kamera-Puffer nach dem Blockieren kurz leeren (verhindert Framestau)
        for _ in range(5): 
            if self.nutze_kamera_links: self.cap_left.read()
            if self.nutze_kamera_rechts: self.cap_right.read()


    def run(self):
        blink_timer = time.time()
        blink_state = True
        
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        
        if self.vollbild:
            cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        else:
            cv2.resizeWindow(self.window_name, 1280, 720) 
            
        cv2.setMouseCallback(self.window_name, self.on_mouse_click)
        self.log("SYSTEM", "=== PROGRAMM GESTARTET ===", True)

        while True:
            frame_l, frame_r = self.read_frames()
            self.last_frame_l = frame_l  # <--- NEU: Merken fürs Labor!
            self.last_frame_r = frame_r  # <--- NEU: Merken fürs Labor!
            
            self.process_resets(frame_l, frame_r)
            
            # ---> NEU: Aufruf für die Editier-Menüs <---
            self.process_edits()
            
            if self.nutze_kamera_links: self.process_camera(frame_l, self.sm.state_left)
            if self.nutze_kamera_rechts: self.process_camera(frame_r, self.sm.state_right)

            if time.time() - blink_timer > 0.3:
                blink_state = not blink_state
                blink_timer = time.time()

            self.update_gui(frame_l, frame_r, blink_state)

            if self.check_keys():
                break

        self.cleanup()

if __name__ == "__main__":
    # ---> NEU: Nur das Hauptprogramm darf beim Start die alten Bilder löschen!
    dm = DateiManager(clear_on_start=True)
    config = dm.load_or_create_config()
    sm = StateManager(config, dm)
    
    tracker = TargetTracker(config, dm, sm)
    tracker.run()