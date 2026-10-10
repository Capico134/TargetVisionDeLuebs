import platform
import cv2
import numpy as np
import time
import subprocess
import os
import sys
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import threading #loading
import math      #loading

# --- NEU: Unsere sauberen Manager-Importe ---
from DateiManagerDeLuebs import DateiManager
from StateManagerDeLuebs import StateManager
from DetectionDeLuebs import TargetDetector
from TargetVisionRenderer import TargetVisionRenderer # <--- NEU!

import LoggerDeLuebs

class TargetTracker:
    def __init__(self, config, datei_manager, state_manager):
        self.config = config
        self.dm = datei_manager
        self.sm = state_manager
        
        self.version = self.dm.get_current_version()
        print(f"🎯 TargetVision DeLübs     [v{self.version}]")
        self.window_name = f"TargetVision DeLuebs - v{self.version}"
        
        # ---> NEU: Als Instanz-Variable speichern! <---
        self.is_windows = platform.system() == 'Windows'
        
        self.nutze_kamera_links = config.getboolean('Kameras', 'nutze_kamera_links')
        self.nutze_kamera_rechts = config.getboolean('Kameras', 'nutze_kamera_rechts')

        print("\n--- START KAMERA INITIALISIERUNG (ASYNCHRON) ---")
        self.kameras_bereit = False
        # 1. Den Hintergrundarbeiter losschicken
        init_thread = threading.Thread(target=self._background_camera_init, daemon=True)
        init_thread.start()
        # 2. Während der Arbeiter schwitzt, bespaßen wir den Nutzer mit der Animation
        self._play_splash_screen()
        
        # --- GUI-Variablen einmalig initialisieren ---
        self.refresh_gui_settings_from_config()
        
        self.detector = TargetDetector(config, datei_manager, state_manager, self.log)
        
        # ---> NEU: Wir lagern das Zeichnen in den Renderer aus! <---
        self.renderer = TargetVisionRenderer(self)

        self.current_crops = {'left': (0,0,0,0), 'right': (0,0,0,0)}
        self.raw_dims = {'left': (1,1), 'right': (1,1)}
        self.last_frame_l = None
        self.last_frame_r = None
        
        self.calib_feedback_left = None
        self.calib_feedback_right = None
        
        self.trigger_reset_left = False
        self.trigger_reset_right = False
        self.trigger_edit_left = False
        self.trigger_edit_right = False
        self.trigger_exit = False
        self.active_picker = None 
        
        if hasattr(self.config, 'healed_parameters') and self.config.healed_parameters:
            self.show_config_alert()

    def _background_camera_init(self):
        """Hier passiert die harte, blockierende Hardware-Arbeit im Hintergrund."""
        cam_left_idx = self.config.getint('Kameras', 'cam_left_index')
        cam_right_idx = self.config.getint('Kameras', 'cam_right_index')
        
        width_l = self.config.getint('Kameras', 'cam_width_links', fallback=1280)
        height_l = self.config.getint('Kameras', 'cam_height_links', fallback=720)
        width_r = self.config.getint('Kameras', 'cam_width_rechts', fallback=1280)
        height_r = self.config.getint('Kameras', 'cam_height_rechts', fallback=720)
        
        # ---> FEHLENDE ZEILE: Beide Kameras initialisieren! <---
        self.cap_left = cv2.VideoCapture(cam_left_idx, cv2.CAP_ANY) if self.nutze_kamera_links else None
        self.cap_right = cv2.VideoCapture(cam_right_idx, cv2.CAP_ANY) if self.nutze_kamera_rechts else None
        
        if self.nutze_kamera_links and self.cap_left:
            mjpg_fcc = cv2.VideoWriter_fourcc(*'MJPG')
            self._smart_set(self.cap_left, cv2.CAP_PROP_FOURCC, mjpg_fcc)
            self._smart_set(self.cap_left, cv2.CAP_PROP_FRAME_WIDTH, width_l)
            self._smart_set(self.cap_left, cv2.CAP_PROP_FRAME_HEIGHT, height_l)
            self._smart_set(self.cap_left, cv2.CAP_PROP_FPS, 30)
            belichtung_l = self.config.get('Kameras', 'belichtung_links', fallback='Standard')
            self._set_camera_exposure(self.cap_left, belichtung_l)
            
        if self.nutze_kamera_rechts and self.cap_right:
            mjpg_fcc = cv2.VideoWriter_fourcc(*'MJPG')
            self._smart_set(self.cap_right, cv2.CAP_PROP_FOURCC, mjpg_fcc)
            self._smart_set(self.cap_right, cv2.CAP_PROP_FRAME_WIDTH, width_r)
            self._smart_set(self.cap_right, cv2.CAP_PROP_FRAME_HEIGHT, height_r)
            self._smart_set(self.cap_right, cv2.CAP_PROP_FPS, 30)
            belichtung_r = self.config.get('Kameras', 'belichtung_rechts', fallback='Standard')
            self._set_camera_exposure(self.cap_right, belichtung_r)
            
        # Signal an die Animation: Wir sind fertig!
        self.kameras_bereit = True

    def _play_splash_screen(self):
        """Zeichnet eine flüssige Animation (Pulsierend), bis die Kameras bereit sind."""
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        if getattr(self, 'vollbild', False):
            cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        else:
            cv2.resizeWindow(self.window_name, 1280, 720)
            
        # 1. Versuchen, das existierende PNG-Logo für den Splash-Screen zu laden
        logo_img = None
        logo_alpha = None
        new_h, new_w = 0, 0
        
        logo_path = os.path.join(getattr(self.dm, 'BASE_DIR', ''), "logo.png")
        if os.path.exists(logo_path):
            raw_logo = cv2.imread(logo_path, cv2.IMREAD_UNCHANGED)
            if raw_logo is not None and raw_logo.shape[2] == 4:
                # Das Logo schön groß für den Startbildschirm skalieren (z.B. 1.2x Original)
                h, w = raw_logo.shape[:2]
                scale = 1.2
                new_w, new_h = int(w * scale), int(h * scale)
                raw_logo = cv2.resize(raw_logo, (new_w, new_h), interpolation=cv2.INTER_AREA)
                
                logo_alpha = (raw_logo[:, :, 3] / 255.0).astype(np.float32)
                logo_img = raw_logo[:, :, :3].astype(np.float32)
                
        winkel = 0
        start_time = time.time()
        
        while not getattr(self, 'kameras_bereit', False):
            # Dunkelgraue Leinwand
            #splash = np.full((720, 1280, 3), (35, 35, 35), dtype=np.uint8)
            splash = np.full((720, 1280, 3), (235, 35, 35), dtype=np.uint8)
            elapsed = time.time() - start_time
            
            # --- Logo pulsieren lassen (Sinuswelle) ---
            if logo_img is not None:
                # math.sin pendelt zwischen -1.0 und 1.0. 
                # Multipliziert mit 3.0 steuern wir die Geschwindigkeit des Pulsierens.
                # Mit 0.75 + (0.25 * sin) pendelt der Wert sauber zwischen 0.5 (halbtransparent) und 1.0 (voll sichtbar).
                pulse_factor = 0.75 + (0.25 * math.sin(elapsed * 3.0))
                
                current_alpha = logo_alpha * pulse_factor
                inv_alpha = 1.0 - current_alpha
                
                # Exakt in der Mitte platzieren
                c_y = (720 - new_h) // 2
                c_x = (1280 - new_w) // 2
                
                roi = splash[c_y:c_y+new_h, c_x:c_x+new_w].astype(np.float32)
                # Alpha-Blending
                blended = (roi * np.dstack([inv_alpha]*3)) + (logo_img * np.dstack([current_alpha]*3))
                splash[c_y:c_y+new_h, c_x:c_x+new_w] = blended.astype(np.uint8)
            else:
                # Fallback, falls kein Logo da ist (Text pulsiert nicht, bleibt statisch)
                cv2.putText(splash, "TargetVision DeLuebs", (380, 350), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3, cv2.LINE_AA)
            
            # --- Lade-Text und rotierender Cyber-Kreis unten rechts ---
            cv2.putText(splash, "Lade Hardware...", (1000, 685), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
            cv2.ellipse(splash, (1200, 680), (12, 12), winkel, 0, 280, (50, 200, 255), 2, cv2.LINE_AA)
            
            cv2.imshow(self.window_name, splash)
            cv2.waitKey(33) # 33ms Wait = Saubere ~30 FPS für die Animation
            winkel = (winkel + 15) % 360


    def refresh_gui_settings_from_config(self):
        """Aktualisiert alle GUI-spezifischen Attribute live aus dem Config-Objekt im RAM."""
        self.nutze_kamera_links = self.config.getboolean('Kameras', 'nutze_kamera_links', fallback=True)
        self.nutze_kamera_rechts = self.config.getboolean('Kameras', 'nutze_kamera_rechts', fallback=False)
        self.ausloeser_durch_erschuetterung = self.config.getboolean('Erkennung', 'ausloeser_durch_erschuetterung', fallback=False)
        
        # ---> NEU: fps_limit statt poll_ms <---
        self.fps_limit = self.config.getint('Timing', 'fps_limit', fallback=30)
        #self.poll_ms = self.config.getint('Timing', 'poll_ms', fallback=33)
        
        self.vollbild = self.config.getboolean('Anzeige', 'vollbild', fallback=False)
        
        # Dem Renderer Bescheid geben, falls er schon existiert
        if hasattr(self, 'renderer'):
            self.renderer.refresh_settings()

    def show_config_alert(self):
        healed_list = self.config.healed_parameters
        count = len(healed_list)
        
        display_list = "\n".join([f"• {p}" for p in healed_list[:10]])
        if count > 10:
            display_list += f"\n• ... und {count - 10} weitere."
            
        titel = "Neue Einstellungen verfügbar"
        text = (
            f"Es wurden {count} neue oder fehlende Konfigurations-Parameter entdeckt "
            "und vorübergehend mit sicheren Standardwerten ergänzt:\n\n"
            f"{display_list}\n\n"
            "Tipp: Öffne bei Gelegenheit das 'Labor & Einstellungen' "
            "und klicke dort auf 'Einstellungen speichern', um die neuen Werte "
            "dauerhaft in deine config.ini zu übernehmen."
        )
        
        temp_root = tk.Tk()
        temp_root.withdraw()
        temp_root.attributes('-topmost', True)
        messagebox.showinfo(titel, text, master=temp_root)
        temp_root.destroy()
        self.config.healed_parameters.clear()
            
    def log(self, side, text, show_gui=False):
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        log_msg = f"[{timestamp}] [{side.upper()}] {text}"
        
        self.dm.write_log(log_msg)
            
        if show_gui:
            gui_text = "".join(c for c in text if ord(c) < 1000).strip()
            gui_text = gui_text if len(gui_text) <= 45 else gui_text[:42] + "..."
            self.renderer.set_message(side, gui_text)

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

        # Zoom-Blocker prüft im Renderer
        anim = self.renderer.zoom_animation.get(state.side)
        if anim:
            if time.time() - anim['start_time'] < anim['duration']:
                return  
            self.renderer.zoom_animation[state.side] = None

        if not state.is_initialized:
            bg_visible, bg_percent = state.is_background_visible(frame)
            self.log(state.side, f"STARTUP-CHECK: Hintergrund zu {bg_percent:.1f}% sichtbar.")
            
            if bg_visible:
                self.log(state.side, "Status: Keine Scheibe vorhanden (Warte auf Einfahren).")
                state.target_present = False
            else:
                self.log(state.side, "Status: Scheibe direkt im Bild erkannt! Speichere Initial-Referenz.", True)
                state.target_present = True
                
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
                        
                        shot_found = self.detector.check_background_and_evaluate(frame, state) 
                        if shot_found: 
                            self.renderer.trigger_zoom(state.side, frame)
                            self.flush_camera_buffers(12) 
                        self.log(state.side, "-" * 60)
        else:
            current_time = time.time()
            if current_time - state.last_scan_time > 1.5:
                state.last_scan_time = current_time
                
                shot_found = self.detector.check_background_and_evaluate(frame, state)
                if shot_found: 
                    self.renderer.trigger_zoom(state.side, frame)
                    self.flush_camera_buffers(12)

    def read_frames(self):
        frame_l, frame_r = None, None
        if self.nutze_kamera_links: 
            ret_l, raw_l = self.cap_left.read()
            frame_l = self.apply_crop(raw_l, 'left') if ret_l else None
        if self.nutze_kamera_rechts: 
            ret_r, raw_r = self.cap_right.read()
            frame_r = self.apply_crop(raw_r, 'right') if ret_r else None
        return frame_l, frame_r

    def flush_camera_buffers(self, frames_to_drop=5):
        for _ in range(frames_to_drop):
            if self.nutze_kamera_links and self.cap_left: self.cap_left.read()
            if self.nutze_kamera_rechts and self.cap_right: self.cap_right.read()

    def _smart_set(self, cap, prop, target_value):
        """Setzt einen OpenCV-Parameter nur, wenn er abweicht, um irrelevante USB-Neustarts zu verhindern."""
        if cap.get(prop) != target_value:
            cap.set(prop, target_value)
    
    def _set_camera_exposure(self, cap, belichtung_str):
        """Erzwingt zuverlässig das Setzen der Belichtung (mit Smart-Check)."""
        if not cap or not cap.isOpened() or belichtung_str == 'Standard':
            return
            
        auto_mode_val = 1 if self.is_windows else 3
        manual_mode_val = 0 if self.is_windows else 1
            
        if belichtung_str == 'Auto':
            self._smart_set(cap, cv2.CAP_PROP_AUTO_EXPOSURE, auto_mode_val)
        else:
            try:
                exp_val = int(belichtung_str)
                # Nur in den manuellen Modus zwingen, falls sie noch auf Auto steht
                if cap.get(cv2.CAP_PROP_AUTO_EXPOSURE) != manual_mode_val:
                    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, manual_mode_val)
                    time.sleep(0.05)
                
                self._smart_set(cap, cv2.CAP_PROP_EXPOSURE, exp_val)
            except ValueError:
                pass

    def apply_handover(self, zip_path):
        package = self.dm.import_match_package(zip_path)
        if not package: return
        
        # 1. Wir laden den NEUEN Parser aus dem Labor-Paket
        new_parser = package['config']
        
        # 2. Wir definieren alle "tiefen" Systemeinstellungen, die einen Neustart erzwingen
        reboot_required = False
        reboot_triggers = []
        
        check_keys = [
            ('Kameras', 'nutze_kamera_links'),
            ('Kameras', 'nutze_kamera_rechts'),
            ('Kameras', 'cam_left_index'),
            ('Kameras', 'cam_right_index'),
            ('Kameras', 'cam_width_links'),
            ('Kameras', 'cam_height_links'),
            ('Kameras', 'cam_width_rechts'),
            ('Kameras', 'cam_height_rechts'),
            ('Anzeige', 'vollbild')
            #('Crop_Links', 'cut_top'), ('Crop_Links', 'cut_bottom'), ('Crop_Links', 'cut_left'), ('Crop_Links', 'cut_right'),
            #('Crop_Rechts', 'cut_top'), ('Crop_Rechts', 'cut_bottom'), ('Crop_Rechts', 'cut_left'), ('Crop_Rechts', 'cut_right')
        ]
        
        # 3. Wir vergleichen die NEUEN Werte mit den ALTEN Werten, die aktuell im System ticken
        for section, key in check_keys:
            # Sicherheitscheck: Falls eine Sektion in der alten Config fehlen sollte
            if not self.config.has_section(section):
                self.config.add_section(section)
            if not new_parser.has_section(section):
                new_parser.add_section(section)
                
            old_val = self.config.get(section, key, fallback=None)
            new_val = new_parser.get(section, key, fallback=None)
            
            if str(old_val).strip() != str(new_val).strip():
                reboot_required = True
                reboot_triggers.append(f"[{section}] {key}")
        
        # 4. Wenn eine Kern-Einstellung geändert wurde -> Notbremse!
        if reboot_required:
            trigger_list = "\n".join([f"• {t}" for t in reboot_triggers])
            self.log("SYSTEM", f"⚠️ Tiefe System-Änderungen erkannt. Neustart erforderlich!", True)
            self.dm.flush_image_queue()
            
            msg = (
                "Du hast im Labor tiefe Systemeinstellungen geändert:\n\n"
                f"{trigger_list}\n\n"
                "Das System wird nun sicher beendet, um die Hardware-Verbindung "
                "und die Bild-Puffer sauber neu aufzubauen.\n"
                "Bitte starte TargetVision danach einfach neu!"
            )
            messagebox.showinfo("Neustart erforderlich", msg)
            self.trigger_exit = True
            return
            
        # 5. Ab hier: Es wurden nur weiche Parameter (Filter, Toleranzen) ODER Live-Hardware-Befehle geändert!
        # Wir laden die neue Config nun offiziell in das Hauptsystem.
        self.config.read(self.dm.CONFIG_FILE, encoding='utf-8')

        # =====================================================================
        # ---> NEU: Belichtung live auf die laufenden Kameras anwenden! <---
        # =====================================================================
        if self.nutze_kamera_links and self.cap_left:
            belichtung_l = self.config.get('Kameras', 'belichtung_links', fallback='Standard')
            self._set_camera_exposure(self.cap_left, belichtung_l)
                
        if self.nutze_kamera_rechts and self.cap_right:
            belichtung_r = self.config.get('Kameras', 'belichtung_rechts', fallback='Standard')
            self._set_camera_exposure(self.cap_right, belichtung_r)
        # =====================================================================
        
        # Weiche Variablen im laufenden Betrieb updaten
        self.refresh_gui_settings_from_config()
        self.detector.refresh_settings_from_config()

        if self.detector.ref_left is not None:
            self.calib_feedback_left = self.detector.ninja_kalibrierungs_check(self.detector.ref_left, 'left')
        if self.detector.ref_right is not None:
            self.calib_feedback_right = self.detector.ninja_kalibrierungs_check(self.detector.ref_right, 'right')

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
            
            state.prev_gray = None
            state.is_moving = False
            state.still_counter = 0
            
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
        state.is_fortsetzung = False 
        
        if frame is not None:
            feedback = self.detector.set_reference_image(frame, side) 
            if side == 'left': self.calib_feedback_left = feedback
            else: self.calib_feedback_right = feedback
            state.target_present = True
            
        self.log(side, "MANUELLER RESET: Referenz gelockt (Pausenerkennung bleibt AKTIV).", True)
        self.log(side, "-" * 60) 

    def process_resets(self, frame_l, frame_r):
        if self.trigger_reset_left:
            self.execute_manual_reset('left', frame_l)
            self.trigger_reset_left = False
        if self.trigger_reset_right:
            self.execute_manual_reset('right', frame_r)
            self.trigger_reset_right = False

    def show_pause_screen(self, message):
        pause_frame = np.full((720, 1280, 3), (35, 35, 35), dtype=np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        
        (w1, h1), _ = cv2.getTextSize(message, font, 1.2, 2)
        cv2.putText(pause_frame, message, ((1280 - w1) // 2, 320), font, 1.2, (50, 200, 255), 2, cv2.LINE_AA)
        
        text2 = "Bitte schließe das andere Fenster, um hier fortzufahren."
        (w2, h2), _ = cv2.getTextSize(text2, font, 0.8, 1)
        cv2.putText(pause_frame, text2, ((1280 - w2) // 2, 400), font, 0.8, (180, 180, 180), 1, cv2.LINE_AA)
        
        if self.vollbild:
            cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.window_name, 1280, 720)
        
        cv2.imshow(self.window_name, pause_frame)
        cv2.waitKey(100)

    def check_keys(self, frame_start_time):
        # OpenCV bekommt rigoros nur 1 Millisekunde, um das GUI zu updaten und Keys abzufangen!
        raw_key = cv2.waitKeyEx(1)
        key = raw_key & 0xFF
        
        # ---> NEU: Der sanfte FPS-Limiter (falls die Kamera unendlich schnell liefert)
        if self.fps_limit > 0:
            target_duration = 1.0 / self.fps_limit
            elapsed = time.perf_counter() - frame_start_time
            if elapsed < target_duration:
                # time.sleep verbrät keine CPU-Last, bremst aber virtuelle Kameras sauber ein
                time.sleep(target_duration - elapsed)
        
        if self.trigger_exit:
            return True

        # =========================================================================
        # ---> DER ZOMBIE-FIX: Prüfen, ob das Fenster über das 'X' geschlossen wurde!
        # =========================================================================
        try:
            if cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1:
                self.log("SYSTEM", "Fenster über 'X' geschlossen. Beende TargetVision...")
                return True
        except cv2.error:
            # Fallback, falls OpenCV beim Prüfen eines toten Fensters meckert
            return True

        if key == ord('q'): return True
        elif key == ord('r'):
            if self.nutze_kamera_links: self.trigger_reset_left = True
            if self.nutze_kamera_rechts: self.trigger_reset_right = True

        if raw_key in (2490368, 65362, 2621440, 65364, 2424832, 65361, 2555904, 65363) or key in (ord('w'), ord('a'), ord('s'), ord('d')):
            current_time = time.time()
            
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
                if raw_key in (2490368, 65362) or key == ord('w'):   dy = -0.2
                elif raw_key in (2621440, 65364) or key == ord('s'): dy =  0.2
                elif raw_key in (2424832, 65361) or key == ord('a'): dx = -0.2
                elif raw_key in (2555904, 65363) or key == ord('d'): dx =  0.2
                
                new_x = round(active_fb['cx'] + dx, 3)
                new_y = round(active_fb['cy'] + dy, 3)
                
                self.sm.set_nullpunkt(active_side, new_x, new_y)
                
                active_fb['cx'] = new_x
                active_fb['cy'] = new_y
                active_fb['time'] = current_time 
                
                for shot in self.sm.shots:
                    if shot['side'] == active_side:
                        new_score, raw_score = self.sm.calculate_score(active_side, shot['pos'][0], shot['pos'][1])
                        shot['score'] = new_score
                        shot['raw_score'] = raw_score
                        
                self.log("SYSTEM", f"🎯 Zentrum {active_side.upper()} feinjustiert: X:{new_x:.3f} Y:{new_y:.3f}", True)

        return False

    def cleanup(self):
        self.dm.flush_image_queue()
        if self.nutze_kamera_links: self.cap_left.release()
        if self.nutze_kamera_rechts: self.cap_right.release()
        cv2.destroyAllWindows()

    def on_mouse_click(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            if getattr(self, 'active_picker', None) is not None:
                s = self.active_picker['side']
                mode = self.active_picker.get('mode', 'edit') 
                
                raw_x = (x - self.renderer.pad_x) / self.renderer.scale_x
                raw_y = (y - self.renderer.pad_y) / self.renderer.scale_y
                
                if s == 'right' and self.nutze_kamera_links:
                    raw_x -= self.renderer.w_left_displayed
                    
                if (s == 'left' and raw_x > self.renderer.w_left_displayed and self.nutze_kamera_rechts) or \
                   (s == 'right' and raw_x < 0):
                    self.log("SYSTEM", "⚠️ Klick war auf der falschen Seite! Bitte nochmal.", True)
                    return
                
                raw_x = max(0.0, raw_x)
                picked_x, picked_y = int(raw_x), int(raw_y)
                
                if mode == 'center':
                    self.sm.set_nullpunkt(s, picked_x, picked_y)
                    self.log("SYSTEM", f"🎯 Neues Zentrum {s.upper()} gesetzt: X:{picked_x} Y:{picked_y}", True)
                    
                    old_fb = self.calib_feedback_left if s == 'left' else self.calib_feedback_right
                    new_fb = {
                        'cx': picked_x, 'cy': picked_y,
                        'red_cx': picked_x, 'red_cy': picked_y,
                        'ideal_rx': old_fb['ideal_rx'] if old_fb else 150, 
                        'ideal_ry': old_fb['ideal_ry'] if old_fb else 150,
                        'red_rx': 0, 'red_ry': 0,
                        'show_red': False,
                        'time': time.time() 
                    }
                    if s == 'left': self.calib_feedback_left = new_fb
                    else: self.calib_feedback_right = new_fb
                        
                    for shot in self.sm.shots:
                        if shot['side'] == s:
                            new_score, raw_score = self.sm.calculate_score(s, shot['pos'][0], shot['pos'][1])
                            shot['score'] = new_score
                            shot['raw_score'] = raw_score
                            
                    self.active_picker = None 
                    return
                else:
                    self.picked_coords = (picked_x, picked_y) 
                    self.picked_coords_ready = True
                    self.log("SYSTEM", f"✅ Koordinaten für Treffer übernommen!", True)
                    return
                
        if event == cv2.EVENT_LBUTTONDOWN:
            if self.renderer.btn_exit_coords:
                ex1, ey1, ex2, ey2 = self.renderer.btn_exit_coords
                if ex1 <= x <= ex2 and ey1 <= y <= ey2:
                    self.trigger_exit = True
                    return
            
            if getattr(self.renderer, 'btn_zip_coords', None):
                zx1, zy1, zx2, zy2 = self.renderer.btn_zip_coords
                if zx1 <= x <= zx2 and zy1 <= y <= zy2:
                    self.log("SYSTEM", "Generiere Debug-Paket... Bitte warten.", True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    zip_filepath = os.path.join(self.dm.ZIP_FOLDER, f"Debug_Paket_{timestamp}.zip")
                    self.dm.flush_image_queue()
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
            
            if self.nutze_kamera_links and getattr(self.renderer, 'btn_left_coords', None):
                bx1, by1, bx2, by2 = self.renderer.btn_left_coords
                if bx1 <= x <= bx2 and by1 <= y <= by2:
                    self.trigger_reset_left = True
                    return
            
            if self.nutze_kamera_rechts and getattr(self.renderer, 'btn_right_coords', None):
                bx1, by1, bx2, by2 = self.renderer.btn_right_coords
                if bx1 <= x <= bx2 and by1 <= y <= by2:
                    self.trigger_reset_right = True
                    return
            
            if self.nutze_kamera_links and getattr(self.renderer, 'btn_edit_left_coords', None):
                ex1, ey1, ex2, ey2 = self.renderer.btn_edit_left_coords
                if ex1 <= x <= ex2 and ey1 <= y <= ey2:
                    self.trigger_edit_left = True
                    return
            
            if self.nutze_kamera_rechts and getattr(self.renderer, 'btn_edit_right_coords', None):
                ex1, ey1, ex2, ey2 = self.renderer.btn_edit_right_coords
                if ex1 <= x <= ex2 and ey1 <= y <= ey2:
                    self.trigger_edit_right = True
                    return
            
            if self.nutze_kamera_links and getattr(self.renderer, 'btn_center_left_coords', None):
                cx1, cy1, cx2, cy2 = self.renderer.btn_center_left_coords
                if cx1 <= x <= cx2 and cy1 <= y <= cy2:
                    self.active_picker = {'mode': 'center', 'side': 'left'}
                    self.log("SYSTEM", "🎯 Klicke ins LINKE Kamerabild, um das neue Zentrum zu setzen!", True)
                    return
            
            if self.nutze_kamera_rechts and getattr(self.renderer, 'btn_center_right_coords', None):
                cx1, cy1, cx2, cy2 = self.renderer.btn_center_right_coords
                if cx1 <= x <= cx2 and cy1 <= y <= cy2:
                    self.active_picker = {'mode': 'center', 'side': 'right'}
                    self.log("SYSTEM", "🎯 Klicke ins RECHTE Kamerabild, um das neue Zentrum zu setzen!", True)
                    return
            
            if getattr(self.renderer, 'btn_highscore_coords', None):
                hx1, hy1, hx2, hy2 = self.renderer.btn_highscore_coords
                if hx1 <= x <= hx2 and hy1 <= y <= hy2:
                    self.log("SYSTEM", "Öffne Highscore-Tabelle...", True)
                    
                    self.show_pause_screen("Highscore-Tabelle geöffnet")
                        
                    proc = subprocess.Popen(["python", "HighscoreViewDeLuebs.py"])
                    while proc.poll() is None:
                        cv2.waitKey(100)
                        
                    if self.vollbild:
                        cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                        cv2.waitKey(50)
                    return
                    
            if getattr(self.renderer, 'btn_save_coords', None):
                sx1, sy1, sx2, sy2 = self.renderer.btn_save_coords
                if sx1 <= x <= sx2 and sy1 <= y <= sy2:
                    self.log("SYSTEM", "Frage nach Spielername...")
                    
                    player_counts = {}
                    for entry in self.sm.hm.data:
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
                    
                    if player_name_l and not player_name_r:
                        player_name_r = player_name_l
                    
                    if player_name_l and player_name_r:
                        self.last_player_name_l = player_name_l
                        self.last_player_name_r = player_name_r if player_name_l != player_name_r else ""
                        
                        log_msg = f"Speichere Match für {player_name_l} / {player_name_r}..." if player_name_l != player_name_r else f"Speichere Match für {player_name_l}..."
                        self.log("SYSTEM", log_msg, True)
                        
                        backup_mask_l = self.sm.state_left.cumulative_mask.copy() if (self.nutze_kamera_links and self.sm.state_left and self.sm.state_left.cumulative_mask is not None) else None
                        backup_mask_r = self.sm.state_right.cumulative_mask.copy() if (self.nutze_kamera_rechts and self.sm.state_right and self.sm.state_right.cumulative_mask is not None) else None
                        
                        self.dm.flush_image_queue()
                        
                        path_l = os.path.join(self.dm.DEBUG_FOLDER, "letzte_aufnahme_left.png")
                        if not os.path.exists(path_l): path_l = os.path.join(self.dm.DEBUG_FOLDER, "referenz_left.png")
                        best_orig_l = cv2.imread(path_l) if os.path.exists(path_l) else None

                        path_r = os.path.join(self.dm.DEBUG_FOLDER, "letzte_aufnahme_right.png")
                        if not os.path.exists(path_r): path_r = os.path.join(self.dm.DEBUG_FOLDER, "referenz_right.png")
                        best_orig_r = cv2.imread(path_r) if os.path.exists(path_r) else None
                        
                        if self.sm.save_current_match(player_name_l, player_name_r):
                            self.log("SYSTEM", "Match erfolgreich gespeichert!", True)
                            
                            if self.nutze_kamera_links: self.dm.clear_debug_images('left', keep_startmask=True)
                            if self.nutze_kamera_rechts: self.dm.clear_debug_images('right', keep_startmask=True)
                            
                            if self.nutze_kamera_links and self.sm.state_left:
                                self.sm.state_left.cumulative_mask = backup_mask_l
                                if backup_mask_l is not None:
                                    self.dm.save_debug_image("cumulative_startmask_left", backup_mask_l)
                                    if best_orig_l is not None:
                                        self.dm.save_debug_image("cumulative_orig_left", best_orig_l)
                                    self.sm.state_left.is_fortsetzung = True 
                                    
                            if self.nutze_kamera_rechts and self.sm.state_right:
                                self.sm.state_right.cumulative_mask = backup_mask_r
                                if backup_mask_r is not None:
                                    self.dm.save_debug_image("cumulative_startmask_right", backup_mask_r)
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

            if getattr(self.renderer, 'btn_labor_coords', None):
                lx1, ly1, lx2, ly2 = self.renderer.btn_labor_coords
                if lx1 <= x <= lx2 and ly1 <= y <= ly2:
                    
                    if getattr(self, 'labor_is_opening', False): 
                        return
                    self.labor_is_opening = True
                    
                    ref_l = self.sm.state_left and self.sm.state_left.is_initialized
                    ref_r = self.sm.state_right and self.sm.state_right.is_initialized
                    
                    if not ref_l and not ref_r:
                        self.log("SYSTEM", "Labor startet leer (Noch keine Scheibe erkannt).", True)
                        
                        self.show_pause_screen("Labor & Einstellungen geöffnet")
                            
                        proc = subprocess.Popen(["python", "LaborDeLuebs.py"])
                        while proc.poll() is None:
                            cv2.waitKey(100)
                            
                        if self.vollbild:
                            cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                            
                        self.labor_is_opening = False
                        return
                    
                    self.log("SYSTEM", "Generiere Live-Snapshot und pausiere System...", True)
                    self.renderer.update_gui(self.last_frame_l, self.last_frame_r, True)
                    cv2.waitKey(50) 
                    
                    self.show_pause_screen("Labor & Einstellungen geöffnet")
                    
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
                        
                        proc = subprocess.Popen(["python", "LaborDeLuebs.py", zip_filepath])
                        while proc.poll() is None:
                            cv2.waitKey(100) 
                            
                        if self.vollbild:
                            cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                            cv2.waitKey(50)
                        
                        handover_path = os.path.join(export_dir, "Live_Tuning_Handover.zip")
                        if os.path.exists(handover_path):
                            self.log("SYSTEM", "Labor-Handover gefunden! Lade Parameter...", True)
                            self.apply_handover(handover_path)
                            os.remove(handover_path)
                            self.log("SYSTEM", "Live-System erfolgreich aktualisiert!", True)
                        else:
                            self.log("SYSTEM", "Labor ohne Übernahme geschlossen.", True)
                            
                        self.dm.flush_image_queue() 
                        try:
                            if hasattr(self.dm, 'DEBUG_FOLDER') and os.path.exists(self.dm.DEBUG_FOLDER):
                                for f in os.listdir(self.dm.DEBUG_FOLDER):
                                    if f.startswith("ZZZ_Live_Snapshot"):
                                        os.remove(os.path.join(self.dm.DEBUG_FOLDER, f))
                        except Exception:
                            pass
                            
                        for _ in range(10): 
                            if self.nutze_kamera_links: self.cap_left.read()
                            if self.nutze_kamera_rechts: self.cap_right.read()
                            
                    else:
                        self.log("SYSTEM", "Fehler beim ZIP-Export. Starte Labor leer.", True)
                        subprocess.Popen(["python", "LaborDeLuebs.py"])
                        
                    self.labor_is_opening = False
                    return
            
            if getattr(self.renderer, 'btn_hilfe_coords', None):
                hx1, hy1, hx2, hy2 = self.renderer.btn_hilfe_coords
                if hx1 <= x <= hx2 and hy1 <= y <= hy2:
                    self.log("SYSTEM", "Öffne Handbuch...", True)
                    
                    self.show_pause_screen("Handbuch geöffnet")
                    
                    proc = subprocess.Popen(["python", "HandbuchDeLuebs.py"]) 
                    
                    while proc.poll() is None:
                        cv2.waitKey(100)
                        
                    if self.vollbild:
                        cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                        cv2.waitKey(50)
                        
                    return
                    
            if getattr(self.renderer, 'btn_rings_coords', None):
                rx1, ry1, rx2, ry2 = self.renderer.btn_rings_coords
                if rx1 <= x <= rx2 and ry1 <= y <= ry2:
                    self.renderer.show_all_rings = not self.renderer.show_all_rings
                    self.log("SYSTEM", f"Zielscheiben-Ringe dauerhaft {'aktiviert' if self.renderer.show_all_rings else 'deaktiviert'}.", True)
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

        self.show_pause_screen(f"Treffer bearbeiten - {'Links' if side=='left' else 'Rechts'}")

        root_dialog = tk.Tk()
        root_dialog.withdraw()
        dialog = tk.Toplevel(root_dialog)
        dialog.title(f"Treffer bearbeiten - {'Links' if side=='left' else 'Rechts'}")
        dialog.geometry("550x450")
        
        dialog.focus_force()

        top_frame = tk.Frame(dialog)
        top_frame.pack(fill="x", padx=10, pady=5)
        
        select_all_var = tk.BooleanVar(value=False)
        check_vars = []
        entries = []  

        def toggle_all():
            state = select_all_var.get()
            for var in check_vars:
                var.set(state)

        tk.Checkbutton(top_frame, text="Alle markieren", variable=select_all_var, command=toggle_all).pack(side="left")

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

        header_frame = tk.Frame(scrollable_frame)
        header_frame.pack(fill="x", pady=(0, 5))
        tk.Label(header_frame, text="Löschen", width=7).grid(row=0, column=0)
        tk.Label(header_frame, text="Nr.", width=4).grid(row=0, column=1)
        tk.Label(header_frame, text="X (px)", width=10).grid(row=0, column=2)
        tk.Label(header_frame, text="Y (px)", width=10).grid(row=0, column=3)
        tk.Label(header_frame, text="Ringe", width=10).grid(row=0, column=4)
        tk.Label(header_frame, text="Pick", width=5).grid(row=0, column=5) 

        for i, shot in enumerate(side_shots):
            row_frame = tk.Frame(scrollable_frame)
            row_frame.pack(fill="x", pady=2)

            c_var = tk.BooleanVar(value=False)
            check_vars.append(c_var)
            tk.Checkbutton(row_frame, variable=c_var, width=5).grid(row=0, column=0)

            tk.Label(row_frame, text=str(i+1), width=4).grid(row=0, column=1)

            x_var = tk.StringVar(value=str(round(float(shot['pos'][0]), 1)))
            tk.Entry(row_frame, textvariable=x_var, width=10).grid(row=0, column=2, padx=5)

            y_var = tk.StringVar(value=str(round(float(shot['pos'][1]), 1)))
            tk.Entry(row_frame, textvariable=y_var, width=10).grid(row=0, column=3, padx=5)

            score_var = tk.StringVar(value=str(shot.get('score', 0.0)))
            tk.Entry(row_frame, textvariable=score_var, width=10).grid(row=0, column=4, padx=5)

            def make_pick_cmd(xv, yv, sv, s_name):
                def cmd():
                    self.active_picker = {'x_var': xv, 'y_var': yv, 'score_var': sv, 'side': s_name}
                    self.log("SYSTEM", f"🎯 Klicke nun in das {s_name.upper()} Kamerabild!", True)
                return cmd

            tk.Button(row_frame, text="🎯", bg="#5bc0de", fg="black", command=make_pick_cmd(x_var, y_var, score_var, side)).grid(row=0, column=5, padx=2)
            entries.append((shot, x_var, y_var, score_var, c_var))

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(fill="x", pady=10)

        def apply_changes():
            to_delete = []
            for item in entries:
                shot_ref, x_var, y_var, score_var, c_var = item
                if c_var.get():
                    to_delete.append(shot_ref)
                else:
                    try:
                        new_x = float(x_var.get())
                        new_y = float(y_var.get())
                        new_score = float(score_var.get())
                        self.sm.update_shot(shot_ref, new_x, new_y, new_score)
                    except ValueError:
                        self.log("SYSTEM", "Fehlerhafte Eingabe ignoriert.")

            if to_delete:
                self.sm.remove_shots(to_delete)

            if hasattr(dialog, 'poll_job'):
                dialog.after_cancel(dialog.poll_job)
            dialog.destroy()

        def cancel():
            if hasattr(dialog, 'poll_job'):
                dialog.after_cancel(dialog.poll_job)
            dialog.destroy()
            
        dialog.protocol("WM_DELETE_WINDOW", cancel)

        tk.Button(btn_frame, text="Übernehmen & Löschen", command=apply_changes, bg="#4CAF50", fg="white", font=('Arial', 10, 'bold')).pack(side="left", padx=20)
        tk.Button(btn_frame, text="Abbrechen", command=cancel, font=('Arial', 10)).pack(side="right", padx=20)

        def poll_picker():
            try:
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
                    
                dialog.poll_job = dialog.after(100, poll_picker)
            except Exception:
                pass 
                
        poll_picker() 

        root_dialog.wait_window(dialog)
        root_dialog.destroy()
        
        if self.vollbild:
            cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            cv2.waitKey(50)
        
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
            frame_start_time = time.perf_counter() 
            
            frame_l, frame_r = self.read_frames()
            self.last_frame_l = frame_l 
            self.last_frame_r = frame_r 
            
            self.process_resets(frame_l, frame_r)
            self.process_edits()
            
            if self.nutze_kamera_links: self.process_camera(frame_l, self.sm.state_left)
            if self.nutze_kamera_rechts: self.process_camera(frame_r, self.sm.state_right)
            
            if time.time() - blink_timer > 0.3:
                blink_state = not blink_state
                blink_timer = time.time()
            
            self.renderer.update_gui(frame_l, frame_r, blink_state)
            
            if self.check_keys(frame_start_time):
                break

        self.cleanup()

if __name__ == "__main__":
    dm = DateiManager(clear_on_start=True)
    config = dm.load_or_create_config()
    sm = StateManager(config, dm)
    
    tracker = TargetTracker(config, dm, sm)
    tracker.run()