import sys
import math 
import os
import time
import json
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
#import zipfile
import cv2
import numpy as np
import configparser
import io
from PIL import Image, ImageTk
import shutil
import copy
from datetime import datetime

# ---> HIER IMPORTIEREN WIR DEINE ECHTE ENGINE UND DEN MANAGER! <---
from DetectionDeLuebs import TargetDetector
from LaborRendererDeLuebs import LaborRenderer
from LaborUIDeLuebs import LaborUIBuilder

from LaborContextDeLuebs import LaborContext, FrameContext  # <--- DIESE ZEILE NEU HINZUFÜGEN!

from DateiManagerDeLuebs import DateiManager
from StateManagerDeLuebs import StateManager
from KalibrierungDeLuebs import Kalibrator
import tools.KameraTestAdvaced as KameraTestAdvaced
import tools.MatchIntegrity as MatchIntegrity  # <--- NEU

#import LoggerDeLuebs
#from HandbuchDeLuebs import PARAMETER_LEXIKON

           
#class DummyDateiManager:
#    def __init__(self, app):
#        self.app = app
#        self.debug_images = {}
#        self.export_folder = "labor_export"
#        
#    def get_current_version(self):
#        """Leitet die Versionsabfrage an den echten DateiManager weiter."""
#        return self.app.dm.get_current_version()
#        
#    def save_debug_image(self, name, image):
#        self.debug_images[name] = image.copy()
#        if self.app.export_images_var.get():
#            import os
#            import cv2
#            if not os.path.exists(self.export_folder):
#                os.makedirs(self.export_folder)
#            path = os.path.join(self.export_folder, f"{name}.png")
#            cv2.imwrite(path, image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
#            return True  # <--- NEU: Meldet "Ja, physisch auf Festplatte exportiert!"
#            
#        return False # <--- NEU: Meldet "Wurde nur stumm im RAM abgelegt."
#            
#    def load_targets(self):
#        # 1. PRIO: Nutze zwingend die historische zielscheiben.json aus dem ZIP-Archiv (Zeitkapsel)!
#        if getattr(self.app, 'package_data', None) and self.app.package_data.get('targets'):
#            return self.app.package_data['targets']
#            
#        # 2. FALLBACK: Das ZIP ist von früher und hat keine JSON an Bord. 
#        # Wir nehmen die tagesaktuelle aus der Gegenwart von der Festplatte.
#        return self.app.dm.load_targets()
#        
#    def write_log(self, msg):
#        # ---> NEU: Stummschaltung für den StateManager <---
#        pass


# ==========================================
# GUI UND LOGIK
# ==========================================
class LaborApp:
    def __init__(self, root):
        self.root = root
        self.renderer = LaborRenderer(self)
        self.ui_builder = LaborUIBuilder(self)
        self.kalibrator = Kalibrator(self) # <--- NEU: Der Kalibrator ist jetzt eingezogen!
        
        self.root.title("Labor & Einstellungen")
        
        # ---> NEU: ELA-Türsteher (Zeichenfilter) für alle Textfelder registrieren <---
        self.vcmd_float = (self.root.register(self.validate_float_chars), '%P')
        self.vcmd_int = (self.root.register(self.validate_int_chars), '%P')
        
        # ---> NEU: Fenstergröße dynamisch an die Windows-Skalierung (z.B. 200%) anpassen <---
        # 96 DPI ist der Standardwert (100%). Liefert der Bildschirm mehr, wächst das Fenster proportional mit.
        skalierungs_faktor = self.root.winfo_fpixels('1i') / 96.0 
        w, h = int(1400 * skalierungs_faktor), int(850 * skalierungs_faktor)
        self.root.geometry(f"{w}x{h}")
        
        # ---> NEU: Labor direkt maximiert starten! <---
        try:
            self.root.state('zoomed') # Standard für Windows
        except tk.TclError:
            self.root.attributes('-zoomed', True) # Fallback für Linux
            
        
        self.dm = DateiManager() # <--- NEU: Unser zentraler ELA-Werkzeugkasten
        self.package_data = None # <--- NEU: Speichert das entpackte ZIP im RAM
        
        self.labor_context = LaborContext(None, self.dm)  # <--- SEIDEN-MUSTER: Unser neuer Manager!
        
        
        self.current_zip_path = None
        self.all_files = []
        self.orig_files = []
        self.current_index = 0
        self.tk_image = None
        self.export_images_var = tk.BooleanVar(value=False)
        
        # TK-Variablen für Slider
        self.hit_tolerance_var = tk.IntVar(value=22)
        self.min_hole_area_var = tk.IntVar(value=25)
        # ---> NEU: Jetzt in Millimetern und mit Float (2 Nachkommastellen) <---
        self.caliber_durchmesser_var = tk.DoubleVar(value=4.50)
        #self.caliber_radius_var = tk.IntVar(value=11)
        #self.hybrid_riss_faktor_var = tk.DoubleVar(value=1.175)
        #self.hybrid_sichel_faktor_var = tk.DoubleVar(value=1.05)
        self.discard_big_hits_var = tk.DoubleVar(value=2.5)
        self.hough_min_faktor_var = tk.DoubleVar(value=0.85)
        self.hough_max_faktor_var = tk.DoubleVar(value=1.15)
        self.hough_param1_var = tk.IntVar(value=25)
        self.hough_param2_var = tk.IntVar(value=4)
        # ---> NEU <---
        self.morph_kernel_var = tk.IntVar(value=5)
        self.blur_kernel_size_var = tk.IntVar(value=7) # <--- NEU
        self.randaufschlag_cumulative_var = tk.IntVar(value=0) # <--- NEU: Default 0
        self.max_aspect_ratio_var = tk.DoubleVar(value=3.5)
        # ---> NEU <---
        self.gesamt_anteil_am_200score_var = tk.DoubleVar(value=0.667)
        self.abriss_max_edge_percent_var = tk.DoubleVar(value=0.75)
        self.abriss_base_bonus_var = tk.DoubleVar(value=10.0)
        #self.early_exit_min_score_var = tk.DoubleVar(value=145.0)
        #self.early_exit_perfect_score_var = tk.DoubleVar(value=196.0)
        self.min_score_valid_var = tk.DoubleVar(value=70.0)
        self.clipping_factor_history_var = tk.DoubleVar(value=0.15)
        self.clipping_factor_current_var = tk.DoubleVar(value=0.95)
        # ---> NEU: Variable für den Filter <---
        self.max_treffer_je_frame_var = tk.IntVar(value=0)
        #self.detail_export_aktiv_var = tk.BooleanVar(value=False) # <--- NEU
        # ---> NEU: Farb-Bonus System <---
        self.farb_bonus_aktiv_var = tk.BooleanVar(value=False)
        self.farb_bonus_limit_var = tk.DoubleVar(value=150.0)
        self.farb_bonus_kurve_var = tk.DoubleVar(value=2.00)
        
        # ---> NEU: Die Ringwertung Nachkommastellen <---
        self.ringwertung_nachkommastellen_var = tk.IntVar(value=1)
        
        # ---> NEU: Die Eintrittskarten für das Battle Royale <---
        self.grenzwert_hough_var = tk.DoubleVar(value=7.0)
        self.abriss_min_hebel_var = tk.DoubleVar(value=0.0)
        
        self.zoom_factor = 1.0
        self.max_zoom_factor = 12.5  # <--- NEU: Zentrales Limit für extremen Deep-Zoom
        self.pan_x = 0
        self.pan_y = 0
        self.view_mode_var = tk.IntVar(value=1) # <--- HIER AUCH ÄNDERN
        
        # ---> NEU: Dynamisches Dictionary für alle Slider und deren Variablen <---
        self.registered_sliders = {}
        
        self.ui_builder.setup_ui()
        
        # =========================================================================
        # ---> FIX: Navigation auch auf dem grauen Hintergrund erlauben! <---
        # =========================================================================
        if hasattr(self, 'img_container'):
            # 1. Rechtsklick (Auto-Fit) auf dem nackten Hintergrund
            self.img_container.bind("<Button-3>", self.reset_view)
            
            # 2. Panning-Rettungsanker: Erlaubt das "Zurückziehen" des Bildes ins Sichtfeld!
            self.img_container.bind("<ButtonPress-1>", self.on_drag_start)
            self.img_container.bind("<B1-Motion>", self.on_drag_motion)
            self.img_container.bind("<ButtonRelease-1>", self.on_drag_stop)
        
        # ---> NEU: Initialisierung für das Blink-Overlay <---
        self.blink_state = True
        self._toggle_blink()
        self.last_mouse_x = None
        self.last_mouse_y = None
        self.drag_start_x = None
        self.drag_start_y = None
        # ---> Strg-Tasten global überwachen (Plattformunabhängig) <---
        self.is_zoom_box_active = False
        self.ctrl_is_pressed = False
        #self.root.bind('<Control_L>', lambda e: setattr(self, 'ctrl_is_pressed', True))
        #self.root.bind('<Control_R>', lambda e: setattr(self, 'ctrl_is_pressed', True))
        #self.root.bind('<KeyRelease-Control_L>', lambda e: setattr(self, 'ctrl_is_pressed', False))
        #self.root.bind('<KeyRelease-Control_R>', lambda e: setattr(self, 'ctrl_is_pressed', False))
        
        
    def _toggle_blink(self):
        """Kippt das Blink-Flag alle 1000ms und erzwingt einen GUI-Redraw."""
        old_state = getattr(self, 'blink_state', True)
        
        # Dauer-Leuchten bei Zoom >= 4.0, normales Blinken bei < 4.0
        if getattr(self, 'zoom_factor', 1.0) >= 4.0:
            new_state = True
        else:
            new_state = not old_state
            
        self.blink_state = new_state
        
        # =========================================================================
        # ---> DER GENIALE FIX: Wir rendern nur, wenn sich WIRKLICH was ändert! <---
        # =========================================================================
        if old_state == new_state:
            # Das Bild sieht exakt so aus wie vor 1 Sekunde. 
            # Wir sparen uns 100% CPU-Last und würgen den Render-Zyklus hier ab!
            self.root.after(1000, self._toggle_blink)
            return
        
        if getattr(self, 'base_combined_img', None) is not None:
            # Blockiert das Blinken bei JEGLICHER Interaktion (Zoom, Panning)! 
            if self.is_interacting:
                self.root.after(1000, self._toggle_blink)
                return

            mx = getattr(self, 'last_mouse_x', None)
            my = getattr(self, 'last_mouse_y', None)
            
            if mx is not None and my is not None:
                # Bild stumm im Hintergrund (RAM) updaten, OHNE es an Tkinter zu senden
                self.renderer.update_image_display(full_rebuild=False, push_to_gui=False)
                # Das Fadenkreuz übernimmt den fertigen RGB-Cache und schickt ihn an Tkinter
                self.renderer.draw_crosshair(mx, my)
            else:
                # Maus ist nicht im Bild -> Normal updaten
                self.renderer.update_image_display(full_rebuild=False, push_to_gui=True)
            
        self.root.after(1000, self._toggle_blink)

    @property
    def is_interacting(self):
        """
        Zentraler Schalter: Gibt True zurück, wenn der User gerade aktiv zieht, 
        zoomt oder Parameter (Slider/WASD) verändert.
        """
        is_zooming = getattr(self, 'is_zoom_box_active', False)
        is_panning = getattr(self, 'drag_start_x', None) is not None
        is_tweaking = getattr(self, '_param_timer', None) is not None
        return is_zooming or is_panning or is_tweaking

    #def toggle_orig_hits(self):
    #    """Schaltet die Original-Treffer ohne Engine-Neuberechnung um."""
    #    if hasattr(self, 'renderer'):
    #        self.renderer.update_image_display(full_rebuild=True)

        
    def validate_float_chars(self, P):
        """Erlaubt nur Ziffern, Punkt, Minus, Plus und E (für wissenschaftliche Notation)"""
        return all(c in "0123456789+-.eE" for c in P)
        
    def validate_int_chars(self, P):
        """Erlaubt nur Ziffern, Plus und Minus"""
        return all(c in "0123456789+-" for c in P)

    def update_calib_sliders(self):
        """Holt die echten Config-Werte der aktuell aktiven Kamera in die GUI-Slider"""
        if getattr(self, 'package_data', None) and self.package_data.get('config'):
            config_ram = self.package_data['config']
            side = self.active_camera_var.get()
            seite_str = "links" if side == 'left' else "rechts"
            
            # ---> NEU: LabelFrame Titel anpassen <---
            if hasattr(self, 'calib_outer_frame'):
                self.calib_outer_frame.config(text=f" Kalibrierung: Kamera {seite_str.capitalize()} ")
            
            # ---> NEU: Sektion sicherstellen, anstatt bei Fehlen abzubrechen! <---
            if not config_ram.has_section('Kameras'):
                config_ram.add_section('Kameras')
                
            val_x = config_ram.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
            val_y = config_ram.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
            val_fisch = config_ram.getfloat('Kameras', f'linsen_verzerrung_{seite_str}', fallback=0.0) 
            val_r4 = config_ram.getfloat('Kameras', f'linsen_verzerrung_{seite_str}_r4', fallback=0.0) 
            
            val_off_x = config_ram.getint('Kameras', f'lens_offset_x_{seite_str}', fallback=0)
            val_off_y = config_ram.getint('Kameras', f'lens_offset_y_{seite_str}', fallback=0)
            val_limit = config_ram.getfloat('Kameras', f'linsen_verzerrung_limit_{seite_str}', fallback=0.0) # <--- NEU
            
            if hasattr(self, 'orig_calib'):
                self.original_values[str(self.calib_x_var)] = self.orig_calib[f"{side}_x"]
                self.original_values[str(self.calib_y_var)] = self.orig_calib[f"{side}_y"]
                self.original_values[str(self.calib_linsen_verzerrung_var)] = self.orig_calib.get(f"{side}_fisch", 0.0) 
                self.original_values[str(self.calib_linsen_verzerrung_r4_var)] = self.orig_calib.get(f"{side}_r4", 0.0) 
                self.original_values[str(self.calib_lens_offset_x_var)] = self.orig_calib.get(f"{side}_off_x", 0)
                self.original_values[str(self.calib_lens_offset_y_var)] = self.orig_calib.get(f"{side}_off_y", 0)
                self.original_values[str(self.calib_linsen_verzerrung_limit_var)] = self.orig_calib.get(f"{side}_limit", 0.0) # <--- NEU

            #self._updating_calib_sliders = True
            #try:
            self.calib_x_var.set(val_x)
            self.calib_y_var.set(val_y)
            self.calib_linsen_verzerrung_var.set(val_fisch)
            self.calib_linsen_verzerrung_r4_var.set(val_r4)
            self.calib_lens_offset_x_var.set(val_off_x)
            self.calib_lens_offset_y_var.set(val_off_y)
            self.calib_linsen_verzerrung_limit_var.set(val_limit) # <--- NEU
            #finally:
            #    self._updating_calib_sliders = False

            
    def switch_camera(self):
        """Wird aufgerufen, wenn man zwischen Links/Rechts umschaltet."""
        self.current_index = 0 # Zurück auf Start!
        self.update_calib_sliders() 
        #self.auto_zoom_and_center() # <--- NEU: Beim Seitenwechsel direkt wieder zentrieren!
        self.process_and_display()

    def get_current_side_origs(self):
        """Gibt nur die Original-Schüsse der aktuell gewählten Kamera zurück."""
        side = self.active_camera_var.get()
        return sorted([f for f in self.orig_files if side in f])


    def print_log(self, side, msg, show_gui=False):
        """Zentrale Log-Ausgabe für Engine und UI (optional ohne Seiten-Präfix bei side=None)"""
        clean_msg = msg.rstrip('\n')
        prefix = f"[{side.upper()}] " if side else ""
        
        self.log_text.insert(tk.END, f"{prefix}{clean_msg}\n", "mono")
        
        if not getattr(self, '_is_batch_calculating', False):
            self.log_text.see(tk.END)



    def apply_config_to_ui(self, config_ram):
        """Zentrale Methode: Füttert alle UI-Slider mit den Werten eines Configconfig_rams."""
        if config_ram:
            if not config_ram.has_section('Erkennung'):
                config_ram.add_section('Erkennung')
                
            self.original_values = {}
            
            # 1. SONDERFALL: Nur noch Legacy-Migration für Uralt-Configs (Pixel zu mm)
            if not config_ram.has_option('Erkennung', 'caliber_durchmesser') and config_ram.has_option('Erkennung', 'caliber_radius'):
                alt_r = config_ram.getfloat('Erkennung', 'caliber_radius', fallback=15.0)
                px_x = config_ram.getfloat('Kameras', 'px_pro_mm_x_links', fallback=5.0) if config_ram.has_section('Kameras') else 5.0
                px_y = config_ram.getfloat('Kameras', 'px_pro_mm_y_links', fallback=5.0) if config_ram.has_section('Kameras') else 5.0
                avg_px = (px_x + px_y) / 2.0
                calc_durchmesser = (alt_r / avg_px) * 2.0 if avg_px > 0 else 4.5
                config_ram.set('Erkennung', 'caliber_durchmesser', str(round(calc_durchmesser, 2)))

            # 2. DIE MAGIE: Automatische Zuweisung ALLER registrierten Slider
            self.migrated_keys = [] # <--- NEU: Merkliste für den Migrator
            
            # =========================================================================
            # ---> DER FIX: Den Slider-losen Parameter einfach mit auf die Liste packen! <---
            # !!!!!!!!!!!!!!!!!!!!!! DIE ECHTE LAZY INJECTION !!!!!!!!!!!!!!!!!!!!!!
            # =========================================================================
            if not config_ram.has_section('Zielscheibe'):
                config_ram.add_section('Zielscheibe')
            if not config_ram.has_option('Zielscheibe', 'ringwertung_nachkommastellen'):
                config_ram.set('Zielscheibe', 'ringwertung_nachkommastellen', '1')
                self.migrated_keys.append('ringwertung_nachkommastellen')
            if not config_ram.has_section('Erkennung'):
                config_ram.add_section('Erkennung')
            if not config_ram.has_option('Erkennung', 'detail_export_aktiv'):
                config_ram.set('Erkennung', 'detail_export_aktiv', 'no')
                self.migrated_keys.append('detail_export_aktiv')
            if not config_ram.has_option('Erkennung', 'verschiebungskorrektur'):
                config_ram.set('Erkennung', 'verschiebungskorrektur', 'no')
                self.migrated_keys.append('verschiebungskorrektur')            
            if not config_ram.has_option('Kameras', 'kamera_backend'):
                config_ram.set('Kameras', 'kamera_backend', 'AUTO')
                self.migrated_keys.append('kamera_backend')
            if not config_ram.has_option('Kameras', 'kamera_codec'):
                config_ram.set('Kameras', 'kamera_codec', 'MJPG')
                self.migrated_keys.append('kamera_codec')
            if not config_ram.has_option('Kameras', 'kamera_init_modus'):
                config_ram.set('Kameras', 'kamera_init_modus', 'PRE')
                self.migrated_keys.append('kamera_init_modus')   
                
            # =========================================================================
            
            # d_config = self.package_data['config']
            # dummy = d_config.getint('Zielscheibe', 'ringwertung_nachkommastellen', fallback=1) # Einfach nur aufrufen, damit der 

            for key, tk_var in self.registered_sliders.items():
                fallback_val = tk_var.get() # Den GUI-Standardwert als Rettungsanker nehmen
                
                # ---> NEU: Fehlt der Key in der ZIP-Config? Dann ab auf die Merkliste! <---
                if not config_ram.has_option('Erkennung', key):
                    self.migrated_keys.append(key)
                
                # Wir rufen absichtlich die get-Methoden MIT Fallback auf.
                if isinstance(tk_var, tk.BooleanVar):
                    val = config_ram.getboolean('Erkennung', key, fallback=fallback_val)
                elif isinstance(tk_var, tk.IntVar):
                    val = config_ram.getint('Erkennung', key, fallback=fallback_val)
                elif isinstance(tk_var, tk.DoubleVar):
                    val = config_ram.getfloat('Erkennung', key, fallback=fallback_val)
                        
                # DER ELA-FIX: Erst die Baseline setzen, DANN den Trace auslösen!
                self.original_values[str(tk_var)] = val
                tk_var.set(val)
            
            # =================================================================
            # ---> ELA FIX: Echte Originalwerte der Kameras für den Mittelklick sichern <---
            # =================================================================
            if not config_ram.has_section('Kameras'):
                config_ram.add_section('Kameras')
            
            # ---> NEU: Manuelle Prüfung der Linsen-Offsets für den Legacy Migrator <---
            for s in ['links', 'rechts']:
                for axis in ['x', 'y']:
                    key = f"lens_offset_{axis}_{s}"
                    if not config_ram.has_option('Kameras', key):
                        config_ram.set('Kameras', key, "0")
                        self.migrated_keys.append(key)
            
            # Da wir auch hier getfloat MIT Fallback nutzen, werden fehlende 
            # Kamera-Parameter (wie 'linsen_verzerrung) sofort vom config_ram geheilt!
            self.orig_calib = {
                'left_x': config_ram.getfloat('Kameras', 'px_pro_mm_x_links', fallback=5.0),
                'left_y': config_ram.getfloat('Kameras', 'px_pro_mm_y_links', fallback=5.0),
                'left_fisch': config_ram.getfloat('Kameras', 'linsen_verzerrung_links', fallback=0.0),
                'left_r4': config_ram.getfloat('Kameras', 'linsen_verzerrung_links_r4', fallback=0.0),
                'left_off_x': config_ram.getint('Kameras', 'lens_offset_x_links', fallback=0), # <--- HIER ERGÄNZEN
                'left_off_y': config_ram.getint('Kameras', 'lens_offset_y_links', fallback=0),
                'right_x': config_ram.getfloat('Kameras', 'px_pro_mm_x_rechts', fallback=5.0),
                'right_y': config_ram.getfloat('Kameras', 'px_pro_mm_y_rechts', fallback=5.0),
                'right_fisch': config_ram.getfloat('Kameras', 'linsen_verzerrung_rechts', fallback=0.0),
                'right_r4': config_ram.getfloat('Kameras', 'linsen_verzerrung_rechts_r4', fallback=0.0),
                'right_off_x': config_ram.getint('Kameras', 'lens_offset_x_rechts', fallback=0),
                'right_off_y': config_ram.getint('Kameras', 'lens_offset_y_rechts', fallback=0),
                'left_limit': config_ram.getfloat('Kameras', 'linsen_verzerrung_limit_links', fallback=0.0),
                'right_limit': config_ram.getfloat('Kameras', 'linsen_verzerrung_limit_rechts', fallback=0.0),
            }
            
            # ---> NEU: Initialen Push der Kalibrierungsdaten in die Slider erzwingen, 
            # BEVOR der Dirty-Marker scharfgeschaltet wird!
            self.update_calib_sliders()

            # =================================================================
            # ---> SCHRITT 1: Kompletten Original-Snapshot ALLER Config-Werte sichern <---
            # =================================================================
            self.orig_config_snapshot = {}
            for sec in config_ram.sections():
                self.orig_config_snapshot[sec] = {}
                for k, v in config_ram.items(sec):
                    self.orig_config_snapshot[sec][k] = str(v).strip()

    def get_orig_config_value(self, section, key, fallback=None):
        """Liefert den unveränderten Originalwert aus dem geladenen Snapshot."""
        if hasattr(self, 'orig_config_snapshot'):
            return self.orig_config_snapshot.get(section, {}).get(key, fallback)
        return fallback

    def is_config_value_changed(self, section, key, current_val):
        """Prüft unbestechlich, ob ein Parameter gegenüber dem geladenen Originalzustand verändert wurde."""
        orig_val = self.get_orig_config_value(section, key, fallback=None)
        if orig_val is None:
            return False

        curr_str = str(current_val).strip().strip('\'"').strip()
        orig_str = str(orig_val).strip().strip('\'"').strip()

        curr_low = curr_str.lower()
        orig_low = orig_str.lower()

        # 1. Sauberer Boolean-Abgleich (fängt 'False' vs 'no' und 'True' vs 'yes' ab!)
        bool_true = ('1', 'true', 'yes', 'on')
        bool_false = ('0', 'false', 'no', 'off')
        if (curr_low in bool_true or curr_low in bool_false) and (orig_low in bool_true or orig_low in bool_false):
            return (curr_low in bool_true) != (orig_low in bool_true)

        # 2. Numerischer Abgleich (für Floats/Ints wie 5.0 vs 5.000)
        try:
            return abs(float(curr_str) - float(orig_str)) > 1e-9
        except ValueError:
            pass

        # 3. Exakter String-Abgleich (z. B. für Kamera-Dateipfade oder aktive_scheibe)
        return curr_str != orig_str
    
    def print_help_banner(self):
        """Gibt das kompakte Cheat-Sheet für die Steuerung und die Auto-Heilungs-Infos im Log aus."""
        self.print_log("SYSTEM", "----------------------------------------------------------------------")    
        self.print_log("SYSTEM", "🚀 WILLKOMMEN IM LABOR - TASTATUR & MAUS STEUERUNG")
        self.print_log("SYSTEM", "[Pfeil Links/Rechts]   : Bild auf der Zeitleiste vor- und zurückspulen")
        self.print_log("SYSTEM", "[W, A, S, D]           : Zielscheiben-Zentrum (Nullpunkt) feinjustieren")
        self.print_log("SYSTEM", "[Mausrad]/[STRG+Ziehen]: Zoomen")
        self.print_log("SYSTEM", "[L-Klick + Ziehen]     : Bildausschnitt frei verschieben (Panning)")
        self.print_log("SYSTEM", "[Mittelklick]          : Ansicht auf den neuesten Schuss zentrieren")
        self.print_log("SYSTEM", "[Rechtsklick]          : Ansicht komplett zurücksetzen (Auto-Fit)")
        self.print_log("SYSTEM", "[ESC]                  : Aktionen abbrechen / Kalibrierungs-Klick zurück")
        self.print_log("SYSTEM", "----------------------------------------------------------------------")    

        # ---> NEU: Alle fehlenden / geheilten Parameter aus GUI & AuditedConfigconfig_ram sammeln <---
        config_ram = self.package_data.get('config') if getattr(self, 'package_data', None) else None
        alle_ergaenzten = []
        
        if getattr(self, 'migrated_keys', None):
            alle_ergaenzten.extend(self.migrated_keys)
            
        if config_ram and hasattr(config_ram, 'healed_parameters'):
            for item in config_ram.healed_parameters:
                # 'item' hat das Format "[Sektion] key" -> wir prüfen, ob der Key schon gelistet ist
                key_only = item.split("] ")[-1] if "] " in item else item
                if key_only not in alle_ergaenzten and item not in alle_ergaenzten:
                    alle_ergaenzten.append(item)

        if alle_ergaenzten:
            keys_str = ", ".join(alle_ergaenzten)
            self.print_log("SYSTEM", f"🔧 Auto-Heilung: {len(alle_ergaenzten)} fehlende Parameter mit Standardwerten ergänzt:")
            self.print_log("SYSTEM", f"   -> {keys_str}")
            
        if config_ram and getattr(config_ram, 'migrated_parameters', None):
            mig_str = ", ".join([f"{old_k} -> {new_k}" for _, old_k, new_k, _ in config_ram.migrated_parameters])
            self.print_log("SYSTEM", f"🔄 Legacy-Übersetzung: {mig_str}")
            
        if alle_ergaenzten or (config_ram and getattr(config_ram, 'migrated_parameters', None)):
            self.print_log("SYSTEM", "----------------------------------------------------------------------")
            
    def get_img(self, name):
        """Holt ein Bild blitzschnell aus dem vorbereiteten RAM-Speicher"""
        return self.package_data['images'].get(name)

    def load_local_config(self):
        """Lädt die lokale config.ini im Stand-Alone Modus."""
        
        # ---> DER FIX: Cache leeren, damit frisch von der Festplatte gelesen wird! <---
        #self.dm.targets_cache = None
        
        config_ram = self.dm.load_or_create_config()
        
        # ---> ELA-FIX: Den LaborContext frisch mit der neuen Config aufbauen! <---
        self.labor_context = LaborContext(config_ram, self.dm)
        
        #Das macht jetzt schon AuditedConfig.py
        ## ---> NEU: Fehlende Keys auch bei lokaler Config ergänzen! <---
        #if config_ram:
        #    if not config_ram.has_section('Erkennung'):
        #        config_ram.add_section('Erkennung')
        #    for key, tk_var in self.registered_sliders.items():
        #        if not config_ram.has_option('Erkennung', key):
        #            # Key fehlt -> mit GUI-Wert ergänzen
        #            config_ram.set('Erkennung', key, str(tk_var.get()))
        
        self.frame_cache = {'left': {}, 'right': {}}
        self.package_data = {
            'config': config_ram,
            'images': {},
            'match_data': None,
            'targets': self.dm.load_targets()  # <--- BOOM! Symmetrie zur Config hergestellt!
        }
        
        self.root.title("Labor & Einstellungen - Lokale config.ini")
        self.lbl_image.config(text="Stand-Alone Modus aktiv.\n(Klicke auf 'Erweiterte Einstellungen')", fg="white")

        # 1. ZUERST die UI füttern (hier passiert die Auto-Heilung & Befüllung von migrated_keys!)
        self.apply_config_to_ui(config_ram)

        # 2. DANN erst das Log und das Help-Banner ausgeben!
        self.print_log("SYSTEM", "Stand-Alone Modus: Lokale config.ini geladen.")
        self.print_help_banner()

        ## ---> NEU: Migrator-Log auch im lokalen Modus ausgeben! <---
        #if hasattr(self, 'migrated_keys') and self.migrated_keys:
        #    keys_str = ", ".join(self.migrated_keys)
        #    self.print_log("SYSTEM", f"🔧 Legacy-Migrator: {len(self.migrated_keys)} fehlende Parameter aus lokaler Config ergänzt:")
        #    self.print_log("SYSTEM", f"   -> {keys_str}")
        #    print(f"\n🔧 [LEGACY-MIGRATOR] {len(self.migrated_keys)} fehlende Parameter lokal ergänzt:\n   -> {keys_str}\n")
        #    self.migrated_keys = []

    def load_zip(self, filepath=None):
        if not filepath:
            filepath = filedialog.askopenfilename(title="Wähle ZIP", filetypes=[("ZIP", "*.zip")])
            
        if filepath:
            self._is_loading = True # <--- NEU: Ladesperre AKTIVIEREN
            
            #self.frame_cache = {'left': {}, 'right': {}}
            #self.labor_context.reset()
            
            self.current_zip_path = filepath
            # Vorläufiger Titel (damit was dasteht, falls das Laden einer Riesen-ZIP kurz dauert)
            self.root.title(f"Labor & Einstellungen  -  {os.path.basename(filepath)}")
            
            self.package_data = self.dm.import_match_package(filepath)
            if not self.package_data:
                messagebox.showerror("Fehler", "Konnte ZIP-Paket nicht laden!")
                return
                
            # =========================================================================
            # ---> DER FIX: Zeitkapsel-JSON global für ALLE Module in den Cache zwingen! <---
            # =========================================================================
            if not self.package_data.get('targets'):
                self.package_data['targets'] = self.dm.load_targets()
            #if self.package_data.get('targets'):
            #    self.dm.targets_cache = self.package_data['targets']
            #else:
            #    self.dm.targets_cache = None
                
            config_ram = self.package_data.get('config')
            
            # ---> ELA-FIX: Den LaborContext frisch mit der ZIP-Config aufbauen! <---
            self.labor_context = LaborContext(config_ram, self.dm)
            
            self.apply_config_to_ui(config_ram)
            self.original_match_data = self.package_data.get('match_data')
            
            # =========================================================================
            # ---> NEU: Fenster-Titel mit Version, Zeitstempel UND Spieler aufhübschen <---
            # =========================================================================
            if self.original_match_data and "metadata" in self.original_match_data:
                meta = self.original_match_data["metadata"]
                
                # 1. Basis-Teile: Name und Version
                version = meta.get("version", "???")
                titel_teile = [
                    f"Labor & Einstellungen  -  {os.path.basename(filepath)}",
                    f"v{version}"
                ]
                
                # 2. Zeitstempel (Sekunden mit [:-3] abschneiden, aus z.B. "18.09.26 19:21:34" wird "18.09.26 19:21")
                zeit = meta.get("timestamp", meta.get("start_zeit", ""))
                if zeit:
                    zeit_ohne_sekunden = zeit[:-3] if len(zeit) > 10 else zeit
                    titel_teile.append(f"🕒 {zeit_ohne_sekunden}")
                
                # 3. Spieler
                spieler = meta.get("spieler", "")
                if spieler:
                    titel_teile.append(f"👤 {spieler}")
                
                # 4. Alles konsequent mit doppeltem Leerzeichen um das Pipe-Symbol verbinden
                self.root.title("  |  ".join(titel_teile))

            self.all_files = list(self.package_data['images'].keys())
            # ---> DER FIX: Nur cumulative_orig filtern! ZZZ_ wird für die Live-Tuning Bridge zwingend gebraucht! <---
            self.orig_files = sorted([f for f in self.all_files if "_orig" in f and not os.path.basename(f).startswith("cumulative_")])
            
            # ---> NEU: Prüfen, welche Kameras überhaupt Daten im Paket haben <---
            has_left = any("left" in f for f in self.all_files)
            has_right = any("right" in f for f in self.all_files)
            
            self.rb_cam_left.config(state=tk.NORMAL if has_left else tk.DISABLED)
            self.rb_cam_right.config(state=tk.NORMAL if has_right else tk.DISABLED)
            
            if has_left: self.active_camera_var.set("left")
            elif has_right: self.active_camera_var.set("right")
                
            # Wir starten sauber bei 0 (Referenzbild)
            self.current_index = 0
            self.btn_prev.config(state=tk.NORMAL)
            self.btn_next.config(state=tk.NORMAL)
            self.btn_first.config(state=tk.NORMAL)
            self.btn_last.config(state=tk.NORMAL)
            self.update_calib_sliders() # <--- NEU: Initiales Füllen der Slider nach dem Laden!
            
            # ---> NEU: Auto-Zoom und Zentrierung vor dem ersten Zeichnen <---
            self.auto_zoom_and_center()
            
            # 1. ZUERST BILD LADEN UND LOG LÖSCHEN
            self.process_and_display()

            ## 2. DANN DEN MIGRATOR-LOG SCHREIBEN (Damit er sichtbar bleibt!)
            #if hasattr(self, 'migrated_keys') and self.migrated_keys:
            #    keys_str = ", ".join(self.migrated_keys)
            #    
            #    # A) Ausgabe in der Labor-GUI
            #    self.print_log("SYSTEM", f"🔧 Legacy-Migrator: {len(self.migrated_keys)} fehlende Parameter für diese Analyse ergänzt:")
            #    self.print_log("SYSTEM", f"   -> {keys_str}")
            #    
            #    # B) Ausgabe in der CMD-Konsole
            #    print(f"\n🔧 [LEGACY-MIGRATOR] {len(self.migrated_keys)} fehlende Parameter aus GUI-Standardwerten in '{os.path.basename(filepath)}' ergänzt:")
            #    print(f"   -> {keys_str}\n")
            #    
            #    # Merkliste wieder putzen
            #    self.migrated_keys = []
                
            self.drag_start_x = None
            self.drag_start_y = None
            self.is_zoom_box_active = False
            self._is_loading = False # <--- Ladesperre LÖSEN

    def prev_shot(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.process_and_display()

    def next_shot(self):
        if self.current_index < len(self.get_current_side_origs()):
            self.current_index += 1
            self.process_and_display()

    def safe_prev_shot(self, event=None):
        # ELA-Schutz: Wenn wir in JEDWEDEM Textfeld/Dropdown sind, ignorieren wir die Pfeiltasten!
        if isinstance(self.root.focus_get(), (tk.Entry, ttk.Combobox)):
            return
        self.prev_shot()

    def safe_next_shot(self, event=None):
        if isinstance(self.root.focus_get(), (tk.Entry, ttk.Combobox)):
            return
        self.next_shot()

    def first_shot(self):
        if self.current_index > 0:
            self.current_index = 0
            self.process_and_display()

    def last_shot(self):
        max_idx = len(self.get_current_side_origs())
        if self.current_index < max_idx:
            self.current_index = max_idx
            self.process_and_display() 

    def jump_to_shot(self, event=None):
        max_idx = len(self.get_current_side_origs())
        try:
            target_shot = int(self.shot_jump_var.get().strip())
            target_shot = max(0, min(target_shot, max_idx))
            self.current_index = target_shot
            

            
            self.process_and_display()
            # ---> HIER GEZOGEN: Fokus sofort weg vom Eingabefeld <---
            #self.root.focus_set() 
        except ValueError:
            self.shot_jump_var.set(str(self.current_index))

    def nudge_center(self, event):
        """Verschiebt den Mittelpunkt im RAM und triggert eine vollständige Neuberechnung."""
        # 1. Schutz einheitlich mit den Pfeiltasten machen:
        if isinstance(self.root.focus_get(), (tk.Entry, ttk.Combobox)):
            return
            
        if not getattr(self, 'original_match_data', None):
            return
            
        side = self.active_camera_var.get()
        center_key = 'center_l' if side == 'left' else 'center_r'
        
        meta = self.original_match_data.get('metadata', {})
        if not meta or center_key not in meta or not meta.get(center_key):
            return # Es gibt in dieser JSON noch gar keinen Mittelpunkt
            
        cx, cy = meta[center_key]
        char = event.keysym.lower()
        
        # ---> NEU: Wir merken uns den alten Stand für das Log <---
        alt_cx, alt_cy = cx, cy
        
        if char == 'w': cy -= 0.2
        elif char == 's': cy += 0.2
        elif char == 'a': cx -= 0.2
        elif char == 'd': cx += 0.2

        # 2. Den neuen Wert speichern
        self.original_match_data['metadata'][center_key] = [round(cx, 4), round(cy, 4)]
        
        # ---> NEU: Das asynchrone Zentrum-Preview mit 800ms Puffer! <---
        # Überbrückt die Windows-Tastatur-Verzögerung und menschliche Tipp-Pausen.
        self.on_param_change(force=False, delay=600)
        
        diff_x = cx - alt_cx
        diff_y = cy - alt_cy
        richtung = ""
        if diff_x < 0: richtung = "◀ Links"
        elif diff_x > 0: richtung = "▶ Rechts"
        elif diff_y < 0: richtung = "▲ Hoch"
        elif diff_y > 0: richtung = "▼ Runter"
        
        self.print_log("SYSTEM", f"🎯 Zentrum {side.upper()} verschoben ({richtung}): X:{cx:.4f} Y:{cy:.4f}")

        # ---> DER FIX: Wir rufen den Renderer auf! <---
        self.renderer.draw_center_preview(cx, cy)

 
    def on_param_change(self, event=None, force=False, delay=300):
        if not self.current_zip_path:
            return
            
        if getattr(self, '_is_loading', False):
            return
            
        if force:
            if hasattr(self, '_param_timer') and self._param_timer is not None:
                self.root.after_cancel(self._param_timer)
                self._param_timer = None
            # ---> ELA-FIX: Den ECHTEN Cache im Model leeren! <---
            self.labor_context.reset()
            self.process_and_display()
            return
            
        if hasattr(self, '_param_timer') and self._param_timer is not None:
            self.root.after_cancel(self._param_timer)
            
        self._param_timer = self.root.after(delay, self._apply_param_change)

    def _apply_param_change(self):
        """Die eigentliche Ausführung nach dem Zeitpuffer"""
        self._param_timer = None
        # ---> ELA-FIX: Den ECHTEN Cache im Model leeren! <---
        self.labor_context.reset()
        self.process_and_display()

    def on_mouse_move(self, event):
        # Wenn noch kein Bild geladen ist, tu nichts
        if getattr(self, 'base_combined_img', None) is None or not hasattr(self, 'current_scale'):
            return

        # ---> NEU: Kein Fadenkreuz zeichnen, während der User aktiv interagiert! <---
        if self.is_interacting:
            return

        # =========================================================================
        # ---> DER FIX: Wir verhindern den tödlichen Tkinter-Stau! <---
        # =========================================================================
        if getattr(self, '_is_rendering_crosshair', False):
            return # Ein 500MB-Bild wird gerade verarbeitet -> weitere Maus-Events abprallen lassen!
            
        
        current_time = time.time()
        # Maximal 40 FPS erlauben
        if current_time - getattr(self, 'last_mouse_update_time', 0) < 0.025:
            return
            
        self.last_mouse_update_time = current_time
        self._is_rendering_crosshair = True # Tür abschließen!
        
        try:
            # Letzte Position für den Blink-Timer retten
            self.last_mouse_x = event.x
            self.last_mouse_y = event.y
            
            x, y = event.x, event.y
            img_h, img_w = self.base_combined_img.shape[:2]
            # Sicherheits-Check: Befindet sich die Maus überhaupt innerhalb des Bildes?
            if x < 0 or y < 0 or x >= img_w or y >= img_h:
                self.on_mouse_leave(event)
                return
            abs_x = x + getattr(self, 'last_vp_x', 0)
            abs_y = y + getattr(self, 'last_vp_y', 0)
            # 1. Ermitteln, in welcher Bildhälfte wir sind und die Basis-Koordinaten rechnen
            is_left = (abs_x < self.current_img_w)
            raw_x = abs_x if is_left else (abs_x - self.current_img_w)
            real_x = int(raw_x / self.current_scale)
            real_y = int(abs_y / self.current_scale)
            
            ## Schutzplanken gegen Out-of-Bounds
            #if hasattr(self, 'last_clean_live_img') and self.last_clean_live_img is not None:
            #    orig_h, orig_w = self.last_clean_live_img.shape[:2]
            #    real_x = max(0, min(real_x, orig_w - 1))
            #    real_y = max(0, min(real_y, orig_h - 1))

            # Schutzplanken gegen Out-of-Bounds
            if hasattr(self, 'last_live_img') and self.last_live_img is not None:
                orig_h, orig_w = self.last_live_img.shape[:2]
                real_x = max(0, min(real_x, orig_w - 1))
                real_y = max(0, min(real_y, orig_h - 1))

            # Diff-Werte abrufen
            diff_val = self.last_raw_diff[real_y, real_x] if hasattr(self, 'last_raw_diff') else 0
            
            # Faktor und Farb-Distanz auslesen
            if hasattr(self, 'last_color_multiplier') and self.last_color_multiplier is not None:
                factor = self.last_color_multiplier[real_y, real_x]
                dist_c = self.last_color_dist[real_y, real_x] if hasattr(self, 'last_color_dist') else 0
                bonus_str = f" | Dist: {dist_c:.0f} | F: {factor:.2f}"
            else:
                bonus_str = " | Filter Aus"
                
            # UI Update mit Anzeige der Seite
            side_name = "Live" if is_left else "Rechts"
            self.lbl_coords.config(text=f"{side_name} X:{real_x:04d} Y:{real_y:04d} | D:{diff_val:03d}{bonus_str}")
            
            # =========================================================================
            # ---> IDEE B: Ab 5-fachem Zoom den Maus-Klon komplett abschalten! <---
            # =========================================================================
            if self.zoom_factor >= 5.0:
                # Falls von vorher noch ein Klon auf dem Monitor klebt, putzen wir ihn EINMALIG weg
                if getattr(self, '_crosshair_active', False):
                    # on_mouse_leave stellt das nackte Bild aus dem RGB-Cache wieder her
                    self.on_mouse_leave(event)
                    self._crosshair_active = False
                    
                # Ab hier: 100 % CPU-Ersparnis! Keine Bildberechnung, kein GUI-Upload mehr.
                return 
                
            self._crosshair_active = True
            
            # Direktes, synchrones Zeichnen (nur bei Zoom < 5.0)
            self.renderer.draw_crosshair(x, y)
            
        finally:
            # Egal was passiert, am Ende wird die Tür wieder aufgeschlossen
            self._is_rendering_crosshair = False

    def on_mouse_leave(self, event):
        # ---> TÜRSTEHER: Kein Neuladen auslösen, während das Bild verschoben wird! <---
        if self.is_interacting:
            return
            
        self.lbl_coords.config(text="Maus nicht im Bild")
        self.last_mouse_x = None
        self.last_mouse_y = None
        
        # ---> DER FIX: Wir nutzen den fertigen RGB-Cache statt der 1-Sekunden-Konvertierung! <---
        if getattr(self, 'base_combined_img_rgb', None) is not None:
            img_pil = Image.fromarray(self.base_combined_img_rgb)
            self.tk_image = ImageTk.PhotoImage(img_pil)
            self.lbl_image.config(image=self.tk_image)

    def on_zoom_box_start(self, event):
        """Startet den Rahmen-Zoom (Strg / Shift)"""
        self.root.focus_set() 
        if getattr(self, 'color_picker_active', False):
            return "break"
            
        self.is_zoom_box_active = True
        self.zoom_box_start_x = event.x
        self.zoom_box_start_y = event.y
        return "break"
        
    def on_zoom_box_motion(self, event):
        """Berechnet die Koordinaten und weist den Renderer an, den Rahmen zu zeichnen"""
        if getattr(self, 'is_zoom_box_active', False):
            if self.zoom_factor >= self.max_zoom_factor - 0.01:
                return "break"
                
            # 25 FPS Türsteher
            current_time = time.time()
            if current_time - getattr(self, 'last_zoombox_update_time', 0) < 0.040:
                return
            self.last_zoombox_update_time = current_time
            
            # ---> NEU: Den Renderer die Arbeit machen lassen! <---
            self.renderer.draw_zoom_box(
                self.zoom_box_start_x, self.zoom_box_start_y, 
                event.x, event.y, 
                getattr(self, 'viewport_place_x', getattr(self, 'pan_x', 0)), getattr(self, 'viewport_place_y', getattr(self, 'pan_y', 0))
            )
        return "break"

    def on_zoom_box_stop(self, event):
        """Führt den Box-Zoom aus"""
        if getattr(self, 'is_zoom_box_active', False):
            self.is_zoom_box_active = False
            
            # ---> NEU: Dem Renderer sagen, er soll aufräumen <---
            self.renderer.hide_zoom_box()
            self.apply_zoom_box(self.zoom_box_start_x, self.zoom_box_start_y, event.x, event.y)
        return "break"

    def abort_zoom_box(self, event=None):
        """Bricht das Aufziehen des Zoom-Rahmens ab, wenn ESC gedrückt wird."""
        if getattr(self, 'is_zoom_box_active', False):
            self.is_zoom_box_active = False
            self.zoom_box_start_x = None
            self.zoom_box_start_y = None
            
            # ---> NEU: Dem Renderer sagen, er soll aufräumen <---
            self.renderer.hide_zoom_box()
            self.print_log("SYSTEM", "Zoom-Rahmen abgebrochen.")

    def on_drag_start(self, event):
        """Normaler Linksklick (Verschieben, Kalibrieren, Pipette)"""
        self.root.focus_set() # <--- ELA FIX: Fokus sanft holen, bevor das Ziehen beginnt!
        
        # ---> FIX 1: Kein Panning starten, solange kein Bild da ist oder gerade ein ZIP lädt! <---
        if getattr(self, 'tk_image', None) is None or getattr(self, '_is_loading', False):
            self.drag_start_x = None
            self.drag_start_y = None
            return

        if getattr(self, 'calib_mode_active', False):
            if event.widget == self.lbl_image:
                 self.handle_calibration_click(event)
            return

        if getattr(self, 'color_picker_active', False):
            self.pick_color_from_event(event)
            self.toggle_color_picker() 
            return

        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root
        self.start_pan_x = self.pan_x
        self.start_pan_y = self.pan_y

    def on_drag_motion(self, event):
        """Verschiebt das Bild normal mit FPS-Drossel"""
        # ---> DER FIX: Wenn wir im Zoom-Modus sind, leiten wir das Event um! <---
        if getattr(self, 'is_zoom_box_active', False):
            return self.on_zoom_box_motion(event)

        if getattr(self, 'tk_image', None) is None: return
        
        # ---> DER TÜRSTEHER GEGEN DEN SONDERFALL <---
        if self.drag_start_x is None or self.drag_start_y is None: 
            return
            
        # =========================================================================
        # ---> NEU: FPS-Drossel verhindert den 500ms Tkinter-Geometrie-Stau! <---
        # =========================================================================
        current_time = time.time()
        # Maximal 25 FPS für das Panning erlauben (0.040 Sekunden)
        if current_time - getattr(self, 'last_pan_update_time', 0) < 0.040:
            return
        self.last_pan_update_time = current_time
        
        dx = event.x_root - self.drag_start_x
        dy = event.y_root - self.drag_start_y
        
        self.pan_x = self.start_pan_x + dx
        self.pan_y = self.start_pan_y + dy
        
        if getattr(self, 'zoom_factor', 1.0) > 4.0:
            self.renderer.update_image_display(full_rebuild=False, push_to_gui=True)
        else:
            self.lbl_image.place(x=self.pan_x, y=self.pan_y)

    def on_drag_stop(self, event):
        """Normales Loslassen (Verschieben beenden oder Röntgen-Klick)"""
        # ---> FIX 2: Startwerte lokal sichern und Status SOFORT vor allen 'returns' freigeben! <---
        start_x = self.drag_start_x
        start_y = self.drag_start_y
        self.drag_start_x = None
        self.drag_start_y = None

        # Wenn wir im Zoom-Modus sind, triggern wir den Zoom!
        if getattr(self, 'is_zoom_box_active', False):
            return self.on_zoom_box_stop(event)

        if getattr(self, 'color_picker_active', False): return
        if getattr(self, 'tk_image', None) is None: return
        
        # Türsteher, falls gar kein gültiger Drag lief
        if start_x is None or start_y is None: 
            return

        dx = event.x_root - start_x
        dy = event.y_root - start_y
        dist = (dx**2 + dy**2)**0.5

        if dist < 5:  
            self.identify_shot_at_click(event.x, event.y)
        else:
            # =========================================================================
            # ---> NEU: Panning beendet -> Wenn Detail-Export an ist, sofort neu zeichnen! <---
            # =========================================================================
            if self.package_data and self.package_data.get('config'):
                if self.package_data['config'].getboolean('Erkennung', 'detail_export_aktiv', fallback=False):
                    self.renderer.update_image_display(full_rebuild=False, push_to_gui=True)

    def apply_zoom_box(self, x1, y1, x2, y2):
        """Berechnet aus dem gezogenen Rahmen den neuen Zoom und zentriert den Ausschnitt."""
        min_x, max_x = min(x1, x2), max(x1, x2)
        min_y, max_y = min(y1, y2), max(y1, y2)
        
        box_w = max_x - min_x
        box_h = max_y - min_y
        
        # 1. Winz-Klicks als Zeitsprung werten (funktioniert IMMER, auch bei Max-Zoom!)
        if box_w < 15 or box_h < 15:
            self.identify_shot_at_click(x2, y2, jump_to_frame=True)
            return
            
        # ---> NEU: 2. Rahmen-Zoom sicher abfangen und willkürliches Panning stoppen <---
        if self.zoom_factor >= self.max_zoom_factor - 0.01:
            self.print_log("SYSTEM", f"Maximaler Zoom ({self.max_zoom_factor}x) erreicht. Rahmen-Zoom gesperrt.")
            return # ZWINGEND NÖTIG, SONST GIBT ES PANNING OHNE ZOOM!
            
        self.root.update_idletasks()
        container_w = self.img_container.winfo_width()
        container_h = self.img_container.winfo_height()
        
        old_scale = getattr(self, 'current_scale', 1.0)
        
        # Neuen Zoom-Faktor basierend auf der Box-Größe berechnen
        zoom_multiplier = min(container_w / box_w, container_h / box_h)
        zoom_multiplier = max(1.01, min(zoom_multiplier, 15.0))
        
        self.zoom_factor = max(0.2, min(self.zoom_factor * zoom_multiplier, self.max_zoom_factor))
        print("apply_zoom_box - zoom_factor: ", self.zoom_factor)
        
        # ---> SEIDEN-MUSTER FIX: Echte Auflösung aus dem Kontext-Paket holen! <---
        if hasattr(self, 'current_context') and self.current_context and self.current_context.live_img is not None:
            h, w = self.current_context.live_img.shape[:2]
        else:
            h, w = 720, 1280
            
        new_scale = (550.0 / h) * self.zoom_factor
        
        # Mittelpunkt der Box im aktuellen Anzeigebild
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        
        abs_center_x = center_x + getattr(self, 'last_vp_x', 0)
        abs_center_y = center_y + getattr(self, 'last_vp_y', 0)
        
        self.pan_x = int((container_w / 2.0) - (abs_center_x / old_scale) * new_scale)
        self.pan_y = int((container_h / 2.0) - (abs_center_y / old_scale) * new_scale)
        
        # =========================================================================
        # ---> DER FIX: Absolut atomares Tkinter-Update <---
        # =========================================================================
        # 1. Bild STUMM rendern lassen (ohne es der GUI zu geben)
        self.renderer.update_image_display(push_to_gui=True)
        
                
        self.update_frame_title()
    
    def toggle_color_picker(self):
        """Schaltet den Modus um und ändert das Aussehen des Buttons/Mauszeigers"""
        self.color_picker_active = not getattr(self, 'color_picker_active', False)
        if self.color_picker_active:
            self.btn_pick_color.config(bg="#e74c3c", text="🔴 Klick ins Bild...")
            self.lbl_image.config(cursor="crosshair")
        else:
            self.btn_pick_color.config(bg="#f39c12", text="🎨 Wandfarbe picken")
            self.lbl_image.config(cursor="")

    def pick_color_from_event(self, event):
        """Holt den Farbwert unter der Maus und schreibt ihn in die Config"""
        if getattr(self, 'base_combined_img', None) is None or not hasattr(self, 'current_scale'):
            return
            
        x, y = event.x, event.y
        img_h, img_w = self.base_combined_img.shape[:2]
        if x < 0 or y < 0 or x >= img_w or y >= img_h: return
        abs_x = x + getattr(self, 'last_vp_x', 0)
        abs_y = y + getattr(self, 'last_vp_y', 0)
        # Koordinaten exakt wie beim Maus-Hover ausrechnen
        is_left = (abs_x < self.current_img_w)
        raw_x = abs_x if is_left else (abs_x - self.current_img_w)
        real_x = int(raw_x / self.current_scale)
        real_y = int(abs_y / self.current_scale)

        #if hasattr(self, 'last_clean_live_img') and self.last_clean_live_img is not None:
        #    orig_h, orig_w = self.last_clean_live_img.shape[:2]
        #    real_x = max(0, min(real_x, orig_w - 1))
        #    real_y = max(0, min(real_y, orig_h - 1))
        # ---> SEIDEN-MUSTER FIX: Kontext statt last_live_img nutzen <---
        ctx = getattr(self, 'current_context', None)
        if ctx and ctx.live_img is not None:
            orig_h, orig_w = ctx.live_img.shape[:2]
            real_x = max(0, min(real_x, orig_w - 1))
            real_y = max(0, min(real_y, orig_h - 1))
            
            # Farbe auslesen (BGR)
            b_val, g_val, r_val = ctx.live_img[real_y, real_x]
            
            # In die Konfiguration der AKTUELLEN Kamera schreiben
            if getattr(self, 'package_data', None) and self.package_data.get('config'):
                config_ram = self.package_data['config']
                side_str = "Hintergrund_Links" if self.current_side == 'left' else "Hintergrund_Rechts"
                
                if not config_ram.has_section(side_str):
                    config_ram.add_section(side_str)
                
                config_ram.set(side_str, 'rgb_r', str(r_val))
                config_ram.set(side_str, 'rgb_g', str(g_val))
                config_ram.set(side_str, 'rgb_b', str(b_val))
                
                self.print_log("SYSTEM", f"🎨 WANDFARBE GEUPDATET ({side_str}): RGB({r_val}, {g_val}, {b_val}) gepickt an Position X:{real_x}, Y:{real_y}")
                
                # Engine sofort mit den neuen Farben zwingen neuzustarten!
                self.on_param_change(force=True)

    # =========================================================================
    # ---> DIE FASSADE FÜR DEN KALIBRATOR <---
    # Wir leiten alle GUI-Aufrufe stumm an die neue Modul-Datei weiter!
    # =========================================================================
    def start_calibration_assist(self):
        self.kalibrator.start_calibration_assist()
    def undo_calibration_click(self, event=None):
        self.kalibrator.undo_calibration_click(event)
    def cancel_calibration(self):
        self.kalibrator.cancel_calibration()
    def update_calibration_instruction(self):
        self.kalibrator.update_calibration_instruction()
    def handle_calibration_click(self, event):
        self.kalibrator.handle_calibration_click(event)
    def finish_calibration(self):
        self.kalibrator.finish_calibration()
        
    def start_kamera_test(self):
        KameraTestAdvaced.start_ui(self.root, self)

    def start_match_integrity(self):
        MatchIntegrity.start_ui(self.root, self)


    def identify_shot_at_click(self, x, y, jump_to_frame=False):
        """Sucht den Treffer unter der Maus und blendet die Frame-Info ein (oder springt dorthin)"""
        if getattr(self, 'base_combined_img', None) is None: return
            
        abs_x = x + getattr(self, 'last_vp_x', 0)
        abs_y = y + getattr(self, 'last_vp_y', 0)
        is_left = (abs_x < self.current_img_w)
        raw_x = abs_x if is_left else (abs_x - self.current_img_w)
        real_x = int(raw_x / self.current_scale)
        real_y = int(abs_y / self.current_scale)

        radius = getattr(self, 'current_radius_px', 15)
        best_shot = None
        best_dist = float('inf')

        for shot in getattr(self, 'current_engine_shots', []):
            sx, sy = shot['pos']
            d = ((sx - real_x)**2 + (sy - real_y)**2)**0.5
            if d <= radius and d < best_dist:
                best_shot = shot
                best_dist = d

        if best_shot:
            f_num = best_shot.get('labor_frame_num', '?')
            
            # ---> NEU: Dynamische Nachkommastellen auslesen <---
            decimals = 1
            if getattr(self, 'package_data', None) and self.package_data.get('config'):
                decimals = self.package_data['config'].getint('Zielscheibe', 'ringwertung_nachkommastellen', fallback=1)
                
            # Verschachtelter f-String: .{decimals}f setzt die Länge flexibel
            self.print_log("SYSTEM", f"🎯 RÖNTGEN-SCAN: Dieser Treffer entstand in BILD #{f_num} (Score: {best_shot.get('score', 0.0):.{decimals}f})")
            
            self.highlighted_shot = {
                'pos': best_shot['pos'], 
                'frame': f_num, 
                'cal_radius': best_shot.get('cal_radius', radius), # <--- NEU: Echter lokaler Radius dieses Schusses!
                'time': time.time()
            }
            
            # ---> NEU: Die Zeitreise-Logik <---
            if jump_to_frame and isinstance(f_num, int):
                self.print_log("SYSTEM", f"🚀 ZEITREISE: Springe direkt zu Bild #{f_num}...")
                self.current_index = f_num
                self.process_and_display()
            else:
                self.renderer.update_image_display(full_rebuild=False)
            
            if hasattr(self, '_highlight_timer') and self._highlight_timer is not None:
                self.root.after_cancel(self._highlight_timer)
            self._highlight_timer = self.root.after(5000, self.clear_highlight)

    def clear_highlight(self):
        """Löscht das orangene/lila Highlight nach Ablauf des Timers"""
        self.highlighted_shot = None
        self._highlight_timer = None 
        self.renderer.update_image_display(full_rebuild=False)
  
    def reset_view(self, event=None):
        """Setzt Zoom und Position zurück (Auto-Fit bei Rechtsklick)"""
        if getattr(self, 'current_zip_path', None):
            self.auto_zoom_and_center()
        else:
            self.zoom_factor = 1.0
            self.pan_x = 0
            self.pan_y = 0
            self.lbl_image.place(x=0, y=0)
            
        self.renderer.update_image_display()
        self.update_frame_title() # <--- NEU

    def toggle_var_mode(self, step, event=None):
        """Aktiviert das Battle Royale VAR für ALLE neuen Schüsse im aktuellen Bild."""
        if isinstance(self.root.focus_get(), (tk.Entry, ttk.Combobox)): return
        if self.current_index == 0: return # Im Referenzbild gibt es keine Schüsse
        
        # 1. Sammle alle NEUEN Schüsse in diesem Frame
        side = getattr(self, 'current_side', self.active_camera_var.get())
        current_frame_num = self.current_index
        
        self.var_shots = []
        for s in getattr(self, 'current_engine_shots', []):
            if s.get('side') == side and s.get('labor_frame_num') == current_frame_num and s.get('is_new', False):
                details = s.get('score_export_details', {})
                if details and 'all_candidates' in details and details['all_candidates']:
                    self.var_shots.append(s)
                    
        if not self.var_shots:
            self.print_log("SYSTEM", "Keine Kandidaten-Daten im aktuellen Bild gefunden (Wurden ohne Subpixel-Export generiert).")
            return
            
        was_active = getattr(self, 'candidate_view_active', False)
        self.candidate_view_active = True
        
        # 2. Globalen Index weiterschalten
        max_candidates = len(self.var_shots[0]['score_export_details']['all_candidates'])
        
        if not was_active:
            # Erster Tastendruck: Bei "Runter" starten wir sauber mit Kandidat 1 (Index 0).
            # Bei "Rauf" springen wir direkt zum letzten Kandidaten.
            self.candidate_idx = 0 if step > 0 else max_candidates - 1
        else:
            # VAR ist schon aktiv -> Normal weiterblättern
            current_idx = getattr(self, 'candidate_idx', 0)
            self.candidate_idx = (current_idx + step) % max_candidates
        
        # Timer zurücksetzen
        if hasattr(self, '_var_timer') and self._var_timer is not None:
            self.root.after_cancel(self._var_timer)
            self._var_timer = None                                      #TIMER AUSSCHALTEN!!!!!!!!!!!!!!!!!
        #self._var_timer = self.root.after(10000, self.clear_var_mode)  #TIMER AUSSCHALTEN!!!!!!!!!!!!!!!!!
        
        self.renderer.update_image_display(full_rebuild=False)

    def clear_var_mode(self, event=None):
        """Beendet den VAR-Modus und räumt auf."""
        if getattr(self, 'candidate_view_active', False):
            self.candidate_view_active = False
            self.candidate_idx = 0
            self.var_shots = []
            if hasattr(self, '_var_timer') and self._var_timer is not None:
                self.root.after_cancel(self._var_timer)
                self._var_timer = None
            #self.print_log("VAR", "Overlay beendet.")
            self.renderer.update_image_display(full_rebuild=False)


    def update_frame_title(self, status=None):
        """Aktualisiert die Überschrift des Bild-Bereichs mit dynamischem Zoom, Shortcuts und optionalem Status."""
        if not getattr(self, 'current_zip_path', None):
            return
            
        side = self.active_camera_var.get()
        zoom_str = f"Zoom: {self.zoom_factor:.1f}x"
        controls = "Rad: Zoom  |  L-Klick: Bewegen  |  R-Klick: Reset  |  M-Klick: Zentrieren  |  Strg+Ziehen: Rahmen"
        
        # Wenn ein Status übergeben wurde -> Text setzen und auf Blau (#3498db) umschalten!
        if status:
            self.image_frame.config(text=status, fg="#00BEFF")
            self.root.update_idletasks() # Erzwingt sofortiges Neuladen der GUI
            return

        # Normaler Zustand -> Wieder auf Weiß zurückschalten
        self.image_frame.config(fg="white")

        if self.current_index == 0:
            self.image_frame.config(text=f" {zoom_str}  |  {controls}  |  📷 Referenz {side.upper()} ")
        else:
            side_origs = self.get_current_side_origs()
            if side_origs and self.current_index <= len(side_origs):
                orig_name = side_origs[self.current_index - 1]
            else:
                orig_name = "Unbekannt"
            self.image_frame.config(text=f" {zoom_str}  |  {controls}  |  📄 {orig_name} ")
            
    def center_on_last_shot(self, event=None):
        """Zentriert den letzten Schuss des aktuellen Bildes in der angeklickten Bildhälfte."""
        if getattr(self, 'current_engine_shots', None) is None or not hasattr(self, 'current_scale'):
            return
            
        side = self.active_camera_var.get()
        current_frame_num = self.current_index
        
        # Alle Treffer dieses Bildes (und dieser Kamera) filtern
        valid_shots = [s for s in self.current_engine_shots if s.get('side') == side and s.get('labor_frame_num') == current_frame_num]
        
        if not valid_shots:
            self.print_log("SYSTEM", f"Mittelklick: Kein neuer Treffer in Bild #{current_frame_num} gefunden, auf den zentriert werden könnte.")
            return
            
        # Den absolut letzten Treffer aus der Liste schnappen
        latest_shot = valid_shots[-1]
        hx, hy = latest_shot['pos']
        
        self.print_log("SYSTEM", f"Mittelklick: Zentriere auf Treffer (X:{hx:.1f}, Y:{hy:.1f}) in Bild #{current_frame_num}")
        
        # Fenstermaße aktualisieren und abrufen
        self.root.update_idletasks()
        container_w = self.img_container.winfo_width()
        container_h = self.img_container.winfo_height()
        
        # Auf welche der beiden Hälften (Links oder Rechts) wurde geklickt?
        abs_x = event.x + getattr(self, 'last_vp_x', 0)
        is_left = (abs_x < getattr(self, 'current_img_w', 0))
        
        if is_left:
            # X-Koordinate im skalierten Bild
            shot_img_x = hx * self.current_scale
            # Ziel-Punkt ist das Zentrum der LINKEN Bildschirmhälfte (also 25% der Gesamtbreite)
            target_container_x = (container_w / 4.0) * 2.0
        else:
            # X-Koordinate im skalierten Bild (um die linke Bildhälfte nach rechts verschoben)
            shot_img_x = (hx * self.current_scale) + self.current_img_w
            # Ziel-Punkt ist das Zentrum der RECHTEN Bildschirmhälfte (also 75% der Gesamtbreite)
            target_container_x = (container_w / 4.0) * 2.0
            
        shot_img_y = hy * self.current_scale
        # Y-Ziel ist exakt die vertikale Mitte des Containers
        target_container_y = container_h / 2.0
        
        # Neue Kamera-Verschiebung (Pan) berechnen
        self.pan_x = int(target_container_x - shot_img_x)
        self.pan_y = int(target_container_y - shot_img_y)
        
        if getattr(self, 'zoom_factor', 1.0) > 4.0:
            self.renderer.update_image_display(full_rebuild=False, push_to_gui=True)
        else:
            self.lbl_image.place(x=self.pan_x, y=self.pan_y)
        
        # Falls die Maus nach dem Klick liegen bleibt, triggern wir kurz ein Move-Event, 
        # damit auch das Fadenkreuz und die Koordinaten sofort aktualisiert werden
        self.on_mouse_move(event)
    
    def auto_zoom_and_center(self):
        """Berechnet den optimalen Zoom, sodass das Doppel-Bild exakt in den sichtbaren Bereich passt."""
        side = self.active_camera_var.get() # Liefert 'left' oder 'right'
        
        # 1. Original-Bildgröße ermitteln (Fallback 720x1280)
        h, w = 720, 1280
        
        # ---> DER FIX: Dateinamen nutzen 'left'/'right' (side), nicht 'links'/'rechts' (seite_str)! <---
        ref_name = next((f for f in getattr(self, 'all_files', []) if f"referenz_{side}" in f), None)
        if ref_name:
            ref_img = self.get_img(ref_name)
            if ref_img is not None:
                h, w = ref_img.shape[:2]
                
        # 2. Verfügbaren Platz in der GUI dynamisch ermitteln
        self.root.update_idletasks() # Wartet intern, bis das Fenster gezeichnet ist
        container_h = self.img_container.winfo_height()
        container_w = self.img_container.winfo_width()
        
        # Fallback-Maße, falls die GUI im Hintergrund noch lädt
        if container_h < 100: container_h = 800
        if container_w < 100: container_w = 1200
        
        # 3. Ziel-Skalierung berechnen (Wir lassen keinen Rand (vorher 0.95) für eine schöne Optik)
        # Wir brauchen Platz für 2 Bilder nebeneinander (w * 2.0)
        target_scale_w = (container_w * 1.00) / (w * 2.0)
        target_scale_h = (container_h * 1.00) / float(h)
        
        # Der kleinere Wert gewinnt, damit garantiert nichts abgeschnitten wird
        target_scale = min(target_scale_w, target_scale_h)
        
        # 4. Den internen zoom_factor der Engine füttern
        # (Die Engine rechnet intern immer mit einer Basis-Höhe von 550 Pixeln)
        self.zoom_factor = target_scale * (h / 550.0)
        self.zoom_factor = max(0.2, min(self.zoom_factor, self.max_zoom_factor)) # Sicherheits-Grenzen
        
        # Echte Skalierung für das Panning (falls die Grenzen gegriffen haben)
        echte_scale = (550.0 / h) * self.zoom_factor
        
        # 5. Bild exakt mittig in den Container pinnen
        self.pan_x = int((container_w - (w * 2.0 * echte_scale)) / 2.0)
        self.pan_y = int((container_h - (h * echte_scale)) / 2.0)
        
        self.lbl_image.place(x=self.pan_x, y=self.pan_y)

    
    def on_mouse_scroll(self, event):
        # ---> DER FIX: Wir merken uns den Zoom & die Maus VOR dem ersten Scroll-Tick! <---
        if not getattr(self, '_is_scrolling', False):
            self._is_scrolling = True
            self._scroll_start_zoom = self.zoom_factor
            self._scroll_mouse_x = event.x
            self._scroll_mouse_y = event.y
            
        # Prüfen, ob nach oben oder unten gescrollt wurde
        if event.num == 4 or getattr(event, 'delta', 0) > 0:
            self.zoom_factor *= 1.15  # 15% Reinzoomen
        elif event.num == 5 or getattr(event, 'delta', 0) < 0:
            self.zoom_factor *= 0.85  # 15% Rauszoomen
            
        # Grenzen setzen
        self.zoom_factor = max(0.2, min(self.zoom_factor, self.max_zoom_factor))
        
        # Titelzeile sofort updaten (direktes visuelles Feedback)
        self.update_frame_title()
        
        # Laufenden Timer abbrechen, wenn noch fleißig am Rad gedreht wird
        if hasattr(self, '_scroll_timer') and self._scroll_timer is not None:
            self.root.after_cancel(self._scroll_timer)
            
        # Render-Befehl erst ausführen, wenn 100 ms lang Ruhe am Mausrad war!
        self._scroll_timer = self.root.after(100, lambda e=event: self._apply_scroll(e))

    def _apply_scroll(self, event):
        """Führt das tatsächliche, schwere Rendern nach Abschluss der Mausrad-Bewegung aus."""
        self._scroll_timer = None
        self._is_scrolling = False # Scroll-Vorgang abgeschlossen
        
        old_zoom = getattr(self, '_scroll_start_zoom', self.zoom_factor)
        
        if self.zoom_factor != old_zoom:
            scale_change = self.zoom_factor / old_zoom
            
            # Wir nutzen die gespeicherten Koordinaten vom START des Scrollens
            mx = self._scroll_mouse_x
            my = self._scroll_mouse_y
            
            # =====================================================================
            # ---> FIX: DIE KORREKTE KAMERA-ZOOM-MATHEMATIK <---
            # =====================================================================
            # 1. Wo liegt die Maus absolut auf dem riesigen virtuellen Bild?
            abs_mx = mx - self.pan_x
            abs_my = my - self.pan_y
            
            # 2. Wo liegt dieser Punkt NACH der Skalierung?
            new_abs_mx = abs_mx * scale_change
            new_abs_my = abs_my * scale_change
            
            # 3. Den Kamera-Nullpunkt (pan) so verschieben, dass der Punkt 
            #    wieder exakt unter der fixen Maus (mx/my) auf dem Monitor landet!
            self.pan_x = int(mx - new_abs_mx)
            self.pan_y = int(my - new_abs_my)
            # =====================================================================
            
        # =========================================================================
        # ---> DER FIX: Absolut atomares Tkinter-Update <---
        # =========================================================================
        # 1. Bild STUMM rendern lassen
        self.renderer.update_image_display(push_to_gui=True)
        
        # Koordinaten-Anzeige manuell triggern, damit sie nach dem Zoom sofort stimmt
        self.on_mouse_move(event)

    def process_and_display(self):
        self.update_frame_title()
        if not self.current_zip_path: 
            return

        # 1. Warte-Cursor einmalig vorab setzen (inkl. Sprung-Textfeld!)
        self.root.config(cursor="watch")
        self.lbl_image.config(cursor="watch")
        if hasattr(self, 'img_container'):
            self.img_container.config(cursor="watch")
        if hasattr(self, 'entry_shot_jump'):
            self.entry_shot_jump.config(cursor="watch")
            
        self._is_batch_calculating = True   

        try:

                
            # ---> NEU: VAR-Modus beim Bildwechsel killen <--- ACHTUNG GEHÖRT DAS HIER HIN???????????????
            if getattr(self, 'candidate_view_active', False):
                self.clear_var_mode()
            
            side = self.active_camera_var.get()
            
            # =====================================================================
            # ---> ELA-FIX: Zustand direkt am Anfang unbestechlich synchronisieren!
            # =====================================================================
            self.current_side = side 
            
            # ---> DER FIX: Alte Treffer-Merkliste sofort löschen, damit bei Kamerawechsel 
            # oder Referenzbildern (Bild 0) keine alten Geister-Kreise übrig bleiben! <---
            self.last_orig_shots_to_draw = []
            
            side_origs = self.get_current_side_origs()
            
            # =========================================================================
            # ---> NEU: ELA-Optimierung! Wir berechnen den offiziellen Wettkampf-Radius
            # genau EINMAL pro Frame-Wechsel und speichern ihn im RAM.
            # =========================================================================
            # ---> ELA FIX: Der Dummy ist tot! Wir nutzen direkt den echten Parser <---
            d_config = self.package_data['config']
            
    
            ringwertung_aktiv = d_config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
            aktive_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
            #targets = self.dm.load_targets()
            targets = self.package_data['targets']
            
            decimals = d_config.getint('Zielscheibe', 'ringwertung_nachkommastellen', fallback=1)
            
            # 1. Fallback-Weiche: Wettkampf-Modus vs. Freies Schießen
            if ringwertung_aktiv and aktive_scheibe in targets:
                offizielles_kaliber_mm = float(targets[aktive_scheibe].get('kaliber_mm', 4.5))
            else:
                offizielles_kaliber_mm = d_config.getfloat('Erkennung', 'caliber_durchmesser', fallback=4.5)
            
            seite_str = "links" if side == 'left' else "rechts"
            px_x = d_config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
            px_y = d_config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
            avg_px = (px_x + px_y) / 2.0
            
            self.official_radius_px = (offizielles_kaliber_mm / 2.0) * avg_px
            # =========================================================================
            
            # UI updaten
            self.shot_jump_var.set(str(self.current_index))
            self.lbl_shot_total.config(text=f" / {len(side_origs)}")
            self.log_text.delete(1.0, tk.END)
            
            # ==========================================================
            # ---> SONDERFALL: INDEX 0 = DAS REFERENZBILD <---
            # ==========================================================
            if self.current_index == 0:
                
                # ---> NEU: Aufruf des zentralen Hilfe-Banners <---
                self.print_help_banner()
                
                self.print_log("SYSTEM", f"Zeige initialen Zustand für Kamera {side.upper()}.\n")
                
                # ---> NEU: Treffer-Anzeige konsequent zurücksetzen! <---
                self.lbl_current_scores.config(text="- keine -", fg="gray")
                self.current_engine_shots = []
                
                # Bilder laden (Mit schwarzem Fallback-Bild, falls nichts existiert)
                dummy_img = self.get_img(side_origs[0]) if side_origs else None
                h, w = dummy_img.shape[:2] if dummy_img is not None else (720, 1280)
                
                ref_name = next((f for f in self.all_files if f"referenz_{side}" in f), None)
                ref_img = self.get_img(ref_name) if ref_name else np.zeros((h, w, 3), dtype=np.uint8)
                
                mask_name = next((f for f in self.all_files if f"cumulative_startmask_{side}" in f), None)
                mask_img = self.get_img(mask_name) if mask_name else np.zeros((h, w), dtype=np.uint8)
                if len(mask_img.shape) == 3: mask_img = cv2.cvtColor(mask_img, cv2.COLOR_BGR2GRAY)
    
                # ---> NEU: Das echte alte Bild (mit Löchern) suchen <---
                cum_orig_name = next((f for f in self.all_files if f"cumulative_orig_{side}" in f), None)
                cum_orig_img = self.get_img(cum_orig_name) if cum_orig_name else ref_img.copy()
    
                # =====================================================================
                # ---> SEIDEN-MUSTER: Frame 0 bekommt auch sein eigenes Daten-Paket! <---
                # =====================================================================
                self.current_context = FrameContext(
                    frame_number=0,
                    shots=[],
                    orig_img=ref_img.copy(),
                    ref_img=ref_img.copy(),
                    live_img=ref_img.copy(),
                    clean_live_img=cum_orig_img.copy(),
                    history_mask=np.zeros((h, w), dtype=np.uint8),
                    diff_image=np.zeros_like(ref_img),
                    diff_gesamt_image=mask_img.copy() if mask_img is not None else np.zeros((h, w), dtype=np.uint8),
                    abrisskante=None,
                    shift_vector=(0, 0),
                    log_text=self.log_text.get("1.0", tk.END),
                    is_cached_run=True
                )
                
                # ---> DER FIX: Wir müssen Modus 4 manuell nullen, da er nicht im Cache liegt! <---
                self.last_raw_diff = np.zeros((h, w), dtype=np.uint8)
                self.last_thresh_raw = np.zeros((h, w), dtype=np.uint8)
                
                self.renderer.update_image_display()
                return
                
            # ==========================================================
            # ---> NORMALE SCHÜSSE (Index > 0) <---
            # ==========================================================
            target_idx = self.current_index - 1
            orig_name = side_origs[target_idx]
            
            self._is_batch_calculating = True 
            
            # ---> ELA-FIX: Den Dummy-Manager bauen und mitgeben! <---
            #d_dm = DummyDateiManager(self)
            
            # ---> SEIDEN-MUSTER: Wir übergeben die Kontrolle komplett an den Context! <---
            self.current_context = self.labor_context.process_frames(
                self, target_idx, side, side_origs, self.all_files, self.get_img#, d_dm
            )
            
            # Falls beim Verarbeiten etwas schiefging (z.B. keine Bilder gefunden)
            if not self.current_context:
                self.print_log("SYSTEM", f"FEHLER: Konnte den Kontext für Bild {target_idx + 1} nicht erstellen.")
                return

            # ---> Die Zeichen-Logik wurde komplett in LaborRendererDeLuebs verlagert! <---
            
            # 1. Radius berechnen (Holen wir uns noch kurz aus der Config, da es GUI/Render-Spezifisch ist)
            # ---> DER FIX: Zwingend in einen ganzzahligen Pixelwert (Integer) verwandeln! <---
            r_erkennung = int(round(self.official_radius_px)) 
            self.current_radius_px = r_erkennung
            
            # 2. Original-Treffer filtern
            if getattr(self, 'original_match_data', None):
                side_char = 'l' if side == 'left' else 'r'
                orig_shots_side = [s for s in self.original_match_data.get("timeline", []) if s.get('s') == side_char]
                curr_shots_side = [s for s in self.current_context.shots if s.get('side') == side]
                
                aligned = self.align_shots(orig_shots_side, curr_shots_side, r_erkennung * 2.5)
                
                shots_to_draw = []
                for o_idx, c_idx, dist in aligned:
                    if o_idx is not None and c_idx is not None:
                        curr_shot = curr_shots_side[c_idx]
                        frame_num = curr_shot.get('labor_frame_num', 0)
                        
                        if frame_num <= self.current_index:
                            shots_to_draw.append(orig_shots_side[o_idx])
                
                self.last_orig_shots_to_draw = shots_to_draw 
            else:
                self.last_orig_shots_to_draw = []
            
            # ---> NEU: Daten für den späteren Vergleich merken <---
            self.current_engine_shots = self.current_context.shots 
            
            # ---> NEU: Ringwertung in die GUI schreiben (MIT SCHUSS-NUMMER) <---
            side_shots = [s for s in self.current_context.shots if s['side'] == side]
            lines = []
            
            decimals = d_config.getint('Zielscheibe', 'ringwertung_nachkommastellen', fallback=1)
            
            for i, s in enumerate(side_shots):
                if s.get('labor_frame_num') == self.current_index:
                    lines.append(f"🎯 #{i+1}: {s['score']:.{decimals}f}")
                    
            if lines:
                self.lbl_current_scores.config(text="\n".join(lines), fg="#27ae60")
            else:
                self.lbl_current_scores.config(text="- keine -", fg="gray")

            self.renderer.update_image_display()
            
        finally:
            self._is_batch_calculating = False
            self.log_text.see(tk.END) # <--- Am Ende 1x sauber nach unten scrollen!
            
            self.root.config(cursor="")
            self.lbl_image.config(cursor="")
            if hasattr(self, 'img_container'):
                self.img_container.config(cursor="")
            if hasattr(self, 'entry_shot_jump'):
                self.entry_shot_jump.config(cursor="")
            self.update_frame_title()

    def align_shots(self, orig_shots, curr_shots, threshold):
        # ---> DELEGIERT AN DEN CONTEXT <---
        return self.labor_context.align_shots(orig_shots, curr_shots, threshold)

    def show_comparison(self):
        # ---> DELEGIERT AN DEN CONTEXT <---
        self.labor_context.show_comparison(self)

    def export_test_case(self):
        # ---> DELEGIERT AN DEN CONTEXT <---
        self.labor_context.export_test_case(self)

    def apply_to_live(self):
        # ---> DELEGIERT AN DEN CONTEXT <---
        self.labor_context.apply_to_live(self)

if __name__ == "__main__":
    import sys 
    
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass 
            
    root = tk.Tk()
    app = LaborApp(root)
    
    if len(sys.argv) > 1:
        zip_path = sys.argv[1]
        
        # =========================================================================
        # ---> DER FIX: Wir verzichten KOMPLETT auf topmost! <---
        # Das Live-System macht sich stattdessen selbst klein (Idee B).
        # Wir rufen das Fenster nur freundlich nach vorne.
        # =========================================================================
        root.lift()
        root.focus_force()
        
        root.after(100, lambda: app.load_zip(zip_path))
    else:
        root.after(100, lambda: app.load_local_config())
        
    root.mainloop()