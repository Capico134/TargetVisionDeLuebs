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
        
        
        # ---> Ersetze den langen Block in der __init__ durch: <---
        # --- GUI-Variablen einmalig initialisieren ---
        self.refresh_gui_settings_from_config()
        
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
        # ---> NEU: Platzhalter für den Zentrum-Button <---
        self.btn_center_left_coords = None
        self.btn_center_right_coords = None        

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
        
        self.show_all_rings = False
        self.btn_rings_coords = None
        
        # ---> NEU: Die elegante Messagebox-Prüfung ganz am Ende des Startvorgangs <---
        if hasattr(self.config, 'healed_parameters') and self.config.healed_parameters:
            self.show_config_alert()

    def refresh_gui_settings_from_config(self):
        """Aktualisiert alle GUI-spezifischen Attribute live aus dem Config-Objekt im RAM."""
        self.nutze_kamera_links = self.config.getboolean('Kameras', 'nutze_kamera_links', fallback=True)
        self.nutze_kamera_rechts = self.config.getboolean('Kameras', 'nutze_kamera_rechts', fallback=False)
        self.ausloeser_durch_erschuetterung = self.config.getboolean('Erkennung', 'ausloeser_durch_erschuetterung', fallback=False)
        self.poll_ms = self.config.getint('Timing', 'poll_ms', fallback=33)
        self.vollbild = self.config.getboolean('Anzeige', 'vollbild', fallback=False)
        self.darstellung_ohne_weissabgleich = self.config.getboolean('Anzeige', 'darstellung_ohne_weissabgleich', fallback=True)
        self.ringwertung_aktiv = self.config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
        self.serien_gruppierung = self.config.getint('Anzeige', 'serien_gruppierung', fallback=0)
        self.fischaugenkorrektur_links = self.config.getfloat('Kameras', 'fischaugenkorrektur_links', fallback=0.0)
        self.fischaugenkorrektur_rechts = self.config.getfloat('Kameras', 'fischaugenkorrektur_rechts', fallback=0.0)

    def show_config_alert(self):
        """Zeigt eine einmalige Warnung, falls beim Start Parameter mit Fallbacks gerettet wurden."""
        count = len(self.config.healed_parameters)
        titel = "Neue Einstellungen verfügbar"
        text = (
            f"Es wurden {count} neue oder fehlende Konfigurations-Parameter entdeckt.\n"
            "Das System verwendet vorübergehend sichere Standardwerte.\n\n"
            "Tipp: Öffne bei Gelegenheit das 'Labor & Einstellungen' "
            "und klicke dort auf 'Einstellungen speichern', um die neuen Werte "
            "dauerhaft in deine config.ini zu übernehmen."
        )
        
        temp_root = tk.Tk()
        temp_root.withdraw()
        temp_root.attributes('-topmost', True)
        messagebox.showinfo(titel, text, master=temp_root)
        temp_root.destroy()
        
        # Leeren, damit die Box bei Handover-Updates im laufenden Betrieb nicht nochmal poppt
        self.config.healed_parameters.clear()
            
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
        
        neu_links = self.config.getboolean('Kameras', 'nutze_kamera_links', fallback=True)
        neu_rechts = self.config.getboolean('Kameras', 'nutze_kamera_rechts', fallback=True)
        
        if neu_links != self.nutze_kamera_links or neu_rechts != self.nutze_kamera_rechts:
            self.log("SYSTEM", "⚠️ Kamera-Änderung erkannt. Neustart erforderlich!", True)
            self.dm.flush_image_queue()
            messagebox.showinfo("Neustart erforderlich", "Du hast die Kamera-Aktivierung in den Einstellungen geändert.\n\nDas System wird nun sicher beendet, um die Hardware-Verbindung neu aufzubauen.\nBitte starte TargetVision danach einfach neu!")
            self.trigger_exit = True
            return
            
        # =========================================================================
        # 2. DIE MAGIE: Single Source of Truth aktualisieren
        # =========================================================================
        # GUI updaten
        self.refresh_gui_settings_from_config()
        # Engine updaten (ohne ihre Referenzbilder zu löschen!)
        self.detector.refresh_settings_from_config()

        # 3. Referenz-Feedback für die GUI neu berechnen (falls Parameter geändert wurden)
        if self.detector.ref_left is not None:
            self.calib_feedback_left = self.detector.ninja_kalibrierungs_check(self.detector.ref_left, 'left')
        if self.detector.ref_right is not None:
            self.calib_feedback_right = self.detector.ninja_kalibrierungs_check(self.detector.ref_right, 'right')

        # =========================================================================
        # 4. BILDER & MASKEN: Die Labor-Wahrheit einpflanzen
        # =========================================================================
        for img_name, img_data in package['images'].items():
            base_name = os.path.basename(img_name)
            if base_name.startswith("ZZZ_Live_Snapshot"):
                continue
            clean_name = base_name.replace('.png', '').replace('.jpg', '')
            self.dm.save_debug_image(clean_name, img_data)
            
        if package['match_data']:
            self.sm.load_match_state(package['match_data'])
            
        for s in ['left', 'right']:
            state = self.sm.state_left if s == 'left' else self.sm.state_right
            if not state: continue
            
            # Kurzzeitgedächtnis flushen
            state.prev_gray = None
            state.is_moving = False
            state.still_counter = 0
            
            # Diff-Gesamt (Die "Pflicht"-Maske) des Labors hart übernehmen
            mask_name = next((f for f in package['images'] if f"diff_gesamt_{s}" in f or f"cumulative_startmask_{s}" in f), None)
            if mask_name:
                mask_bgr = package['images'][mask_name]
                state.cumulative_mask = cv2.cvtColor(mask_bgr, cv2.COLOR_BGR2GRAY)
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
        
        # ---> NEU: Zentrum-Button links neben Edit <---
        cx1, cy1 = start_x + frame_w - 330, total_h - 35
        cx2, cy2 = start_x + frame_w - 230, total_h - 5
        cv2.rectangle(view, (cx1, cy1), (cx2, cy2), (180, 130, 70), -1) # Dezentes Blau (BGR)
        cv2.rectangle(view, (cx1, cy1), (cx2, cy2), (255, 255, 255), 1)
        cv2.putText(view, "Zentrum", (cx1 + 15, cy1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        
        if side == 'left':
            self.btn_left_coords = (bx1, by1, bx2, by2)
            self.btn_edit_left_coords = (ex1, ey1, ex2, ey2)
            self.btn_center_left_coords = (cx1, cy1, cx2, cy2) # <--- NEU
        else:
            self.btn_right_coords = (bx1, by1, bx2, by2)
            self.btn_edit_right_coords = (ex1, ey1, ex2, ey2) 
            self.btn_center_right_coords = (cx1, cy1, cx2, cy2) # <--- NEU

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
            # =========================================================================
            # ---> NEU: ELA-Optimierung! Wir nutzen den OFFIZIELLEN Radius aus der JSON,
            # aber fallen auf den Slider-Wert zurück, wenn die Ringwertung aus ist!
            # =========================================================================
            aktive_scheibe = self.config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
            targets = self.dm.load_targets() 
            
            if self.ringwertung_aktiv and aktive_scheibe in targets:
                offizielles_kaliber_mm = float(targets[aktive_scheibe].get('kaliber_mm', 4.5))
            else:
                offizielles_kaliber_mm = self.config.getfloat('Erkennung', 'caliber_durchmesser', fallback=4.5)
            
            seite_str = "links" if side == 'left' else "rechts"
            px_x = self.config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
            px_y = self.config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
            avg_px = (px_x + px_y) / 2.0
            
            cal_r_offiziell = (offizielles_kaliber_mm / 2.0) * avg_px
            final_radius = max(2, int(cal_r_offiziell * self.scale_x))
            # =========================================================================
            
            side_shots = self.sm.get_shots_for_side(side)
            for idx, shot in enumerate(side_shots):
                x, y = shot['pos']
                
                if shot['side'] == 'right' and self.nutze_kamera_links:
                    x += self.w_left_displayed
                    
                # ---> OFFSET ADDIEREN! <---
                # VORHER: final_x = int(x * self.scale_x) + self.pad_x
                final_x = int(round(x * self.scale_x)) + self.pad_x
                final_y = int(round(y * self.scale_y)) + self.pad_y
                
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
            # HIER STECKT DER TIMER (15.0 Sekunden)
            if feedback and (current_time - feedback['time'] < 15.0):
                use_cam = self.nutze_kamera_links if s == 'left' else self.nutze_kamera_rechts
                if use_cam:
                    offset_x = 0 if s == 'left' else scaled_w_left
                    
                    # ---> NEU: self.pad_x und self.pad_y auf die Zentren addieren! <---
                    fb_cx = int(round(feedback['cx'] * self.scale_x)) + offset_x + getattr(self, 'pad_x', 0)
                    fb_cy = int(round(feedback['cy'] * self.scale_y)) + getattr(self, 'pad_y', 0)
                    
                    fb_ideal_rx = int(round(feedback['ideal_rx'] * self.scale_x))
                    fb_ideal_ry = int(round(feedback['ideal_ry'] * self.scale_y))
                    
                    # ---> NEU: Auch beim roten Fehler-Kreis den Offset addieren! <---
                    fb_red_cx = int(round(feedback['red_cx'] * self.scale_x)) + offset_x + getattr(self, 'pad_x', 0)
                    fb_red_cy = int(round(feedback['red_cy'] * self.scale_y)) + getattr(self, 'pad_y', 0)
                    
                    fb_red_rx = int(round(feedback['red_rx'] * self.scale_x))
                    fb_red_ry = int(round(feedback['red_ry'] * self.scale_y))

                    # =========================================================================
                    # ---> ELA HILFSFUNKTION: Gestrichelte Ellipsen zeichnen (1/3 Linie, 2/3 Lücke) <---
                    # =========================================================================
                    def draw_dashed_ellipse(img, center, rx, ry, color):
                        # Sicherheitscheck: OpenCV crasht bei Radien <= 0
                        if rx <= 0 or ry <= 0:
                            return
                            
                        # 60 kleine Segmente (alle 6 Grad). Davon 2 Grad Linie, 4 Grad Lücke.
                        for angle in range(0, 360, 6):
                            cv2.ellipse(img, center, (int(rx), int(ry)), 0, angle, angle + 2, color, 1, cv2.LINE_AA)

                    if feedback['show_red']:
                        draw_dashed_ellipse(combined_view, (fb_red_cx, fb_red_cy), fb_red_rx, fb_red_ry, (0, 0, 255))
                    
                    # 1. Den Standard "Spiegel" (Zentrum) zeichnen
                    draw_dashed_ellipse(combined_view, (fb_cx, fb_cy), fb_ideal_rx, fb_ideal_ry, (0, 255, 0))
                    
                    # ---> NEU: Ein feines Kreuz im exakten Zentrum <---
                    cross_size = 6
                    cv2.line(combined_view, (fb_cx - cross_size, fb_cy), (fb_cx + cross_size, fb_cy), (0, 255, 0), 1, cv2.LINE_AA)
                    cv2.line(combined_view, (fb_cx, fb_cy - cross_size), (fb_cx, fb_cy + cross_size), (0, 255, 0), 1, cv2.LINE_AA)
                    
                    # =========================================================================
                    # ---> ELA: Die beiden äußersten Ringe zur optischen Kontrolle zeichnen <---
                    # =========================================================================
                    aktive_scheibe = self.config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
                    targets = self.dm.load_targets()
                    
                    if aktive_scheibe in targets:
                        ringe = targets[aktive_scheibe].get('ringe_durchmesser_mm', {})
                        if ringe:
                            # Wir sortieren alle Durchmesser absteigend und schnappen uns die zwei größten!
                            alle_durchmesser = sorted([float(d) for d in ringe.values()], reverse=True)
                            aeusserste_zwei = alle_durchmesser[:2]
                            
                            seite_str = "links" if s == 'left' else "rechts"
                            px_x = self.config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
                            px_y = self.config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
                            korrektur = self.fischaugenkorrektur_links if s == 'left' else self.fischaugenkorrektur_rechts
                            
                            for d_mm in aeusserste_zwei:
                                r_mm_base = d_mm / 2.0
                                r_mm_draw = r_mm_base * (1.0 + (r_mm_base * korrektur)) # <--- NEU
                                ring_rx = round((r_mm_draw * px_x) * self.scale_x)
                                ring_ry = round((r_mm_draw * px_y) * self.scale_y)
                                
                                # Gestrichelte äußere Ringe zeichnen
                                draw_dashed_ellipse(combined_view, (fb_cx, fb_cy), ring_rx, ring_ry, (0, 255, 0))
        
        # =========================================================================
        # ---> NEU: Dauerhafte Zielscheiben-Ringe (Ein/Aus-Schalter) <---
        # =========================================================================
        if self.show_all_rings:
            for s, fb in [('left', self.calib_feedback_left), ('right', self.calib_feedback_right)]:
                use_cam = self.nutze_kamera_links if s == 'left' else self.nutze_kamera_rechts
                if use_cam and fb:
                    offset_x = 0 if s == 'left' else scaled_w_left
                    cx = int(round(fb['cx'] * self.scale_x)) + offset_x + getattr(self, 'pad_x', 0)
                    cy = int(round(fb['cy'] * self.scale_y)) + getattr(self, 'pad_y', 0)
                    
                    aktive_scheibe = self.config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
                    targets = self.dm.load_targets()
                    if aktive_scheibe in targets:
                        target_data = targets[aktive_scheibe]
                        ringe = target_data.get('ringe_durchmesser_mm', {})
                        innenzehner = target_data.get('innenzehner_mm', 0.0)
                        
                        seite_str = "links" if s == 'left' else "rechts"
                        px_x = self.config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
                        px_y = self.config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
                        korrektur = self.fischaugenkorrektur_links if s == 'left' else self.fischaugenkorrektur_rechts
                        
                        def draw_dashed_ellipse_perm(img, center, rx, ry, color):
                            for angle in range(0, 360, 6):
                                cv2.ellipse(img, center, (rx, ry), 0, angle, angle + 2, color, 1, cv2.LINE_AA)
                                
                        for ring_name, d_mm in ringe.items():
                            r_mm_base = float(d_mm) / 2.0
                            r_mm_draw = r_mm_base * (1.0 + (r_mm_base * korrektur)) # <--- NEU
                            rx = round((r_mm_draw * px_x) * self.scale_x)
                            ry = round((r_mm_draw * px_y) * self.scale_y)
                            draw_dashed_ellipse_perm(combined_view, (cx, cy), rx, ry, (0, 255, 0))
                            
                        if innenzehner > 0:
                            r_mm = float(innenzehner) / 2.0
                            rx = round((r_mm * px_x) * self.scale_x)
                            ry = round((r_mm * px_y) * self.scale_y)
                            draw_dashed_ellipse_perm(combined_view, (cx, cy), rx, ry, (0, 255, 0))
        
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
        
        # 6. Labor (Lila)
        self.btn_labor_coords, x_cursor = draw_button(combined_view, "Labor & Einstellungen", x_cursor, (150, 50, 150))
        
        # ---> NEU: 7. Zielscheiben-Ringe An/Aus <---
        rings_text = "Scheibe: An" if self.show_all_rings else "Scheibe: Aus"
        rings_color = (40, 160, 40) if self.show_all_rings else (80, 80, 80)
        self.btn_rings_coords, x_cursor = draw_button(combined_view, rings_text, x_cursor, rings_color)
        
        
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

                total_shots = len(side_shots)
                display_shots = side_shots[-max_items:] if total_shots > max_items else side_shots
                display_shots_rev = list(reversed(display_shots)) 
                
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
                
                for i, shot in enumerate(display_shots_rev):
                    shot_num = total_shots - i  # Zählt jetzt rückwärts (z.B. 17, 16, 15...)
                    score_val = shot.get('score', 0.0)
                    text_color = (0, 255, 255) if score_val < 10.0 else (0, 255, 0)
                    text = f" {shot_num}:"
                    score_str = f"{score_val:.1f}"
                    y_pos = start_y_hud + 20 + (i * line_h)
                    
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
                    
                    if i == 0 and len(display_shots_rev) > 1:
                        cv2.line(combined_view, (box_x - 5, y_pos + 8), (box_x + box_w - 5, y_pos + 8), (70, 70, 70), 1)

                y_sum = start_y_hud + 8 + len(display_shots_rev) * line_h
                cv2.line(combined_view, (box_x - 5, y_sum), (box_x + box_w - 5, y_sum), (100, 100, 100), 1)
                
                gesamt = sum(s.get('score', 0.0) for s in side_shots)
                gesamt_text = "Ges.:"
                gesamt_val = f"{gesamt:.1f}"
                y_total = y_sum + 20
                
                cv2.putText(combined_view, gesamt_text, (box_x - 5, y_total), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(combined_view, gesamt_val, (box_x + 45, y_total), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (50, 200, 255), 2, cv2.LINE_AA)

        # =========================================================================
        # ---> NEU: Prominenter Serien-Balken (Footer) mit Hintergrund <---
        # =========================================================================
        if self.ringwertung_aktiv and self.serien_gruppierung > 0:
            
            scaled_h = int(orig_h * self.scale_y)
            footer_y = getattr(self, 'pad_y', 0) + scaled_h - 65
            
            # ---> SCHRITT 1: Hintergrund vorbereiten <---
            overlay = combined_view.copy()
            
            # Wir müssen erst den Hintergrund für alle aktiven Seiten zeichnen
            for side in ['left', 'right']:
                if side == 'left' and not self.nutze_kamera_links: continue
                if side == 'right' and not self.nutze_kamera_rechts: continue
                
                side_shots = self.sm.get_shots_for_side(side)
                if not side_shots: continue
                
                if side == 'left':
                    start_x = getattr(self, 'pad_x', 0)
                    available_w = int(self.w_left_displayed * self.scale_x)
                else:
                    start_x = getattr(self, 'pad_x', 0) + int(self.w_left_displayed * self.scale_x)
                    available_w = int((orig_w - self.w_left_displayed) * self.scale_x)

                serien = [side_shots[i:i + self.serien_gruppierung] for i in range(0, len(side_shots), self.serien_gruppierung)]
                max_serien = 5 
                anzeige_serien = serien[-max_serien:]
                
                block_w = 110
                total_blocks_w = len(anzeige_serien) * block_w
                cursor_x = start_x + (available_w - total_blocks_w) // 2
                
                padding = 15
                box_x1 = cursor_x - padding
                box_x2 = cursor_x + total_blocks_w - block_w + 90 + padding
                box_y1 = footer_y - 25
                box_y2 = footer_y + 10
                
                # Nur das Rechteck auf das Overlay malen!
                cv2.rectangle(overlay, (box_x1, box_y1), (box_x2, box_y2), (20, 20, 20), -1)
                
            # ---> SCHRITT 2: Overlay einblenden BEVOR der Text kommt <---
            cv2.addWeighted(overlay, 0.4, combined_view, 0.6, 0, combined_view)

            # ---> SCHRITT 3: Text knackscharf auf das fertige Bild schreiben <---
            for side in ['left', 'right']:
                if side == 'left' and not self.nutze_kamera_links: continue
                if side == 'right' and not self.nutze_kamera_rechts: continue
                
                side_shots = self.sm.get_shots_for_side(side)
                if not side_shots: continue
                
                if side == 'left':
                    start_x = getattr(self, 'pad_x', 0)
                    available_w = int(self.w_left_displayed * self.scale_x)
                else:
                    start_x = getattr(self, 'pad_x', 0) + int(self.w_left_displayed * self.scale_x)
                    available_w = int((orig_w - self.w_left_displayed) * self.scale_x)

                serien = [side_shots[i:i + self.serien_gruppierung] for i in range(0, len(side_shots), self.serien_gruppierung)]
                max_serien = 6 
                anzeige_serien = serien[-max_serien:]
                
                block_w = 110
                total_blocks_w = len(anzeige_serien) * block_w
                cursor_x = start_x + (available_w - total_blocks_w) // 2
                
                for i, serie in enumerate(anzeige_serien):
                    serien_index = len(serien) - len(anzeige_serien) + i + 1
                    summe = sum(s.get('score', 0.0) for s in serie)
                    
                    is_active = (i == len(anzeige_serien) - 1) and (len(serie) < self.serien_gruppierung or len(side_shots) % self.serien_gruppierung == 0)
                    
                    color_label = (255, 255, 255) if is_active else (180, 180, 180)
                    color_val = (50, 220, 255) if is_active else (220, 220, 220)
                    
                    text_l = f"S{serien_index}:"
                    text_r = f"{summe:.1f}"
                    
                    cv2.putText(combined_view, text_l, (cursor_x, footer_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_label, 1, cv2.LINE_AA)
                    cv2.putText(combined_view, text_r, (cursor_x + 35, footer_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color_val, 2, cv2.LINE_AA)
                    
                    cursor_x += block_w
                    
        cv2.imshow(self.window_name, combined_view)

    def check_keys(self):
        # ---> ELA FIX: waitKeyEx liest auch Pfeiltasten (Sondertasten) aus! <---
        raw_key = cv2.waitKeyEx(self.poll_ms)
        key = raw_key & 0xFF
        
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

        # =========================================================================
        # ---> NEU: ELA-Nudge-Funktion (Pixel-Schubsen per Pfeiltasten oder WASD) <---
        # =========================================================================
        # Windows Pfeiltasten: Hoch=2490368, Runter=2621440, Links=2424832, Rechts=2555904
        # Linux Pfeiltasten: Hoch=65362, Runter=65364, Links=65361, Rechts=65363
        if raw_key in (2490368, 65362, 2621440, 65364, 2424832, 65361, 2555904, 65363) or key in (ord('w'), ord('a'), ord('s'), ord('d')):
            current_time = time.time()
            
            # Herausfinden, welche Seite gerade aktiv kalibriert wird (Der neuere Timer gewinnt!)
            active_side = None
            active_fb = None
            
            t_left = self.calib_feedback_left['time'] if self.calib_feedback_left else 0
            t_right = self.calib_feedback_right['time'] if self.calib_feedback_right else 0
            
            if current_time - t_left < 15.0 and t_left >= t_right:
                active_side = 'left'
                active_fb = self.calib_feedback_left
            elif current_time - t_right < 15.0:
                active_side = 'right'
                active_fb = self.calib_feedback_right
                
            if active_side and active_fb:
                dx, dy = 0, 0
                if raw_key in (2490368, 65362) or key == ord('w'): dy = -1
                elif raw_key in (2621440, 65364) or key == ord('s'): dy = 1
                elif raw_key in (2424832, 65361) or key == ord('a'): dx = -1
                elif raw_key in (2555904, 65363) or key == ord('d'): dx = 1
                
                # 1. Koordinaten um exakt 1 Pixel verschieben
                new_x = active_fb['cx'] + dx
                new_y = active_fb['cy'] + dy
                
                # 2. Ins System schreiben
                self.sm.set_nullpunkt(active_side, new_x, new_y)
                
                # 3. Feedback updaten & TIMER VERLÄNGERN!
                active_fb['cx'] = new_x
                active_fb['cy'] = new_y
                active_fb['time'] = current_time 
                
                # 4. Ringwertung aller bestehenden Schüsse live neu durchrechnen!
                for shot in self.sm.shots:
                    if shot['side'] == active_side:
                        new_score, raw_score = self.sm.calculate_score(active_side, shot['pos'][0], shot['pos'][1])
                        shot['score'] = new_score
                        shot['raw_score'] = raw_score
                        
                self.log("SYSTEM", f"🎯 Zentrum {active_side.upper()} feinjustiert: X:{new_x} Y:{new_y}", True)

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
                mode = self.active_picker.get('mode', 'edit') # <--- ELA: Fallback auf edit für den alten Dialog
                
                # ---> OFFSET ABZIEHEN! <---
                raw_x = (x - getattr(self, 'pad_x', 0)) / self.scale_x
                raw_y = (y - getattr(self, 'pad_y', 0)) / self.scale_y
                
                if s == 'right' and self.nutze_kamera_links:
                    raw_x -= self.w_left_displayed
                    
                if (s == 'left' and raw_x > self.w_left_displayed and self.nutze_kamera_rechts) or \
                   (s == 'right' and raw_x < 0):
                    self.log("SYSTEM", "⚠️ Klick war auf der falschen Seite! Bitte nochmal.", True)
                    return
                
                raw_x = max(0.0, raw_x)
                picked_x, picked_y = int(raw_x), int(raw_y)
                
                # ==============================================================
                # ---> NEU: Weiche für Editieren vs. Zentrum setzen <---
                # ==============================================================
                if mode == 'center':
                    # 1. Den Nullpunkt im System überschreiben
                    self.sm.set_nullpunkt(s, picked_x, picked_y)
                    self.log("SYSTEM", f"🎯 Neues Zentrum {s.upper()} gesetzt: X:{picked_x} Y:{picked_y}", True)
                    
                    # 2. Visuelles Feedback aktualisieren (Grüner Kreis rutscht zur Maus)
                    old_fb = self.calib_feedback_left if s == 'left' else self.calib_feedback_right
                    new_fb = {
                        'cx': picked_x, 'cy': picked_y,
                        'red_cx': picked_x, 'red_cy': picked_y,
                        'ideal_rx': old_fb['ideal_rx'] if old_fb else 150, 
                        'ideal_ry': old_fb['ideal_ry'] if old_fb else 150,
                        'red_rx': 0, 'red_ry': 0,
                        'show_red': False,
                        'time': time.time() # Startet den Timer für die Anzeige neu
                    }
                    if s == 'left': self.calib_feedback_left = new_fb
                    else: self.calib_feedback_right = new_fb
                        
                    # 3. Ringwertung aller bestehenden Schüsse live neu durchrechnen!
                    for shot in self.sm.shots:
                        if shot['side'] == s:
                            new_score, raw_score = self.sm.calculate_score(s, shot['pos'][0], shot['pos'][1])
                            shot['score'] = new_score
                            shot['raw_score'] = raw_score
                            
                    self.active_picker = None 
                    return
                else:
                    # Der bisherige Editier-Modus für den Briefkasten
                    self.picked_coords = (picked_x, picked_y) 
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
            
            # Zentrum Button (Links)
            if self.nutze_kamera_links and getattr(self, 'btn_center_left_coords', None):
                cx1, cy1, cx2, cy2 = self.btn_center_left_coords
                if cx1 <= x <= cx2 and cy1 <= y <= cy2:
                    self.active_picker = {'mode': 'center', 'side': 'left'}
                    self.log("SYSTEM", "🎯 Klicke ins LINKE Kamerabild, um das neue Zentrum zu setzen!", True)
                    return
            
            # Zentrum Button (Rechts)
            if self.nutze_kamera_rechts and getattr(self, 'btn_center_right_coords', None):
                cx1, cy1, cx2, cy2 = self.btn_center_right_coords
                if cx1 <= x <= cx2 and cy1 <= y <= cy2:
                    self.active_picker = {'mode': 'center', 'side': 'right'}
                    self.log("SYSTEM", "🎯 Klicke ins RECHTE Kamerabild, um das neue Zentrum zu setzen!", True)
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
                        
                        # ---> NEU: Erst warten, bis der Koch alle Bilder sicher auf der Platte hat <---
                        self.dm.flush_image_queue()
                        
                        # =========================================================
                        # ---> DER FIX: Wir holen uns das letzte PERFEKTE Bild von der Festplatte! <---
                        # =========================================================
                        # Links
                        path_l = os.path.join(self.dm.DEBUG_FOLDER, "letzte_aufnahme_left.png")
                        if not os.path.exists(path_l): path_l = os.path.join(self.dm.DEBUG_FOLDER, "referenz_left.png")
                        best_orig_l = cv2.imread(path_l) if os.path.exists(path_l) else None

                        # Rechts
                        path_r = os.path.join(self.dm.DEBUG_FOLDER, "letzte_aufnahme_right.png")
                        if not os.path.exists(path_r): path_r = os.path.join(self.dm.DEBUG_FOLDER, "referenz_right.png")
                        best_orig_r = cv2.imread(path_r) if os.path.exists(path_r) else None
                        
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
                                    # ---> NEU: Das garantiert saubere Bild als Optik-Referenz mitspeichern <---
                                    if best_orig_l is not None:
                                        self.dm.save_debug_image("cumulative_orig_left", best_orig_l)
                                    self.sm.state_left.is_fortsetzung = True  # Flag für JSON setzen
                                    
                            if self.nutze_kamera_rechts and self.sm.state_right:
                                self.sm.state_right.cumulative_mask = backup_mask_r
                                if backup_mask_r is not None:
                                    self.dm.save_debug_image("cumulative_startmask_right", backup_mask_r)
                                    # ---> NEU: Das garantiert saubere Bild als Optik-Referenz mitspeichern <---
                                    if best_orig_r is not None:
                                        self.dm.save_debug_image("cumulative_orig_right", best_orig_r)
                                    self.sm.state_right.is_fortsetzung = True
                            
                            self.log("SYSTEM", "Leere Kamera-Puffer nach Pause...")
                            for _ in range(10): 
                                if self.nutze_kamera_links: self.cap_left.read()
                                if self.nutze_kamera_rechts: self.cap_right.read()
                        else:
                            self.log("SYSTEM", "Speichern abgebrochen (Keine Treffer).", True)
                    return

            # ---> NEU: Labor Button (Der Brückenschlag) <---
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
                        subprocess.Popen(["python", "LaborDeLuebs.py"])
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
                        proc = subprocess.Popen(["python", "LaborDeLuebs.py", zip_filepath])
                        
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
                            
                        # =========================================================
                        # ---> NEU: MÜLLABFUHR FÜR DIE ZZZ-SNAPSHOTS <---
                        # =========================================================
                        self.dm.flush_image_queue() # Erst sicherstellen, dass alles auf der Platte ist
                        try:
                            if hasattr(self.dm, 'DEBUG_FOLDER') and os.path.exists(self.dm.DEBUG_FOLDER):
                                for f in os.listdir(self.dm.DEBUG_FOLDER):
                                    if f.startswith("ZZZ_Live_Snapshot"):
                                        os.remove(os.path.join(self.dm.DEBUG_FOLDER, f))
                        except Exception:
                            pass
                            
                        # Kleine Pause für die Kameras, um Puffer-Müll (Standbilder) zu leeren
                        for _ in range(10): 
                            if self.nutze_kamera_links: self.cap_left.read()
                            if self.nutze_kamera_rechts: self.cap_right.read()
                            
                    else:
                        self.log("SYSTEM", "Fehler beim ZIP-Export. Starte Labor leer.", True)
                        subprocess.Popen(["python", "LaborDeLuebs.py"])
                        
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
                    
            # ---> NEU: Zielscheiben-Ringe Button <---
            if getattr(self, 'btn_rings_coords', None):
                rx1, ry1, rx2, ry2 = self.btn_rings_coords
                if rx1 <= x <= rx2 and ry1 <= y <= ry2:
                    self.show_all_rings = not self.show_all_rings
                    self.log("SYSTEM", f"Zielscheiben-Ringe dauerhaft {'aktiviert' if self.show_all_rings else 'deaktiviert'}.", True)
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