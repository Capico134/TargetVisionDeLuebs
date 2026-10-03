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
from datetime import datetime

# ---> HIER IMPORTIEREN WIR DEINE ECHTE ENGINE UND DEN MANAGER! <---
from DetectionDeLuebs import TargetDetector
from LaborRendererDeLuebs import LaborRenderer
from LaborUIDeLuebs import LaborUIBuilder

from DateiManagerDeLuebs import DateiManager
from StateManagerDeLuebs import StateManager

import LoggerDeLuebs
#from HandbuchDeLuebs import PARAMETER_LEXIKON

           
class DummyDateiManager:
    def __init__(self, app):
        self.app = app
        self.debug_images = {}
        self.export_folder = "labor_export"
        
    def save_debug_image(self, name, image):
        self.debug_images[name] = image.copy()
        if self.app.export_images_var.get():
            import os
            import cv2
            if not os.path.exists(self.export_folder):
                os.makedirs(self.export_folder)
            path = os.path.join(self.export_folder, f"{name}.png")
            cv2.imwrite(path, image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            return True  # <--- NEU: Meldet "Ja, physisch auf Festplatte exportiert!"
            
        return False # <--- NEU: Meldet "Wurde nur stumm im RAM abgelegt."
            
    def load_targets(self):
        # 1. PRIO: Nutze zwingend die historische zielscheiben.json aus dem ZIP-Archiv (Zeitkapsel)!
        if getattr(self.app, 'package_data', None) and self.app.package_data.get('targets'):
            return self.app.package_data['targets']
            
        # 2. FALLBACK: Das ZIP ist von früher und hat keine JSON an Bord. 
        # Wir nehmen die tagesaktuelle aus der Gegenwart von der Festplatte.
        return self.app.dm.load_targets()
        
    def write_log(self, msg):
        # ---> NEU: Stummschaltung für den StateManager <---
        pass


# ==========================================
# GUI UND LOGIK
# ==========================================
class LaborApp:
    def __init__(self, root):
        self.root = root
        self.renderer = LaborRenderer(self)
        self.ui_builder = LaborUIBuilder(self)
        
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
        self.hybrid_discard_faktor_var = tk.DoubleVar(value=2.5)
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
        #self.debug_subpixel_export_var = tk.BooleanVar(value=False) # <--- NEU
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
        
        # Dauer-Leuchten bei Zoom >= 5.0, normales Blinken bei < 5.0
        if getattr(self, 'zoom_factor', 1.0) >= 5.0:
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
        Zentraler Schalter: Gibt True zurück, wenn der User gerade aktiv zieht oder zoomt.
        Kann in Zukunft für neue Maus-Gesten beliebig erweitert werden.
        """
        is_zooming = getattr(self, 'is_zoom_box_active', False)
        is_panning = getattr(self, 'drag_start_x', None) is not None
        return is_zooming or is_panning
        
    def validate_float_chars(self, P):
        """Erlaubt nur Ziffern, Punkt, Minus, Plus und E (für wissenschaftliche Notation)"""
        return all(c in "0123456789+-.eE" for c in P)
        
    def validate_int_chars(self, P):
        """Erlaubt nur Ziffern, Plus und Minus"""
        return all(c in "0123456789+-" for c in P)

    def update_calib_sliders(self):
        """Holt die echten Config-Werte der aktuell aktiven Kamera in die GUI-Slider"""
        if getattr(self, 'package_data', None) and self.package_data.get('config'):
            parser = self.package_data['config']
            side = self.active_camera_var.get()
            seite_str = "links" if side == 'left' else "rechts"
            
            # ---> NEU: LabelFrame Titel anpassen <---
            if hasattr(self, 'calib_outer_frame'):
                self.calib_outer_frame.config(text=f" Kalibrierung: Kamera {seite_str.capitalize()} ")
            
            # ---> NEU: Sektion sicherstellen, anstatt bei Fehlen abzubrechen! <---
            if not parser.has_section('Kameras'):
                parser.add_section('Kameras')
                
            val_x = parser.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
            val_y = parser.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
            val_fisch = parser.getfloat('Kameras', f'fischaugenkorrektur_{seite_str}', fallback=0.0) 
            
            # ---> DER FIX: original_values ZUERST aktualisieren, bevor set() den Trace auslöst! <---
            if hasattr(self, 'orig_calib'):
                self.original_values[str(self.calib_x_var)] = self.orig_calib[f"{side}_x"]
                self.original_values[str(self.calib_y_var)] = self.orig_calib[f"{side}_y"]
                self.original_values[str(self.calib_fischauge_var)] = self.orig_calib.get(f"{side}_fisch", 0.0) 

            # Jetzt erst die GUI setzen, damit der Trace keinen falschen Alarm (Rot) schlägt
            self.calib_x_var.set(val_x)
            self.calib_y_var.set(val_y)
            self.calib_fischauge_var.set(val_fisch)

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


    # ---> NEU: Parameter 'show_gui' hinzugefügt, damit das Programm nicht crasht <---
    def print_log(self, side, msg, show_gui=False):
        """Simuliert den Log-Output der Engine in der GUI"""
        self.log_text.insert(tk.END, f"[{side.upper()}] {msg}\n")
        self.log_text.see(tk.END)

    def apply_config_to_ui(self, parser):
        """Zentrale Methode: Füttert alle UI-Slider mit den Werten eines ConfigParsers."""
        if parser:
            if not parser.has_section('Erkennung'):
                parser.add_section('Erkennung')
                
            self.original_values = {}
            
            # 1. SONDERFALL: Nur noch Legacy-Migration für Uralt-Configs (Pixel zu mm)
            if not parser.has_option('Erkennung', 'caliber_durchmesser') and parser.has_option('Erkennung', 'caliber_radius'):
                alt_r = parser.getfloat('Erkennung', 'caliber_radius', fallback=15.0)
                px_x = parser.getfloat('Kameras', 'px_pro_mm_x_links', fallback=5.0) if parser.has_section('Kameras') else 5.0
                px_y = parser.getfloat('Kameras', 'px_pro_mm_y_links', fallback=5.0) if parser.has_section('Kameras') else 5.0
                avg_px = (px_x + px_y) / 2.0
                calc_durchmesser = (alt_r / avg_px) * 2.0 if avg_px > 0 else 4.5
                parser.set('Erkennung', 'caliber_durchmesser', str(round(calc_durchmesser, 2)))

            # 2. DIE MAGIE: Automatische Zuweisung ALLER registrierten Slider
            self.migrated_keys = [] # <--- NEU: Merkliste für den Migrator
            
            # =========================================================================
            # ---> DER FIX: Den Slider-losen Parameter einfach mit auf die Liste packen! <---
            # !!!!!!!!!!!!!!!!!!!!!! DIE ECHTE LAZY INJECTION !!!!!!!!!!!!!!!!!!!!!!
            # =========================================================================
            if not parser.has_section('Zielscheibe'):
                parser.add_section('Zielscheibe')
            if not parser.has_option('Zielscheibe', 'ringwertung_nachkommastellen'):
                parser.set('Zielscheibe', 'ringwertung_nachkommastellen', '1')
                self.migrated_keys.append('ringwertung_nachkommastellen')
            if not parser.has_section('Erkennung'):
                parser.add_section('Erkennung')
            if not parser.has_option('Erkennung', 'debug_subpixel_export'):
                parser.set('Erkennung', 'debug_subpixel_export', 'no')
                self.migrated_keys.append('debug_subpixel_export')
            # =========================================================================
            
            # d_config = self.package_data['config']
            # dummy = d_config.getint('Zielscheibe', 'ringwertung_nachkommastellen', fallback=1) # Einfach nur aufrufen, damit der 

            for key, tk_var in self.registered_sliders.items():
                fallback_val = tk_var.get() # Den GUI-Standardwert als Rettungsanker nehmen
                
                # ---> NEU: Fehlt der Key in der ZIP-Config? Dann ab auf die Merkliste! <---
                if not parser.has_option('Erkennung', key):
                    self.migrated_keys.append(key)
                
                # Wir rufen absichtlich die get-Methoden MIT Fallback auf.
                if isinstance(tk_var, tk.BooleanVar):
                    val = parser.getboolean('Erkennung', key, fallback=fallback_val)
                elif isinstance(tk_var, tk.IntVar):
                    val = parser.getint('Erkennung', key, fallback=fallback_val)
                elif isinstance(tk_var, tk.DoubleVar):
                    val = parser.getfloat('Erkennung', key, fallback=fallback_val)
                        
                # DER ELA-FIX: Erst die Baseline setzen, DANN den Trace auslösen!
                self.original_values[str(tk_var)] = val
                tk_var.set(val)
            
            # =================================================================
            # ---> ELA FIX: Echte Originalwerte der Kameras für den Mittelklick sichern <---
            # =================================================================
            if not parser.has_section('Kameras'):
                parser.add_section('Kameras')
                
            # Da wir auch hier getfloat MIT Fallback nutzen, werden fehlende 
            # Kamera-Parameter (wie fischaugenkorrektur) sofort vom Parser geheilt!
            self.orig_calib = {
                'left_x': parser.getfloat('Kameras', 'px_pro_mm_x_links', fallback=5.0),
                'left_y': parser.getfloat('Kameras', 'px_pro_mm_y_links', fallback=5.0),
                'left_fisch': parser.getfloat('Kameras', 'fischaugenkorrektur_links', fallback=0.0),
                'right_x': parser.getfloat('Kameras', 'px_pro_mm_x_rechts', fallback=5.0),
                'right_y': parser.getfloat('Kameras', 'px_pro_mm_y_rechts', fallback=5.0),
                'right_fisch': parser.getfloat('Kameras', 'fischaugenkorrektur_rechts', fallback=0.0)
            }
            
            # ---> NEU: Initialen Push der Kalibrierungsdaten in die Slider erzwingen, 
            # BEVOR der Dirty-Marker scharfgeschaltet wird!
            self.update_calib_sliders()
            
            
    def get_img(self, name):
        """Holt ein Bild blitzschnell aus dem vorbereiteten RAM-Speicher"""
        return self.package_data['images'].get(name)

    def load_local_config(self):
        """Lädt die lokale config.ini im Stand-Alone Modus."""
        parser = self.dm.load_or_create_config()
        
        #Das macht jetzt schon AuditedConfig.py
        ## ---> NEU: Fehlende Keys auch bei lokaler Config ergänzen! <---
        #if parser:
        #    if not parser.has_section('Erkennung'):
        #        parser.add_section('Erkennung')
        #    for key, tk_var in self.registered_sliders.items():
        #        if not parser.has_option('Erkennung', key):
        #            # Key fehlt -> mit GUI-Wert ergänzen
        #            parser.set('Erkennung', key, str(tk_var.get()))
        
        self.package_data = {
            'config': parser,
            'images': {},
            'match_data': None
        }
        
        self.root.title("Labor & Einstellungen - Lokale config.ini")
        self.print_log("SYSTEM", "Stand-Alone Modus: Lokale config.ini geladen.")
        self.lbl_image.config(text="Stand-Alone Modus aktiv.\n(Klicke auf 'Erweiterte Einstellungen')", fg="white")
        
        # Exakt dieselbe Hilfsfunktion nutzen – keine Redundanz mehr!
        self.apply_config_to_ui(parser)

    def load_zip(self, filepath=None):
        if not filepath:
            filepath = filedialog.askopenfilename(title="Wähle ZIP", filetypes=[("ZIP", "*.zip")])
            
        if filepath:
            self._is_loading = True # <--- NEU: Ladesperre AKTIVIEREN
            
            self.current_zip_path = filepath
            # Vorläufiger Titel (damit was dasteht, falls das Laden einer Riesen-ZIP kurz dauert)
            self.root.title(f"Labor & Einstellungen  -  {os.path.basename(filepath)}")
            
            self.package_data = self.dm.import_match_package(filepath)
            if not self.package_data:
                messagebox.showerror("Fehler", "Konnte ZIP-Paket nicht laden!")
                return
                
            parser = self.package_data.get('config')
            
            self.apply_config_to_ui(parser)
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

            # 2. DANN DEN MIGRATOR-LOG SCHREIBEN (Damit er sichtbar bleibt!)
            if hasattr(self, 'migrated_keys') and self.migrated_keys:
                keys_str = ", ".join(self.migrated_keys)
                
                # A) Ausgabe in der Labor-GUI
                self.print_log("SYSTEM", f"🔧 Legacy-Migrator: {len(self.migrated_keys)} fehlende Parameter für diese Analyse ergänzt:")
                self.print_log("SYSTEM", f"   -> {keys_str}")
                
                # B) Ausgabe in der CMD-Konsole
                print(f"\n🔧 [LEGACY-MIGRATOR] {len(self.migrated_keys)} fehlende Parameter aus GUI-Standardwerten in '{os.path.basename(filepath)}' ergänzt:")
                print(f"   -> {keys_str}\n")
                
                # Merkliste wieder putzen
                self.migrated_keys = []
                
            self._is_loading = False # <--- NEU: Ladesperre LÖSEN

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
            self.root.focus()
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
        
        if char == 'w': cy   -= 0.2
        elif char == 's': cy += 0.2
        elif char == 'a': cx -= 0.2
        elif char == 'd': cx += 0.2

        # 2. Den neuen Wert speichern (wird dann beim nächsten "Test-Case-Export" auch physisch in die JSON geschrieben!)
        self.original_match_data['metadata'][center_key] = [cx, cy]
        
        # 3. Log ausgeben und Bild sofort neu rendern (stanzt die Engine neu und berechnet die Ringe neu!)
        self.print_log("SYSTEM", f"🎯 Zentrum {side.upper()} feinjustiert: X:{cx} Y:{cy}")
        self.on_param_change(force=True)
 
    def on_param_change(self, event=None, force=False):
        if not self.current_zip_path:
            return
            
        # ---> NEU: Blockiere Updates, während ein ZIP im Hintergrund geladen wird! <---
        if getattr(self, '_is_loading', False):
            return
            
        # Wenn 'Enter' im Textfeld gedrückt wurde, sofort aktualisieren
        if force:
            self.process_and_display()
            return
            
        # ---> NEU: Die Debounce-Logik (Idee B) <---
        # 1. Existiert schon ein laufender Timer? Dann brich ihn ab!
        if hasattr(self, '_param_timer') and self._param_timer is not None:
            self.root.after_cancel(self._param_timer)
            
        # 2. Starte einen neuen Timer (z.B. 300 Millisekunden)
        # Erst wenn 300 ms lang kein neues Event kam, wird process_and_display aufgerufen
        self._param_timer = self.root.after(300, self._apply_param_change)

    def _apply_param_change(self):
        """Die eigentliche Ausführung nach dem Zeitpuffer"""
        self._param_timer = None
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
                
            # 1. Ermitteln, in welcher Bildhälfte wir sind und die Basis-Koordinaten rechnen
            is_left = (x < self.current_img_w)
            raw_x = x if is_left else (x - self.current_img_w)
            
            real_x = int(raw_x / self.current_scale)
            real_y = int(y / self.current_scale)
            
            # Schutzplanken gegen Out-of-Bounds
            if hasattr(self, 'last_clean_live_img') and self.last_clean_live_img is not None:
                orig_h, orig_w = self.last_clean_live_img.shape[:2]
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
        if getattr(self, 'color_picker_active', False):
            return "break"
            
        # ---> DER FIX: Türsteher entfernt! Wir lassen den Klick erstmal zu. <---
        
        self.is_zoom_box_active = True
        self.zoom_box_start_x = event.x
        self.zoom_box_start_y = event.y
        
        # 4 hauchdünne UI-Linien erzeugen (falls noch nicht existent)
        if not hasattr(self, 'zoom_borders'):
            self.zoom_borders = [tk.Frame(self.img_container, bg="yellow") for _ in range(4)]
            
        return "break"
        
    #def on_zoom_box_motion(self, event):
    #    """Zeichnet den Rahmen butterweich über natives Tkinter (0% CPU, Anti-Glitch)"""
    #    if getattr(self, 'is_zoom_box_active', False):
    #        
    #        # 25 FPS Türsteher (0.040 Sekunden)
    #        current_time = time.time()
    #        if current_time - getattr(self, 'last_zoombox_update_time', 0) < 0.040:
    #            return
    #        self.last_zoombox_update_time = current_time
    #        
    #        x1, y1 = self.zoom_box_start_x, self.zoom_box_start_y
    #        x2, y2 = event.x, event.y
    #        
    #        min_x, max_x = min(x1, x2), max(x1, x2)
    #        min_y, max_y = min(y1, y2), max(y1, y2)
    #        
    #        t = 3 # Liniendicke
    #        
    #        w = max(t * 2, max_x - min_x)
    #        h = max(t * 2, max_y - min_y)
    #        
    #        # =========================================================================
    #        # DER FIX GEGEN DAS VERSCHWINDEN: 1 Pixel absichtlicher Overlap + Z-Order
    #        # =========================================================================
    #        # Wir machen die horizontalen Striche 2 Pixel breiter (w+2) und schieben sie 1px nach links
    #        self.zoom_borders[0].place(x=min_x - 1, y=min_y, width=w + 2, height=t)
    #        self.zoom_borders[1].place(x=min_x - 1, y=min_y + h - t, width=w + 2, height=t)
    #        
    #        # Die vertikalen Striche klemmen wir wie gehabt dazwischen
    #        self.zoom_borders[2].place(x=min_x, y=min_y + t, width=t, height=h - 2*t)
    #        self.zoom_borders[3].place(x=min_x + w - t, y=min_y + t, width=t, height=h - 2*t)
    #
    #        # Zwingt Windows, diese 4 Linien sofort ganz nach vorne zu rendern
    #        for border in self.zoom_borders:
    #            border.lift()
    #
    #    return "break"

    def on_zoom_box_motion(self, event):
        """Zeichnet den Rahmen butterweich über natives Tkinter (ohne Overlap-Flackern)"""
        if getattr(self, 'is_zoom_box_active', False):
            
            # ---> NEU: Floating-Point sicherer Türsteher für den Rahmen! <---
            if self.zoom_factor >= self.max_zoom_factor - 0.01:
                return "break"
                
            # 25 FPS Türsteher
            current_time = time.time()
            if current_time - getattr(self, 'last_zoombox_update_time', 0) < 0.040:
                return
            self.last_zoombox_update_time = current_time
            
            x1, y1 = self.zoom_box_start_x, self.zoom_box_start_y
            x2, y2 = event.x, event.y
            
            min_x, max_x = min(x1, x2), max(x1, x2)
            min_y, max_y = min(y1, y2), max(y1, y2)
            
            t = 2 # Liniendicke in Pixeln
            
            w = max(t * 2, max_x - min_x)
            h = max(t * 2, max_y - min_y)
            
            draw_x = min_x + getattr(self, 'pan_x', 0)
            draw_y = min_y + getattr(self, 'pan_y', 0)
            
            self.zoom_borders[0].place(x=draw_x, y=draw_y, width=w, height=t)
            self.zoom_borders[1].place(x=draw_x, y=draw_y + h - t, width=w, height=t)
            self.zoom_borders[2].place(x=draw_x, y=draw_y + 2*t, width=t, height=h - 4*t)
            self.zoom_borders[3].place(x=draw_x + w - t, y=draw_y + 2*t, width=t, height=h - 4*t)

        return "break"


    def on_zoom_box_stop(self, event):
        """Führt den Box-Zoom aus"""
        if getattr(self, 'is_zoom_box_active', False):
            self.is_zoom_box_active = False
            
            # UI-Linien wieder unsichtbar machen
            if hasattr(self, 'zoom_borders'):
                for border in self.zoom_borders:
                    border.place_forget()
                    
            self.apply_zoom_box(self.zoom_box_start_x, self.zoom_box_start_y, event.x, event.y)
        return "break"

    def abort_zoom_box(self, event=None):
        """Bricht das Aufziehen des Zoom-Rahmens ab, wenn ESC gedrückt wird."""
        if getattr(self, 'is_zoom_box_active', False):
            self.is_zoom_box_active = False
            self.zoom_box_start_x = None
            self.zoom_box_start_y = None
            
            # UI-Linien wieder unsichtbar machen
            if hasattr(self, 'zoom_borders'):
                for border in self.zoom_borders:
                    border.place_forget()
                    
            self.print_log("SYSTEM", "Zoom-Rahmen abgebrochen.")

    def on_drag_start(self, event):
        """Normaler Linksklick (Verschieben, Kalibrieren, Pipette)"""
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
        
        self.lbl_image.place(x=self.pan_x, y=self.pan_y)

    def on_drag_stop(self, event):
        """Normales Loslassen (Verschieben beenden oder Röntgen-Klick)"""
        # ---> DER FIX: Wenn wir im Zoom-Modus sind, triggern wir den Zoom! <---
        if getattr(self, 'is_zoom_box_active', False):
            return self.on_zoom_box_stop(event)

        if getattr(self, 'color_picker_active', False): return
        if getattr(self, 'tk_image', None) is None: return
        
        # ---> DER TÜRSTEHER GEGEN DEN SONDERFALL <---
        if self.drag_start_x is None or self.drag_start_y is None: 
            return

        dx = event.x_root - self.drag_start_x
        dy = event.y_root - self.drag_start_y
        dist = (dx**2 + dy**2)**0.5
        
        self.drag_start_x = None
        self.drag_start_y = None

        if dist < 5:  
            self.identify_shot_at_click(event.x, event.y)

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
        
        # Neuen Maßstab ermitteln
        h, w = self.last_live_img.shape[:2] if hasattr(self, 'last_live_img') and self.last_live_img is not None else (720, 1280)
        new_scale = (550.0 / h) * self.zoom_factor
        
        # Mittelpunkt der Box im aktuellen Anzeigebild
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        
        # Den Ausschnitt exakt auf die Mitte des Monitors mappen
        self.pan_x = int((container_w / 2.0) - (center_x / old_scale) * new_scale)
        self.pan_y = int((container_h / 2.0) - (center_y / old_scale) * new_scale)
        
        # Bild an die neue Position setzen und neu zeichnen
        self.lbl_image.place(x=self.pan_x, y=self.pan_y)
        self.renderer.update_image_display()
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

        # Koordinaten exakt wie beim Maus-Hover ausrechnen
        is_left = (x < self.current_img_w)
        raw_x = x if is_left else (x - self.current_img_w)
        real_x = int(raw_x / self.current_scale)
        real_y = int(y / self.current_scale)

        if hasattr(self, 'last_clean_live_img') and self.last_clean_live_img is not None:
            orig_h, orig_w = self.last_clean_live_img.shape[:2]
            real_x = max(0, min(real_x, orig_w - 1))
            real_y = max(0, min(real_y, orig_h - 1))
            
            # Farbe auslesen (BGR)
            b_val, g_val, r_val = self.last_clean_live_img[real_y, real_x]
            
            # In die Konfiguration der AKTUELLEN Kamera schreiben
            if getattr(self, 'package_data', None) and self.package_data.get('config'):
                parser = self.package_data['config']
                side_str = "Hintergrund_Links" if self.current_side == 'left' else "Hintergrund_Rechts"
                
                if not parser.has_section(side_str):
                    parser.add_section(side_str)
                
                parser.set(side_str, 'rgb_r', str(r_val))
                parser.set(side_str, 'rgb_g', str(g_val))
                parser.set(side_str, 'rgb_b', str(b_val))
                
                self.print_log("SYSTEM", f"🎨 WANDFARBE GEUPDATET ({side_str}): RGB({r_val}, {g_val}, {b_val}) gepickt an Position X:{real_x}, Y:{real_y}")
                
                # Engine sofort mit den neuen Farben zwingen neuzustarten!
                self.on_param_change(force=True)

    def start_calibration_assist(self):
        """Startet den Kalibrierungs-Assistenten ODER bricht ihn ab."""
        if not getattr(self, 'package_data', None):
            messagebox.showwarning("Fehler", "Bitte lade zuerst ein ZIP-Paket!")
            return
            
        # ---> DER FIX: Wenn der Modus schon aktiv ist, dient der Button als Abbruch! <---
        if getattr(self, 'calib_mode_active', False):
            self.cancel_calibration()
            return
            
        self.calib_mode_active = True
        self.calib_points = []
        self.btn_calib_assist.config(bg="#e74c3c", text="🔴 Assistent aktiv (Abbrechen)")
        self.lbl_image.config(cursor="crosshair")
        
        # ---> NEU: Backspace für "Rückgängig" binden <---
        self.root.bind('<BackSpace>', self.undo_calibration_click)
        
        # =========================================================================
        # ---> NEU: Extrem auffällige Warnung für das Zielprofil! <---
        # =========================================================================
        d_config = self.package_data['config']
        aktive_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
        
        self.print_log("KALIB", "▼" * 60, show_gui=True)
        self.print_log("KALIB", f"🛑  !!! AKTIVES PROFIL: {aktive_scheibe.upper()} !!!  🛑", show_gui=True)
        self.print_log("KALIB", "▲" * 60, show_gui=True)
        
        if "Laufende" in aktive_scheibe:
            self.print_log("KALIB", "⚠️ Achtung: Es ist ein Profil für Laufende Scheiben aktiv!", show_gui=True)
            
        self.update_calibration_instruction()
        
    def undo_calibration_click(self, event=None):
        """Macht den letzten Klick im Assistenten rückgängig."""
        if not getattr(self, 'calib_mode_active', False) or not self.calib_points:
            return
            
        # Letzten Punkt abstrakt entfernen
        removed_pt = self.calib_points.pop()
        self.print_log("KALIB", f"Letzter Klick rückgängig gemacht (noch {len(self.calib_points)}/16 Punkte).", show_gui=True)
        
        # ---> DER ELA-FIX: Pipeline zeichnet einfach den neuen Zustand ohne den Punkt! <---
        self.renderer.update_image_display()#full_rebuild=False) # <--- NEU
        self.update_calibration_instruction()  

    def cancel_calibration(self):
        """Bricht den Assistenten ab."""
        self.calib_mode_active = False
        self.calib_points = []
        self.btn_calib_assist.config(bg="#8e44ad", text="📏 Kalibrierung")
        self.lbl_image.config(cursor="")
        self.root.unbind('<BackSpace>') # Binding wieder lösen
        self.print_log("KALIB", "Assistent manuell abgebrochen.", show_gui=True)
        self.renderer.update_image_display()

    def update_calibration_instruction(self):
        """Aktualisiert die Anweisungen für den Benutzer, je nachdem, wie viele Klicks schon erfolgt sind."""
        steps = [
            "1/16: Klicke auf den LINKEN Rand des schwarzen Spiegels",
            "2/16: Klicke auf den RECHTEN Rand des schwarzen Spiegels",
            "3/16: Klicke auf den OBEREN Rand des schwarzen Spiegels",
            "4/16: Klicke auf den UNTEREN Rand des schwarzen Spiegels",
            "5/16: Klicke DIAGONAL LINKS OBEN am schwarzen Spiegel",
            "6/16: Klicke DIAGONAL RECHTS UNTEN am schwarzen Spiegel",
            "7/16: Klicke DIAGONAL RECHTS OBEN am schwarzen Spiegel",
            "8/16: Klicke DIAGONAL LINKS UNTEN am schwarzen Spiegel",
            "9/16: Klicke auf den LINKEN Rand des 9er-Rings",
            "10/16: Klicke auf den RECHTEN Rand des 9er-Rings",
            "11/16: Klicke auf den OBEREN Rand des 9er-Rings",
            "12/16: Klicke auf den UNTEREN Rand des 9er-Rings",
            "13/16: Klicke auf den LINKEN Rand des äußersten Rings",
            "14/16: Klicke auf den RECHTEN Rand des äußersten Rings",
            "15/16: Klicke auf den OBEREN Rand des äußersten Rings",
            "16/16: Klicke auf den UNTEREN Rand des äußersten Rings"
        ]
        
        if len(self.calib_points) < len(steps):
            self.print_log("KALIBRIERUNG", steps[len(self.calib_points)], show_gui=True)
            self.lbl_coords.config(text=f"Aktion: {steps[len(self.calib_points)]}")
        else:
            self.finish_calibration()

    def handle_calibration_click(self, event):
        """Sammelt die Klicks des Benutzers und löst ein Neuzeichnen aus."""
        if getattr(self, 'base_combined_img', None) is None or not hasattr(self, 'current_scale'):
            return
            
        x, y = event.x, event.y
        img_h, img_w = self.base_combined_img.shape[:2]
        if x < 0 or y < 0 or x >= img_w or y >= img_h: return

        is_left = (x < self.current_img_w)
        raw_x = x if is_left else (x - self.current_img_w)
        # ---> NEU: Echte Subpixel-Präzision durch das Zoomen nutzen! <---
        real_x = round(raw_x / self.current_scale, 4)
        real_y = round(y / self.current_scale, 4)
        
        self.calib_points.append((real_x, real_y))
        
        schritt = len(self.calib_points)
        self.print_log("KALIB", f"✓ Punkt {schritt}/16 gesetzt bei (X: {real_x}, Y: {real_y})", show_gui=True)
        
        # ---> DER ELA-FIX: Wir malen nicht mehr selbst, wir rufen die Pipeline! <---
        self.renderer.update_image_display()#full_rebuild=False) # <--- NEU
        self.update_calibration_instruction()

    def finish_calibration(self):
        """Berechnet aus den gesammelten Punkten die Empfehlungen inkl. Best-Fit Validierung."""
        
        
        self.root.unbind('<BackSpace>')
        self.calib_mode_active = False
        self.btn_calib_assist.config(bg="#8e44ad", text="📏 Kalibrierung")
        self.lbl_image.config(cursor="")
        
        if len(self.calib_points) != 16:
            self.print_log("KALIB", "Zu wenige Punkte gesammelt. Abbruch.", show_gui=True)
            return
            
        d_config = self.package_data['config']
        aktive_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
        targets = self.dm.load_targets()
        
        if aktive_scheibe not in targets:
            messagebox.showerror("Fehler", f"Scheibe '{aktive_scheibe}' nicht in zielscheiben.json gefunden!")
            return
            
        target_data = targets[aktive_scheibe]
        
        # 1. Reale Millimeter-Maße
        try:
            spiegel_mm = float(target_data.get('spiegel_durchmesser_mm', 30.5))
            ringe_mm = target_data.get('ringe_durchmesser_mm', {})
            neun_mm = float(ringe_mm.get('9', spiegel_mm * 0.5))
            
            if '1' in ringe_mm:
                aussen_mm = float(ringe_mm['1'])
            else:
                 aussen_mm = max([float(v) for v in ringe_mm.values()]) if ringe_mm else spiegel_mm * 2.0
        except ValueError:
            messagebox.showerror("Fehler", "Ungültige Millimeter-Werte in der zielscheiben.json!")
            return

        # 2. Punkte entpacken
        pts = self.calib_points
        spiegel_l, spiegel_r, spiegel_o, spiegel_u = pts[0], pts[1], pts[2], pts[3]
        diag1_o, diag1_u, diag2_o, diag2_u = pts[4], pts[5], pts[6], pts[7]
        neun_l, neun_r, neun_o, neun_u = pts[8], pts[9], pts[10], pts[11]
        aussen_l, aussen_r, aussen_o, aussen_u = pts[12], pts[13], pts[14], pts[15]

        # 3. Das exakte Zentrum auf Basis des 9er Rings ermitteln (am zuverlässigsten)
        cx = (neun_l[0] + neun_r[0]) / 2.0
        cy = (neun_o[1] + neun_u[1]) / 2.0

        # =========================================================================
        # A) Best-Fit Regressions-Analyse (Least Squares) über alle 3 Ringe
        # Minimiert den quadratischen Fehler über die gesamte Scheibe.
        # =========================================================================
        
        # Radien in echten Millimetern
        r_9 = neun_mm / 2.0
        r_s = spiegel_mm / 2.0
        r_a = aussen_mm / 2.0
        
        # Gemessene Pixel-Radien (X-Achse)
        p_9_x = abs(neun_r[0] - neun_l[0]) / 2.0
        p_s_x = abs(spiegel_r[0] - spiegel_l[0]) / 2.0
        p_a_x = abs(aussen_r[0] - aussen_l[0]) / 2.0
        
        # Gemessene Pixel-Radien (Y-Achse)
        p_9_y = abs(neun_u[1] - neun_o[1]) / 2.0
        p_s_y = abs(spiegel_u[1] - spiegel_o[1]) / 2.0
        p_a_y = abs(aussen_u[1] - aussen_o[1]) / 2.0
        
        # Umrechnung in gemessene "Pixel pro Millimeter" an den jeweiligen Radien
        y_data_x = np.array([p_9_x / r_9, p_s_x / r_s, p_a_x / r_a])
        y_data_y = np.array([p_9_y / r_9, p_s_y / r_s, p_a_y / r_a])
        x_data = np.array([r_9, r_s, r_a])
        
        # Lineare Regression (y = m*x + b)
        # b ist die Skalierung bei Radius 0 (das exakte optische Zentrum)
        # m ist die Steigung der Verzerrung
        m_x, b_x = np.polyfit(x_data, y_data_x, 1)
        m_y, b_y = np.polyfit(x_data, y_data_y, 1)
        
        px_mm_x = b_x
        px_mm_y = b_y
        
        # Die Fischaugenkorrektur (K) ergibt sich aus Steigung / Basis-Skalierung
        k_x = m_x / b_x if b_x != 0 else 0.0
        k_y = m_y / b_y if b_y != 0 else 0.0
        
        avg_korrektur = (k_x + k_y) / 2.0
        
        
        
        dist_diag1 = math.hypot(diag1_o[0] - diag1_u[0], diag1_o[1] - diag1_u[1])
        dist_diag2 = math.hypot(diag2_o[0] - diag2_u[0], diag2_o[1] - diag2_u[1])
        
        # =========================================================================
        # NEU: VALIDIERUNGS-CHECK & MONSTER-LOG
        # =========================================================================
        
        log_lines = []
        log_lines.append("\n" + "="*70)
        log_lines.append("🎯 KALIBRIERUNGS-PROTOKOLL")
        log_lines.append("="*70)
        
        log_lines.append("\n1. ROHE MAUSKLICKS (Pixel-Koordinaten):")
        log_lines.append(f"  Spiegel : L{spiegel_l}, R{spiegel_r}, O{spiegel_o}, U{spiegel_u}")
        log_lines.append(f"  Diagonal: LO{diag1_o}, RU{diag1_u}, RO{diag2_o}, LU{diag2_u}")
        log_lines.append(f"  9er-Ring: L{neun_l}, R{neun_r}, O{neun_o}, U{neun_u}")
        log_lines.append(f"  Außen   : L{aussen_l}, R{aussen_r}, O{aussen_o}, U{aussen_u}")
        
        log_lines.append(f"\n2. ERMITTELTE KONTROLL-DISTANZEN:")
        log_lines.append(f"  Spiegel Diagonale 1: {dist_diag1:.1f} px")
        log_lines.append(f"  Spiegel Diagonale 2: {dist_diag2:.1f} px")

        log_lines.append(f"\n3. BERECHNETE PARAMETER:")
        log_lines.append(f"  Zentrum (X/Y) : {cx:.2f} / {cy:.2f}")
        log_lines.append(f"  px_pro_mm (X) : {px_mm_x:.3f}")
        log_lines.append(f"  px_pro_mm (Y) : {px_mm_y:.3f}")
        log_lines.append(f"  Fischaugenkorr: {avg_korrektur:.5f}")

        def validate_point(name, pt, mm_real):
            r_mm_base = mm_real / 2.0
            r_mm_draw = r_mm_base * (1.0 + (r_mm_base * avg_korrektur))
            
            dx_px = pt[0] - cx
            dy_px = pt[1] - cy
            
            dx_mm = dx_px / px_mm_x if px_mm_x else 0
            dy_mm = dy_px / px_mm_y if px_mm_y else 0
            dist_mm = math.hypot(dx_mm, dy_mm)
            
            err_mm = dist_mm - r_mm_draw
            
            act_dist_px = math.hypot(dx_px, dy_px)
            px_per_mm_ray = act_dist_px / dist_mm if dist_mm > 0 else 0
            err_px = err_mm * px_per_mm_ray
            
            return err_px, err_mm

        log_lines.append("\n4. BEST-FIT VALIDIERUNG (Theorie vs. Klick):")
        log_lines.append("  (Minus = Klick war näher am Zentrum als berechnet)")
        
        def add_validation(section_name, mm_real, labels, points):
            log_lines.append(f"\n  ▶ {section_name} ({mm_real} mm):")
            for lbl, pt in zip(labels, points):
                err_px, err_mm = validate_point(lbl, pt, mm_real)
                log_lines.append(f"    {lbl:<12} -> Abweichung: {err_px:>+5.1f} px  |  {err_mm:>+6.2f} mm")

        add_validation("9er-Ring", neun_mm, ["Links", "Rechts", "Oben", "Unten"], [neun_l, neun_r, neun_o, neun_u])
        add_validation("Spiegel (Achsen)", spiegel_mm, ["Links", "Rechts", "Oben", "Unten"], [spiegel_l, spiegel_r, spiegel_o, spiegel_u])
        add_validation("Spiegel (Diag)", spiegel_mm, ["Links-Oben", "Rechts-Unten", "Rechts-Oben", "Links-Unten"], [diag1_o, diag1_u, diag2_o, diag2_u])
        add_validation("Außenring", aussen_mm, ["Links", "Rechts", "Oben", "Unten"], [aussen_l, aussen_r, aussen_o, aussen_u])

        log_lines.append("="*70 + "\n")
        
        # ... [Dein bestehender Code, log_lines.append("="*70 + "\n") etc.] ...

        # Einmal direkt vorab ins Log schreiben (zur Vorschau)
        for line in log_lines:
            self.print_log("KALIB", line, show_gui=True)
            
        # UI-Ergebnis ausgeben
        report = (
            "🎯 Kalibrierung Abgeschlossen!\n\n"
            "Vorgeschlagene Werte:\n"
            f"▶ px_pro_mm (X): {px_mm_x:.3f}\n"
            f"▶ px_pro_mm (Y): {px_mm_y:.3f}\n"
            f"▶ Fischaugenkorr.: {avg_korrektur:.5f}\n\n"
            "💡 Ein extrem detailliertes Protokoll (inkl. aller Koordinaten "
            "und Millimeter-Abweichungen) findest du jetzt unten im Log!"
        )
        
        def apply_values():
             # ---> NEU: ELA-Präzision (3 und 5 Nachkommastellen statt 2 und 4) <---
             self.calib_x_var.set(round(px_mm_x, 3))
             self.calib_y_var.set(round(px_mm_y, 3))
             self.calib_fischauge_var.set(round(avg_korrektur, 5))
             
             # Erzwingt den Neuaufbau der Bilder
             self.on_param_change(force=True)
             
             # Verzögertes Schreiben des Logs
             def write_log_delayed():
                 for line in log_lines:
                     self.print_log("KALIB", line, show_gui=True)
                 self.print_log("SYSTEM", "✅ Kalibrierungswerte erfolgreich übernommen und Bilder neu berechnet!", show_gui=True)
                 
             self.root.after(400, write_log_delayed)
             info_win.destroy()

        # =========================================================================
        # ---> NEU: Zwischenablage-Funktion <---
        # =========================================================================
        def copy_to_clipboard():
            full_log = "\n".join(log_lines)
            self.root.clipboard_clear()
            self.root.clipboard_append(full_log)
            # Kurzes Feedback, damit man weiß, dass es geklappt hat
            tk.messagebox.showinfo("Kopiert", "Das komplette Protokoll wurde in die Zwischenablage kopiert!", parent=info_win)
             
        info_win = tk.Toplevel(self.root)
        info_win.title("Kalibrierungs-Ergebnis")
        info_win.attributes('-topmost', True)
        
        tk.Label(info_win, text=report, justify=tk.LEFT, padx=20, pady=20, font=("Arial", 11)).pack()
        
        btn_frame = tk.Frame(info_win)
        btn_frame.pack(pady=10)
        
        # ---> NEU: Der mittlere Button in blau <---
        tk.Button(btn_frame, text="Werte übernehmen", command=apply_values, bg="#27ae60", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="📋 Log kopieren", command=copy_to_clipboard, bg="#3498db", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Abbrechen", command=info_win.destroy).pack(side=tk.LEFT, padx=5)
        
        self.renderer.update_image_display()
  
    def identify_shot_at_click(self, x, y, jump_to_frame=False):
        """Sucht den Treffer unter der Maus und blendet die Frame-Info ein (oder springt dorthin)"""
        if getattr(self, 'base_combined_img', None) is None: return
            
        is_left = (x < self.current_img_w)
        raw_x = x if is_left else (x - self.current_img_w)
        real_x = int(raw_x / self.current_scale)
        real_y = int(y / self.current_scale)

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

    def update_frame_title(self):
        """Aktualisiert die Überschrift des Bild-Bereichs mit dynamischem Zoom und Shortcuts."""
        if not getattr(self, 'current_zip_path', None):
            return
            
        side = self.active_camera_var.get()
        zoom_str = f"Zoom: {self.zoom_factor:.1f}x"
        controls = "Rad: Zoom  |  L-Klick: Bewegen  |  R-Klick: Reset  |  M-Klick: Zentrieren  |  Strg+Ziehen: Rahmen"
        
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
        if not getattr(self, 'current_engine_shots', None) or not hasattr(self, 'current_scale'):
            return
            
        side = self.active_camera_var.get()
        current_frame_num = self.current_index
        
        # Alle Treffer dieses Bildes (und dieser Kamera) filtern
        valid_shots = [s for s in self.current_engine_shots if s.get('side') == side and s.get('labor_frame_num') == current_frame_num]
        
        if not valid_shots:
            self.print_log("SYSTEM", "Mittelklick: Kein Treffer in diesem Bild gefunden, auf den zentriert werden könnte.")
            return
            
        # Den absolut letzten Treffer aus der Liste schnappen
        latest_shot = valid_shots[-1]
        hx, hy = latest_shot['pos']
        
        # Fenstermaße aktualisieren und abrufen
        self.root.update_idletasks()
        container_w = self.img_container.winfo_width()
        container_h = self.img_container.winfo_height()
        
        # Auf welche der beiden Hälften (Links oder Rechts) wurde geklickt?
        is_left = (event.x < getattr(self, 'current_img_w', 0))
        
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
        
        # Bild verschieben
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
            
            # Verschiebung berechnen und Label exakt in diesem Moment umsetzen
            self.pan_x -= int(mx * scale_change - mx)
            self.pan_y -= int(my * scale_change - my)
            self.lbl_image.place(x=self.pan_x, y=self.pan_y)
            
        # Jetzt, wo das Bild passend verschoben ist, wird es passend groß gerendert!
        self.renderer.update_image_display()
        
        # Koordinaten-Anzeige manuell triggern, damit sie nach dem Zoom sofort stimmt
        self.on_mouse_move(event)

    def process_and_display(self):
        #self.root.focus()
        self.update_frame_title()
        if not self.current_zip_path: return
        
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
        targets = self.dm.load_targets()
        
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
            #self.image_frame.config(text=f" Live-Labor (Referenz & Startmaske)  |  📷 Kamera {side.upper()} ")
            self.print_log("SYSTEM", f"Zeige initialen Zustand für Kamera {side.upper()}.")
            
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

            # ZUWEISUNG: Links saubere Referenz, Rechts in Ansicht 5 das Bild mit Löchern!
            self.last_live_img = ref_img                # Linke UI-Hälfte
            self.last_clean_live_img = cum_orig_img     # Rechte UI-Hälfte (nur in Modus 5)
            self.last_diff_img = np.zeros_like(ref_img)
            self.last_diff_gesamt_img = mask_img
            self.last_ref_img = ref_img
            self.last_raw_diff = np.zeros((h, w), dtype=np.uint8)
            self.last_thresh_raw = np.zeros((h, w), dtype=np.uint8)
            self.last_history_mask = np.zeros((h, w), dtype=np.uint8)
            # ---> NEU: Geister-Abrisskante beim Zurückspringen löschen! <---
            self.last_abrisskante = None
            
            self.renderer.update_image_display()
            return
            
        # ==========================================================
        # ---> NORMALE SCHÜSSE (Index > 0) <---
        # ==========================================================
        target_idx = self.current_index - 1
        orig_name = side_origs[target_idx]
        
        #self.image_frame.config(text=f" Live-Labor (Mausrad = Zoom | Klick = Bewegen | Rechtsklick = Reset)  |  📄 {orig_name} ")
        
        # 1. DUMMYS AUFBAUEN
        # ---> ELA FIX <---
        d_config = self.package_data['config']
        d_dm = DummyDateiManager(self)
        d_sm = StateManager(d_config, d_dm)
        
        # 2. ECHTE ENGINE STARTEN
        detector = TargetDetector(d_config, d_dm, d_sm, self.print_log)
        
        ref_name = next((f for f in self.all_files if f"referenz_{side}" in f), None)
        if not ref_name: return
        ref_img = self.get_img(ref_name)
        detector.set_reference_image(ref_img, side)
        
        # =========================================================================
        # ---> ELA FIX: Beschütze das echte Zentrum vor der Auto-Erkennung! <---
        # =========================================================================
        if getattr(self, 'original_match_data', None):
            meta = self.original_match_data.get('metadata', {})
            center_key = 'center_l' if side == 'left' else 'center_r'
            if meta.get(center_key):
                d_sm.set_nullpunkt(side, meta[center_key][0], meta[center_key][1])
        
        startmask_name = next((f for f in self.all_files if f"cumulative_startmask_{side}" in f), None)
        if startmask_name:
            startmask_bgr = self.get_img(startmask_name)
            startmask_gray = cv2.cvtColor(startmask_bgr, cv2.COLOR_BGR2GRAY)
            state = d_sm.state_left if side == 'left' else d_sm.state_right
            state.cumulative_mask = startmask_gray
            self.print_log("SYSTEM", f"Fortsetzung erkannt! Start-Maske für {side} geladen.")
        
        # 3. TIME-TRAVEL SIMULATION
        for i in range(target_idx + 1):
            img = self.get_img(side_origs[i])
            
            if i == target_idx:
                self.log_text.insert(tk.END, "\n" + "▼"*70 + "\n")
                self.log_text.insert(tk.END, f"███  START DER LIVE-ANALYSE FÜR BILD-AUFNAHME ({i+1})  ███\n")
                self.log_text.insert(tk.END, "▼"*70 + "\n\n")
                
                # --- ELA: Alte Geister-Bilder aus der Zeitreise vor dem echten Frame löschen ---
                d_dm.debug_images.pop(f"diff_letzter_treffer_{side}", None)
                d_dm.debug_images.pop(f"diff_letzte_verworfene_auswertung_{side}", None)
                d_dm.debug_images.pop(f"letzte_abrisskante_{side}", None) # <--- NEU
                
                live_img = img.copy()
                clean_live_img = img.copy()
                
                temp_state = d_sm.state_left if side == 'left' else d_sm.state_right
                if temp_state.cumulative_mask is not None:
                    history_mask = temp_state.cumulative_mask.copy()
                else:
                    history_mask = np.zeros(img.shape[:2], dtype=np.uint8)
                    
            # ---> NEU: Zähle die Schüsse VOR der Erkennung <---
            shots_before = len(d_sm.shots)
            
            detector.detect_new_shot(img, side)
            
            # ---> NEU: Stemple alle neu hinzugekommenen Schüsse mit der Bildnummer <---
            shots_after = len(d_sm.shots)
            for j in range(shots_before, shots_after):
                d_sm.shots[j]['labor_frame_num'] = i + 1

        # 4. VISUALISIERUNG DER ENGINE-ERGEBNISSE
        # Hole das Diff-Bild direkt aus dem Dummy-DateiManager der Engine!
        # ---> NEU: Ringwertung aus dem StateManager in die GUI schreiben (MIT SCHUSS-NUMMER) <---
        side_shots = [s for s in d_sm.shots if s['side'] == side]
        lines = []
        
        # ---> DER FIX: Auslesen der Nachkommastellen direkt aus der Config! <---
        # Wir holen den Wert einmal pro Frame-Wechsel frisch aus dem RAM-ConfigParser.
        decimals = d_config.getint('Zielscheibe', 'ringwertung_nachkommastellen', fallback=1)
        
        for i, s in enumerate(side_shots):
            if s.get('is_new', False):
                # Dynamische Formatierung auf die eingestellte Nachkommastellen-Zahl (ohne das Wort "Ringe")
                lines.append(f"🎯 #{i+1}: {s['score']:.{decimals}f}")
                
        if lines:
            self.lbl_current_scores.config(text="\n".join(lines), fg="#27ae60")
        else:
            self.lbl_current_scores.config(text="- keine -", fg="gray")
            
            
        diff_img = d_dm.debug_images.get(f"diff_letzter_treffer_{side}")
        if diff_img is None:
            # Fallback falls kein Treffer erkannt wurde
            diff_img = d_dm.debug_images.get(f"diff_letzte_verworfene_auswertung_{side}", np.zeros_like(live_img))
        
        if len(diff_img.shape) == 2:
            diff_img = cv2.cvtColor(diff_img, cv2.COLOR_GRAY2BGR)
            
        # ====================================================================
        # ---> ELA-Render-Pipeline: Optische Schichten (Layers) <---
        # Schicht 1 (Hintergrund): Alte berechnete Treffer (Grün)
        # Schicht 2 (Mitte): Original-Treffer aus der JSON (Gelb)
        # Schicht 3 (Vordergrund): Aktuellster Treffer (Rot)
        # ====================================================================
        
        # Radien sauber runden
        r_erkennung = round(detector.get_caliber_radius(side))
        r_offiziell = round(self.official_radius_px)
        self.current_radius_px = r_erkennung  # Für das Maus-Fadenkreuz speichern!

        # --- LAYER 1: Alte Treffer (Grün) ---
        for shot in d_sm.shots:
            if shot['side'] == side and not shot.get('is_new', False):
                draw_pos = (int(round(shot['pos'][0])), int(round(shot['pos'][1])))
                cv2.circle(live_img, draw_pos, r_erkennung, (0, 255, 0), 1)
                
        self.last_orig_shots_to_draw = [] # <--- NEU: Vorab leeren
        
        # --- LAYER 2: Original-Treffer aus match.json (Gelb) ---
        if getattr(self, 'show_orig_hits_var', None) and self.show_orig_hits_var.get() and getattr(self, 'original_match_data', None):
            side_char = 'l' if side == 'left' else 'r'
            orig_shots_side = [s for s in self.original_match_data.get("timeline", []) if s.get('s') == side_char]
            curr_shots_side = [s for s in d_sm.shots if s.get('side') == side]
            
            # Smart Alignment
            aligned = self.align_shots(orig_shots_side, curr_shots_side, r_erkennung * 2.5)
            
            shots_to_draw = []
            for o_idx, c_idx, dist in aligned:
                if o_idx is not None and c_idx is not None:
                    curr_shot = curr_shots_side[c_idx]
                    frame_num = curr_shot.get('labor_frame_num', 0)
                    
                    if frame_num <= self.current_index:
                        shots_to_draw.append(orig_shots_side[o_idx])
            
            self.last_orig_shots_to_draw = shots_to_draw 
            
            for s in shots_to_draw:
                hx = int(round(s['x']))
                hy = int(round(s['y']))
                # Wieder zurück auf knackig scharfe Standard-Pixel ohne Kantenglättung!
                cv2.circle(live_img, (hx, hy), r_offiziell, (0, 255, 255), 1)
                cv2.circle(live_img, (hx, hy), 1, (0, 255, 255), 0)
        
        # --- LAYER 3: Neue Treffer (Rot - Immer ganz oben!) ---
        for shot in d_sm.shots:
            if shot['side'] == side and shot.get('is_new', False):
                draw_pos = (int(round(shot['pos'][0])), int(round(shot['pos'][1])))
                cv2.circle(live_img, draw_pos, r_erkennung, (0, 0, 255), 1)
        
        
        # ====================================================================
        # ---> NEU: Daten für den späteren Vergleich merken <---
        self.current_engine_shots = d_sm.shots 
        #self.current_side = side # WURDE SCHON GANZ OBEN GEMACHT!!

        # ---> NEU: Alle nötigen Bilder aus der Engine fischen <---
        h, w = live_img.shape[:2]
        
        # ---> DER FIX: Diff-Gesamt 100% sicher aus dem StateManager holen! <---
        temp_state = d_sm.state_left if side == 'left' else d_sm.state_right
        if temp_state.cumulative_mask is not None:
            diff_gesamt_img = temp_state.cumulative_mask.copy()
        else:
            diff_gesamt_img = np.zeros((h, w), dtype=np.uint8)
            
            
        ref_img = d_dm.debug_images.get(f"referenz_{side}")
        if ref_img is None:
            ref_img = np.zeros((h, w, 3), dtype=np.uint8)

        # Bilder für butterweiches Zoomen im RAM zwischenspeichern
        self.last_live_img = live_img
        self.last_clean_live_img = clean_live_img.copy() # <--- NEU: Das nackte Bild retten!
        self.last_diff_img = diff_img
        self.last_diff_gesamt_img = diff_gesamt_img
        self.last_ref_img = ref_img
        
        # ---> NEU: Abrisskante aus dem Dummy-Manager fischen <---
        self.last_abrisskante = d_dm.debug_images.get(f"letzte_abrisskante_{side}")

        
        
        # ==========================================================
        # ---> NEU: Den echten RAW-Diff-Wert berechnen (Modus 4) <---
        # ==========================================================
        if len(ref_img.shape) == 3 and 'clean_live_img' in locals():
            k = self.blur_kernel_size_var.get()
            
            # 1. Wir nutzen zwingend das saubere Bild OHNE gezeichnete Kreise!
            live_blur = cv2.GaussianBlur(clean_live_img, (k, k), 0)
            
            # Die Engine nutzt intern self.ref_left, und das ist geblurrt gespeichert.
            ref_blur = cv2.GaussianBlur(ref_img, (k, k), 0)
            
            norm_live = detector.normalize_brightness(ref_blur, live_blur)
            diff_bgr = cv2.absdiff(ref_blur, norm_live)
            raw_diff = np.max(diff_bgr, axis=2) # Unser Farb-Hack!
            
            # =========================================================================
            # ---> NEU: Matrix-Simulation für das Labor (Ansicht 4 synchron halten!) <---
            # =========================================================================
            if self.farb_bonus_aktiv_var.get():
                bg_sec = 'Hintergrund_Links' if side == 'left' else 'Hintergrund_Rechts'
                r_tgt = d_config.getint(bg_sec, 'rgb_r')
                g_tgt = d_config.getint(bg_sec, 'rgb_g')
                b_tgt = d_config.getint(bg_sec, 'rgb_b')
                
                sum_tgt = float(r_tgt + g_tgt + b_tgt)
                if sum_tgt == 0: sum_tgt = 1.0
                target_norm = np.array([b_tgt/sum_tgt, g_tgt/sum_tgt, r_tgt/sum_tgt], dtype=np.float32)
                
                live_float = norm_live.astype(np.float32)
                live_sum = np.sum(live_float, axis=2, keepdims=True)
                live_sum[live_sum == 0] = 1.0
                live_norm = live_float / live_sum
                
                dist_matrix = np.linalg.norm(live_norm - target_norm, axis=2) * 1000.0
                
                self.last_color_dist = dist_matrix # Distanz für die Maus retten!
                
                # =========================================================================
                # ---> NEU: ELA-konforme Multiplikator-Logik mit Rausch-Plateau <---
                # =========================================================================
                limit = self.farb_bonus_limit_var.get()
                multiplier = 1.0 - (dist_matrix / limit)
                
                # Boost um 15% (Rausch-Ausgleich), aber hart bei 1.0 abriegeln!
                multiplier = np.clip(multiplier * 1.15, 0.0, 1.0)
                
                kurve = self.farb_bonus_kurve_var.get()
                if kurve != 1.0:
                    multiplier = multiplier ** kurve
                
                self.last_color_multiplier = multiplier 
                
                raw_diff = np.clip(raw_diff.astype(np.float32) * multiplier, 0, 255).astype(np.uint8)
            else:
                self.last_color_multiplier = None

            # ---> NEU: Wir führen den Threshold VORHER aus, genau wie die Engine! <---


            hit_tol = self.hit_tolerance_var.get()
            _, thresh_raw = cv2.threshold(raw_diff, hit_tol, 255, cv2.THRESH_BINARY)
            self.last_thresh_raw = thresh_raw.copy()

            self.last_raw_diff = raw_diff.copy() # Für die farbige Anzeige
            
            if 'history_mask' in locals():
                self.last_history_mask = history_mask.copy()
            else:
                self.last_history_mask = np.zeros((h, w), dtype=np.uint8)        

        
        self.renderer.update_image_display()

    def align_shots(self, orig_shots, curr_shots, threshold):
        """Robustes Greedy-Alignment, das Aussetzer und OpenCV-Reihenfolge-Änderungen verzeiht."""
        aligned = []
        used_curr = set()
        
        # 1. Wir suchen für jeden Original-Schuss den perfekten, noch freien Partner
        for i, orig in enumerate(orig_shots):
            ox, oy = orig['x'], orig['y']
            
            best_j = None
            best_dist = float('inf')
            
            # Wir gucken uns die aktuellen Schüsse an (mit einem großzügigen Puffer für vertauschte Reihenfolgen)
            start_j = max(0, i - 15)
            end_j = min(len(curr_shots), i + 15)
            
            for j in range(start_j, end_j):
                if j in used_curr: continue
                cx, cy = int(curr_shots[j]['pos'][0]), int(curr_shots[j]['pos'][1])
                dist = np.hypot(cx - ox, cy - oy)
                
                # Gierig den absolut nächsten Schuss schnappen, der innerhalb des Limits liegt
                if dist < threshold and dist < best_dist:
                    best_dist = dist
                    best_j = j
                    
            if best_j is not None:
                used_curr.add(best_j)
                aligned.append((i, best_j, best_dist))
            else:
                # Kein passender Partner im Umkreis gefunden -> Schuss fehlt in der Neuberechnung
                aligned.append((i, None, None))
                
        # 2. Jetzt sammeln wir alle NEUEN Schüsse ein, die bisher keinen Original-Partner gefunden haben
        for j in range(len(curr_shots)):
            if j not in used_curr:
                aligned.append((None, j, None))
                
        # 3. Liste sortieren, damit sie in der Tabelle chronologisch hübsch aussieht
        def sort_key(item):
            o_idx, c_idx, d = item
            if o_idx is not None: return o_idx * 1000
            if c_idx is not None: return (c_idx * 1000) + 500
            return 999999
            
        aligned.sort(key=sort_key)
        return aligned

    def show_comparison(self):
        if not self.current_zip_path or not getattr(self, 'original_match_data', None) or not self.orig_files:
            return

        # 1. Info-Fenster öffnen
        comp_win = tk.Toplevel(self.root)
        comp_win.title(f"📊 Integrations-Check: Live-Parameter vs. Original-Match")
        
        sf = self.root.winfo_fpixels('1i') / 96.0
        w, h = int(1600 * sf), int(750 * sf) # Etwas breiter gemacht für die Ringwerte
        comp_win.geometry(f"{w}x{h}")
        
        # ---> DER FIX: transient und topmost restlos entfernt! <---
        # Wir holen das Fenster nur einmalig sanft nach vorne, ohne es festzunageln.
        comp_win.lift()
        comp_win.focus_force()

        # =====================================================================
        # ---> Feste Werkzeugleiste für Buttons oben <---
        # =====================================================================
        btn_frame = tk.Frame(comp_win)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        def copy_to_clipboard():
            full_log = txt.get("1.0", tk.END)
            self.root.clipboard_clear()
            self.root.clipboard_append(full_log)
            tk.messagebox.showinfo("Kopiert", "Das komplette Protokoll wurde in die Zwischenablage kopiert!", parent=comp_win)
            
        tk.Button(btn_frame, text="📋 In Zwischenablage kopieren", command=copy_to_clipboard, bg="#3498db", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT)

        # =====================================================================
        # ---> Text-Frame mit Scrollbar <---
        # =====================================================================
        txt_frame = tk.Frame(comp_win)
        txt_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        scrollbar = tk.Scrollbar(txt_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        txt = tk.Text(txt_frame, font=("Consolas", 12), bg="#1e1e1e", fg="#00ff00", padx=10, pady=10, yscrollcommand=scrollbar.set)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=txt.yview)

        txt.insert(tk.END, "Führe komplette Neuberechnung aller Schüsse durch... Bitte warten...\n")
        comp_win.update()

        # 2. Voller Simulations-Durchlauf (Stumm im Hintergrund)
        d_config = self.package_data['config']
        
        ## Auch hier sicherstellen, dass der Parameter im RAM-Parser existiert
        #if not d_config.has_section('Zielscheibe'):
        #    d_config.add_section('Zielscheibe')
        #    
        #if not d_config.has_option('Zielscheibe', 'ringwertung_nachkommastellen'):
        #    d_config.set('Zielscheibe', 'ringwertung_nachkommastellen', '1')
        #    print("🔧 [LAZY-INJECTION] Parameter 'ringwertung_nachkommastellen=1' für Integrations-Check ergänzt.")

        d_dm = DummyDateiManager(self)
        d_sm = StateManager(d_config, d_dm)
        detector = TargetDetector(d_config, d_dm, d_sm, lambda side, text, show_gui=False: None) 

        for s in ['left', 'right']:
            ref_name = next((f for f in self.all_files if f"referenz_{s}" in f), None)
            if ref_name:
                ref_img = self.get_img(ref_name)
                detector.set_reference_image(ref_img, s)
                
                if getattr(self, 'original_match_data', None):
                    meta = self.original_match_data.get('metadata', {})
                    center_key = 'center_l' if s == 'left' else 'center_r'
                    if meta.get(center_key):
                        d_sm.set_nullpunkt(s, meta[center_key][0], meta[center_key][1])
            
            startmask_name = next((f for f in self.all_files if f"cumulative_startmask_{s}" in f), None)
            if startmask_name:
                startmask_bgr = self.get_img(startmask_name)
                startmask_gray = cv2.cvtColor(startmask_bgr, cv2.COLOR_BGR2GRAY)
                state = d_sm.state_left if s == 'left' else d_sm.state_right
                state.cumulative_mask = startmask_gray

        frame_counts = {'left': 0, 'right': 0}
        for orig_name in self.orig_files:
            img = self.get_img(orig_name)
            s = 'left' if 'left' in orig_name else 'right'
            frame_counts[s] += 1
            curr_frame_num = frame_counts[s]
            
            shots_before = len(d_sm.shots)
            detector.detect_new_shot(img, s)
            shots_after = len(d_sm.shots)
            
            for idx in range(shots_before, shots_after):
                d_sm.shots[idx]['frame_num'] = curr_frame_num

        # 3. Ausgabe aufbereiten[cite: 11]
        txt.delete(1.0, tk.END)
        txt.insert(tk.END, f"VERGLEICH: KOMPLETTES MATCH (Aktuelle Slider-Werte vs. Original-JSON)\n")
        txt.insert(tk.END, "="*85 + "\n")

        # ---> NEU: Dynamische Nachkommastellen aus der Config auslesen <---
        decimals = d_config.getint('Zielscheibe', 'ringwertung_nachkommastellen', fallback=1)

        def build_side_comparison(side_name, side_char):
            cal_r = detector.get_caliber_radius(side_name) 
            orig_shots = [s for s in self.original_match_data.get("timeline", []) if s.get('s') == side_char]
            curr_shots = [s for s in d_sm.shots if s['side'] == side_name]
            
            if not orig_shots and not curr_shots: return 
            
            txt.insert(tk.END, f"\n--- KAMERA {side_name.upper()} ---\n")
            txt.insert(tk.END, f"Original Treffer: {len(orig_shots)} | Neu berechnet: {len(curr_shots)}\n")
            txt.insert(tk.END, "Legende: 'E' = Manuell editiert | '*' = Methode hat sich zum Original geändert\n")
            
            # Neuer, erweiterter Header mit Platz für die Ringwertung
            header = f"{'Nr':>3} | {'Bild':>4} | {'Orig-Methode':<25} | {'Neu-Methode':<25} | {'Orig (X,Y, Ring)':<27} | {'Neu (X,Y, Ring)':<27} | {'Dist':>6} | {'O-CV':>6} | {'N-CV':>6} | {'% Kal':<10}\n"
            txt.insert(tk.END, header)
            txt.insert(tk.END, "-"*165 + "\n")
            
            threshold = cal_r * 2.5  
            aligned = self.align_shots(orig_shots, curr_shots, threshold)
                    
            total_dist = 0.0
            match_count = 0
            
            for idx, (orig_idx, curr_idx, dist) in enumerate(aligned):
                if orig_idx is not None and curr_idx is not None:
                    orig = orig_shots[orig_idx]
                    curr = curr_shots[curr_idx]
                    
                    ox, oy = float(orig['x']), float(orig['y'])
                    cx, cy = float(curr['pos'][0]), float(curr['pos'][1])
                    
                    # Ringwerte auslesen
                    orig_score = float(orig.get('score', 0.0))
                    curr_score = float(curr.get('score', 0.0))
                    
                    dx, dy = cx - ox, cy - oy
                    dist = np.hypot(dx, dy)
                    
                    cal_d = cal_r * 2
                    pct = (dist / cal_d) * 100 if cal_d else 0
                    
                    total_dist += dist
                    match_count += 1
                    
                    warn = "⚠️" if pct > 25.0 else ""
                    edit_marker = "E" if orig.get('edited', False) else " "
                    
                    # =========================================================================
                    # ---> NEU: Original-Score dynamisch formatieren (Die ungeschminkte Wahrheit!)
                    # =========================================================================
                    o_score_str = f"{orig_score:.4f}".rstrip('0')
                    if o_score_str.endswith('.'): 
                        o_score_str += "0" # Aus "10." machen wir sauber wieder "10.0"
                    
                    # String-Zusammenbau inkl. formatierter Ringwertung
                    orig_str = f"O:{orig_idx+1:02d}{edit_marker} {ox:>5.1f},{oy:>5.1f} ({o_score_str})"
                    curr_str = f"N:{curr_idx+1:02d}  {cx:>5.1f},{cy:>5.1f} ({curr_score:.{decimals}f})"
                    
                    f_num = curr.get('frame_num', 0)
                    curr_method = curr.get('winner_method', 'Std')
                    orig_method = orig.get('winner_method', 'Unbekannt')
                    
                    display_curr_method = f"{curr_method}*" if orig_method != 'Unbekannt' and orig_method != curr_method else curr_method
                    
                    orig_cv, curr_cv = orig.get('cv_score', 0.0), curr.get('cv_score', 0.0)
                    pct_str = f"{pct:.1f}% {warn}"
                    
                    txt.insert(tk.END, f"{idx+1:3d} | #{f_num:<3} | {orig_method:<25} | {display_curr_method:<25} | {orig_str:<27} | {curr_str:<27} | {dist:6.1f}p | {orig_cv:6.1f} | {curr_cv:6.1f} | {pct_str:<10}\n")
                    
                elif orig_idx is not None:
                    orig = orig_shots[orig_idx]
                    edit_marker = "E" if orig.get('edited', False) else " "
                    ox, oy = float(orig['x']), float(orig['y'])
                    orig_score = float(orig.get('score', 0.0))
                    
                    # ---> HIER AUCH DIE NEUE FORMATIERUNG EINFÜGEN <---
                    o_score_str = f"{orig_score:.4f}".rstrip('0')
                    if o_score_str.endswith('.'): 
                        o_score_str += "0"
                        
                    orig_str = f"O:{orig_idx+1:02d}{edit_marker} {ox:>5.1f},{oy:>5.1f} ({o_score_str})"
                    orig_cv = orig.get('cv_score', 0.0)
                    orig_method = orig.get('winner_method', 'Unbekannt')
                    
                    txt.insert(tk.END, f"{idx+1:3d} | {'--':>4} | {orig_method:<25} | {'--- FEHLT ---':<25} | {orig_str:<27} | {'--- FEHLT ---':<27} | {'--':>6} | {orig_cv:6.1f} | {'--':>6} | {'-- ❌':<10}\n")
                    
                elif curr_idx is not None:
                    curr = curr_shots[curr_idx]
                    cx, cy = float(curr['pos'][0]), float(curr['pos'][1])
                    curr_score = float(curr.get('score', 0.0))
                    curr_str = f"N:{curr_idx+1:02d}  {cx:>5.1f},{cy:>5.1f} ({curr_score:.{decimals}f})"
                    curr_cv = curr.get('cv_score', 0.0)
                    f_num = curr.get('frame_num', 0)
                    curr_method = curr.get('winner_method', 'Std')
                    
                    txt.insert(tk.END, f"{idx+1:3d} | #{f_num:<3} | {'--- FEHLT ---':<25} | {curr_method:<25} | {'--- FEHLT ---':<27} | {curr_str:<27} | {'--':>6} | {'--':>6} | {curr_cv:6.1f} | {'-- 🆕':<10}\n")

            if match_count > 0:
                avg_dist = total_dist / match_count
                txt.insert(tk.END, "-"*165 + "\n")
                txt.insert(tk.END, f"Ø Abweichung {side_name.upper()} (nur gematchte Treffer): {avg_dist:.2f} Pixel\n")
                
        build_side_comparison('left', 'l')
        build_side_comparison('right', 'r')
        
        txt.config(state=tk.DISABLED)



    def export_test_case(self):
        """
        Exportiert das aktuell geladene Match inklusive der manuell 
        bearbeiteten/perfektionierten match.json und der AKTUELLEN GUI-Parameter (config.ini).
        """
        # 1. Sicherheitscheck: Ist überhaupt etwas geladen?
        if not getattr(self, 'current_zip_path', None) or not getattr(self, 'original_match_data', None) or not self.orig_files:
            messagebox.showwarning("Fehler", "Es ist kein Match geladen, das exportiert werden könnte!")
            return
    
        # 2. Ordnerstruktur vorbereiten
        export_dir = os.path.join(os.getcwd(), "testcases")
        os.makedirs(export_dir, exist_ok=True)
        
        base_name = os.path.basename(self.current_zip_path)
        default_name = base_name.replace(".zip", "_verbessert.zip")
        
        # 3. Speicher-Dialog öffnen
        save_path = filedialog.asksaveasfilename(
            initialdir=export_dir,
            initialfile=default_name,
            title="Golden Master Test-Case speichern",
            defaultextension=".zip",
            filetypes=[("ZIP Archive", "*.zip")]
        )
        
        if not save_path:
            return 
            
        try:
            # =========================================================================
            # NEU: 4. SILENT MATCH RECALCULATION (Die perfekten Schüsse generieren!)
            # =========================================================================
            # Wir machen hier genau das Gleiche wie in show_comparison(), aber STUMM.
            # ---> ELA FIX <---
            d_config = self.package_data['config']
            d_dm = DummyDateiManager(self)
            d_sm = StateManager(d_config, d_dm)
            detector = TargetDetector(d_config, d_dm, d_sm, lambda side, text, show_gui=False: None) 

            #with zipfile.ZipFile(self.current_zip_path, 'r') as zf:
            ### Start WEG
            # Setze Referenzen und Startmasken
            for s in ['left', 'right']:
                    # ---> DER FIX: Prüfen, ob die Kamera für diese Seite überhaupt noch aktiv ist! <---
                    state = d_sm.state_left if s == 'left' else d_sm.state_right
                    if not state:
                        continue # Kamera ist abgeschaltet -> alte Bilder im ZIP ignorieren
                        
                    ref_name = next((f for f in self.all_files if f"referenz_{s}" in f), None)
                    if ref_name:
                        detector.set_reference_image(self.get_img(ref_name), s)
                        
                        # ---> ELA FIX <---
                        if getattr(self, 'original_match_data', None):
                            meta = self.original_match_data.get('metadata', {})
                            center_key = 'center_l' if s == 'left' else 'center_r'
                            if meta.get(center_key):
                                d_sm.set_nullpunkt(s, meta[center_key][0], meta[center_key][1])
                    
                    startmask_name = next((f for f in self.all_files if f"cumulative_startmask_{s}" in f), None)
                    if startmask_name:
                        startmask_gray = cv2.cvtColor(self.get_img(startmask_name), cv2.COLOR_BGR2GRAY)
                        state.cumulative_mask = startmask_gray

            # Alle orig-Bilder durch die NEUEN Parameter jagen
            for orig_name in self.orig_files:
                img = self.get_img( orig_name)
                s = 'left' if 'left' in orig_name else 'right'
                detector.detect_new_shot(img, s)
            
            ### END WEG
            
            # =========================================================================
            # NEU: 5. EINE BRANDNEUE MATCH.JSON BAUEN
            # =========================================================================
            new_match_data = {
                "metadata": self.original_match_data.get("metadata", {}).copy(),
                "timeline": []
            }
            
            # Die Gesamt-Trefferzahlen in den Metadaten aktualisieren (falls sich was geändert hat)
            shots_l = [s for s in d_sm.shots if s['side'] == 'left']
            shots_r = [s for s in d_sm.shots if s['side'] == 'right']
            
            new_match_data["metadata"]["treffer_links"] = len(shots_l)
            new_match_data["metadata"]["treffer_rechts"] = len(shots_r)
            new_match_data["metadata"]["gesamtpunkte"] = len(d_sm.shots)
            
            # Wir bauen die neue Timeline aus den Schüssen der frisch durchgelaufenen Engine!
            for s in d_sm.shots:
                # Den Zeitstempel t_mono müssen wir faken oder aus dem Original übernehmen. 
                # Da wir offline keine perfekten Zeitstempel haben, ordnen wir sie chronologisch (1.0, 2.0, ...) an.
                # Oder besser: Wir versuchen, den Zeitstempel des alten, zugehörigen Schusses zu retten!
                
                # Wir suchen blind nach dem nächsten passenden Original-Schuss, um dessen 't' und 'edited'-Flag zu klauen
                side_char = "l" if s['side'] == 'left' else "r"
                orig_candidates = [o for o in self.original_match_data.get("timeline", []) if o.get('s') == side_char]
                
                closest_t = 0.0
                is_edited = False
                
                # Wenn wir im Labor per Slider arbeiten, sind das CV-generierte Schüsse, also "edited=False" 
                # (es sei denn, wir bauen später noch manuelles Schuss-Verschieben per Maus ins Labor ein).
                
                # Für den Moment: Einfach als neuen, perfekten Schuss in die Timeline schreiben.
                new_match_data["timeline"].append({
                    "t": float(len(new_match_data["timeline"]) + 1.0), 
                    "s": side_char,
                    "x": round(float(s['pos'][0]), 4),
                    "y": round(float(s['pos'][1]), 4),
                    "a": round(float(s['area']), 1),
                    "score": float(s.get('score', 0.0)),
                    "cv_score": round(float(s.get('cv_score', 0.0)), 1),
                    "winner_method": str(s.get('winner_method', 'Unbekannt')), # <--- NEU
                    "edited": False 
                })


            # =========================================================================
            # NEU: 6. ELA Export mit Overwrite-Schutz (.tmp Tausch)
            # =========================================================================
            parser = self.package_data.get('config')
            if parser:
                string_io = io.StringIO()
                parser.write(string_io)
                new_ini_str = string_io.getvalue()
            else:
                new_ini_str = None
                
            # Prüfen, ob wir das Original-ZIP überschreiben wollen
            is_overwrite = (os.path.abspath(save_path) == os.path.abspath(self.current_zip_path))
            actual_save_path = save_path + ".tmp" if is_overwrite else save_path
                
            success = self.dm.export_match_package(
                filepath=actual_save_path,
                match_data=new_match_data,
                config_string=new_ini_str,
                source_zip=self.current_zip_path,
                apply_diet_filter=True
            )
            
            if success:
                # Heimlicher Tausch, falls wir überschrieben haben
                if is_overwrite:
                    os.remove(self.current_zip_path) # Altes Original löschen
                    os.rename(actual_save_path, self.current_zip_path) # Temp-Datei umbenennen
                    
                messagebox.showinfo("Erfolg", f"Test-Case erfolgreich aktualisiert:\n{os.path.basename(save_path)}")
            else:
                messagebox.showerror("Fehler", "Beim Exportieren ist ein Fehler aufgetreten.")
            
        except Exception as e:
            messagebox.showerror("Fehler", f"Beim Exportieren ist ein Fehler aufgetreten:\n{str(e)}")

    def apply_to_live(self):
        """
        Aktualisiert die physische config.ini und baut (falls Live-Tuning) ein Handover-Paket
        sowie Vorher/Nachher-Backups zur Dokumentation.
        """
        if not getattr(self, 'package_data', None):
            messagebox.showwarning("Fehler", "Es ist keine Konfiguration geladen!")
            return

        # ---> NEU: Die 3-Wege Text-Weiche <---
        current_path = getattr(self, 'current_zip_path', '')

        if not current_path:
            # Fall 1: Stand-Alone Modus (Nur lokale config.ini)
            titel = "Globale Einstellungen speichern?"
            text = (
                "Möchtest du diese Werte direkt in die System-Konfiguration schreiben?\n\n"
                "▶ Sie gelten ab sofort als Standard für alle NEUEN Matches.\n\n"
                "Das Labor wird danach geschlossen."
            )
        elif os.path.basename(current_path) == "Live_Tuning_Bridge.zip":
            # Fall 2: Live-Tuning am Schießstand
            titel = "Live-System aktualisieren?"
            text = (
                "Möchtest du diese Einstellungen an das laufende System am Schießstand senden?\n\n"
                "▶ Das aktuelle Match wird sofort damit fortgesetzt.\n"
                "▶ Das Labor wird danach geschlossen."
            )
        else:
            # Fall 3: Altes Highscore-Match geladen
            titel = "Als neuen Standard speichern?"
            text = (
                "Möchtest du diese Werte als neuen Standard für die Zukunft übernehmen?\n\n"
                "WICHTIG: Das geladene Match-Archiv bleibt davon unberührt! "
                "Diese Werte gelten nur für NEUE Matches.\n\n"
                "Das Labor wird danach geschlossen."
            )

        antwort = messagebox.askyesno(titel, text)
        if not antwort:
            return
            
            
        try:
            current_path = getattr(self, 'current_zip_path', '')
            export_dir = os.path.join(os.getcwd(), "labor_export")
            os.makedirs(export_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_basename = os.path.basename(current_path).replace(".zip", "") if current_path else "Backup"

            # =========================================================
            # ---> WIEDER DA: Das "Vorher"-Backup <---
            # =========================================================
            if current_path and os.path.exists(current_path):
                backup_vorher_path = os.path.join(export_dir, f"{safe_basename}_Vorher_{timestamp}.zip")
                shutil.copy2(current_path, backup_vorher_path)

            # 1. & 2. RAM-Config in String wandeln und Bulk-Update-Dict bauen
            parser = self.package_data.get('config')
            updates = {}
            if parser:
                string_io = io.StringIO()
                parser.write(string_io)
                new_ini_str = string_io.getvalue()
                
                # Sauberes Dictionary für das physische config.ini Backup-Update
                for section in parser.sections():
                    updates[section] = {}
                    for key, val in parser.items(section):
                        updates[section][key] = str(val)
            else:
                new_ini_str = None
 
            # 3. Physische config.ini aktualisieren (Kommentare bleiben erhalten!)
            self.dm.update_ini_file_bulk(updates)

            # 4. Prüfen: Sind wir im "Live-Tuning" Modus? (Die Bridge-Weiche!)
            if current_path and os.path.basename(current_path) == "Live_Tuning_Bridge.zip":
                
                # Wir müssen die aktuellen Masken/Diffs berechnen, um sie an TargetVision zu übergeben
                d_config = self.package_data['config']  
                d_dm = DummyDateiManager(self)
                d_sm = StateManager(d_config, d_dm)
                detector = TargetDetector(d_config, d_dm, d_sm, lambda side, text, show_gui=False: None)

                # =====================================================================
                # ---> DER FIX: Referenzen, Nullpunkte & Startmasken VORAB setzen! <---
                # =====================================================================
                for s in ['left', 'right']:
                    state = d_sm.state_left if s == 'left' else d_sm.state_right
                    if not state: 
                        continue
                        
                    ref_name = next((f for f in self.all_files if f"referenz_{s}" in f), None)
                    if ref_name:
                        detector.set_reference_image(self.get_img(ref_name), s)
                        if getattr(self, 'original_match_data', None):
                            meta = self.original_match_data.get('metadata', {})
                            center_key = 'center_l' if s == 'left' else 'center_r'
                            if meta.get(center_key):
                                d_sm.set_nullpunkt(s, meta[center_key][0], meta[center_key][1])
                    
                    startmask_name = next((f for f in self.all_files if f"cumulative_startmask_{s}" in f), None)
                    if startmask_name:
                        startmask_gray = cv2.cvtColor(self.get_img(startmask_name), cv2.COLOR_BGR2GRAY)
                        state.cumulative_mask = startmask_gray

                # Jetzt die Aufnahmen sauber (und nur EINMAL) durchjagen
                for orig_name in self.orig_files:
                    s = 'left' if 'left' in orig_name else 'right'
                    temp_state = d_sm.state_left if s == 'left' else d_sm.state_right
                    if not temp_state: 
                        continue
                    detector.detect_new_shot(self.get_img(orig_name), s)

                # Die Bilder über den DateiManager temporär auf die Festplatte legen, damit der Exporter sie greifen kann
                for img_name, img_data in d_dm.debug_images.items():
                    self.dm.save_debug_image(img_name, img_data)

                # =========================================================
                # ---> NEU: Warten, bis der Koch alle Bilder auf die Platte geschrieben hat! <---
                # =========================================================
                if hasattr(self.dm, 'flush_image_queue'):
                    self.dm.flush_image_queue()
                    
                # =========================================================
                # ---> DER FIX 2: Die neuen JSON-Daten bauen! <---
                # =========================================================
                new_match_data = {
                    "metadata": self.original_match_data.get("metadata", {}).copy(),
                    "timeline": []
                }
                shots_l = [s for s in d_sm.shots if s['side'] == 'left']
                shots_r = [s for s in d_sm.shots if s['side'] == 'right']
                new_match_data["metadata"]["treffer_links"] = len(shots_l)
                new_match_data["metadata"]["treffer_rechts"] = len(shots_r)
                new_match_data["metadata"]["gesamtpunkte"] = len(d_sm.shots)
                
                for s in d_sm.shots:
                    side_char = "l" if s['side'] == 'left' else "r"
                    new_match_data["timeline"].append({
                        "t": float(len(new_match_data["timeline"]) + 1.0),
                        "s": side_char,
                        # ---> NEU: Mit 4 Nachkommastellen statt int() <---
                        "x": round(float(s['pos'][0]), 4),
                        "y": round(float(s['pos'][1]), 4),
                        "a": round(float(s['area']), 1),
                        "score": float(s.get('score', 0.0)),
                        "cv_score": round(float(s.get('cv_score', 0.0)), 1),
                        "winner_method": str(s.get('winner_method', 'Unbekannt')),
                        "edited": False
                    })
                
                # =========================================================
                # ---> WIEDER DA: Das "Nachher"-Backup <---
                # =========================================================
                backup_nachher_path = os.path.join(export_dir, f"{safe_basename}_Nachher_{timestamp}.zip")
                self.dm.export_match_package(
                    filepath=backup_nachher_path,
                    match_data=new_match_data,  # <--- HIER WAR NOCH self.original_match_data !!
                    source_folder=self.dm.DEBUG_FOLDER,
                    apply_diet_filter=False 
                )

                # Handover-Paket schnüren (Nimmt die Bilder direkt aus dem debug_bilder Ordner)
                handover_path = os.path.join(export_dir, "Live_Tuning_Handover.zip")
                self.dm.export_match_package(
                    filepath=handover_path,
                    match_data=new_match_data,  # <--- UND AUCH HIER MUSS new_match_data HIN !!
                    source_folder=self.dm.DEBUG_FOLDER,
                    apply_diet_filter=False 
                )
                self.print_log("SYSTEM", "Handover-Paket und Backups erstellt.")

            self.print_log("SYSTEM", "Schließe Labor...")
            self.root.destroy() 

        except Exception as e:
            # ---> NEU: Der Fehler-Röntgenblick für die Konsole! <---
            import traceback
            traceback.print_exc()
            
            messagebox.showerror("Kritischer Fehler", f"Fehler beim Übernehmen:\n{str(e)}")

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