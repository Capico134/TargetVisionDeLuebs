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
from LaborControlDeLuebs import LaborNavigationController, LaborPlaybackController, LaborToolController
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
        
        self.labor_context = LaborContext(None, self.dm)

        # ---> NEU: Unser Navigations-Controller <---
        self.nav_ctrl = LaborNavigationController(self)
        # ---> NEU: Unser Playback-Controller <---
        self.play_ctrl = LaborPlaybackController(self)
        # ---> NEU: Unser Tool-Controller <---
        self.tool_ctrl = LaborToolController(self)
        
        
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
            
            # ---> NEU: ELA-Handshake - Die historischen Matchdaten an das Model übergeben! <---
            self.labor_context.original_match_data = self.original_match_data
            
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
        if hasattr(self, 'labor_context') and self.labor_context:
            self.labor_context.original_match_data = self.original_match_data
        
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
                self.print_help_banner()
                self.lbl_current_scores.config(text="- keine -", fg="gray")
                self.current_engine_shots = []
                
                # ---> DELEGATION: Das Model kümmert sich um alles! <---
                self.current_context = self.labor_context.process_frames(self, -1, side, side_origs, self.all_files, self.get_img)
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

    # ---> DELEGATION AN DEN NAVIGATION-CONTROLLER <---
    def on_zoom_box_start(self, event): return self.nav_ctrl.on_zoom_box_start(event)
    def on_zoom_box_motion(self, event): return self.nav_ctrl.on_zoom_box_motion(event)
    def on_zoom_box_stop(self, event): return self.nav_ctrl.on_zoom_box_stop(event)
    def abort_zoom_box(self, event=None): return self.nav_ctrl.abort_zoom_box(event)
    def on_drag_start(self, event): return self.nav_ctrl.on_drag_start(event)
    def on_drag_motion(self, event): return self.nav_ctrl.on_drag_motion(event)
    def on_drag_stop(self, event): return self.nav_ctrl.on_drag_stop(event)
    def reset_view(self, event=None): return self.nav_ctrl.reset_view(event)
    def center_on_last_shot(self, event=None): return self.nav_ctrl.center_on_last_shot(event)
    def auto_zoom_and_center(self): return self.nav_ctrl.auto_zoom_and_center()
    def on_mouse_scroll(self, event): return self.nav_ctrl.on_mouse_scroll(event)
    # ---> DELEGATION AN DEN PLAYBACK-CONTROLLER <---
    def prev_shot(self): return self.play_ctrl.prev_shot()
    def next_shot(self): return self.play_ctrl.next_shot()
    def safe_prev_shot(self, event=None): return self.play_ctrl.safe_prev_shot(event)
    def safe_next_shot(self, event=None): return self.play_ctrl.safe_next_shot(event)
    def first_shot(self): return self.play_ctrl.first_shot()
    def last_shot(self): return self.play_ctrl.last_shot()
    def jump_to_shot(self, event=None): return self.play_ctrl.jump_to_shot(event)
    # ---> DELEGATION AN DEN TOOL-CONTROLLER <---
    def toggle_color_picker(self): return self.tool_ctrl.toggle_color_picker()
    def pick_color_from_event(self, event): return self.tool_ctrl.pick_color_from_event(event)
    def identify_shot_at_click(self, x, y, jump_to_frame=False): return self.tool_ctrl.identify_shot_at_click(x, y, jump_to_frame)
    def clear_highlight(self): return self.tool_ctrl.clear_highlight()
    def toggle_var_mode(self, step, event=None): return self.tool_ctrl.toggle_var_mode(step, event)
    def clear_var_mode(self, event=None): return self.tool_ctrl.clear_var_mode(event)
    def on_mouse_move(self, event): return self.tool_ctrl.on_mouse_move(event)
    def on_mouse_leave(self, event): return self.tool_ctrl.on_mouse_leave(event)

    def show_context_actions(self, actions):
        self.ui_builder.show_context_actions(actions)
    def clear_context_actions(self):
        self.ui_builder.clear_context_actions()
    
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