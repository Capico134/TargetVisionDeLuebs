
import os

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
from DateiManagerDeLuebs import DateiManager
from StateManagerDeLuebs import StateManager

import LoggerDeLuebs
from HandbuchDeLuebs import PARAMETER_LEXIKON

# ==========================================
# TOOLTIP-KLASSE FÜR DIE GUI
# ==========================================
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.show_id = None
        self.hide_id = None
        
        self.widget.bind("<Enter>", self.enter_widget)
        self.widget.bind("<Leave>", self.leave_widget)
        
    def enter_widget(self, event=None):
        self.cancel_hide()
        if not self.tip_window:
            self.show_id = self.widget.after(500, self.show)
            
    def leave_widget(self, event=None):
        if self.show_id:
            self.widget.after_cancel(self.show_id)
            self.show_id = None
        self.schedule_hide()
        
    def enter_tooltip(self, event=None):
        self.cancel_hide()
        
    def leave_tooltip(self, event=None):
        self.schedule_hide()
        
    def schedule_hide(self):
        self.cancel_hide()
        # 200ms Gnadenfrist, um mit der Maus vom Label auf den Tooltip zu wechseln
        self.hide_id = self.widget.after(200, self.hide)
        
    def cancel_hide(self):
        if self.hide_id:
            self.widget.after_cancel(self.hide_id)
            self.hide_id = None
            
    def show(self):
        if self.tip_window or not self.text: return
        x, y, cx, cy = self.widget.bbox("insert")
        
        # Etwas weiter weg geschoben, damit große Mauszeiger den Text nicht verdecken
        x += self.widget.winfo_rootx() + 45
        y += self.widget.winfo_rooty() + 30
        
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True) # Entfernt den Windows-Rahmen
        
        # ---> NEU: Mache den Tooltip zum König aller Fenster! <---
        tw.attributes('-topmost', True) 
        
        tw.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("Arial", 10), wraplength=350, padx=5, pady=5)
        label.pack()
        
        # ---> NEU: Der Tooltip registriert jetzt auch selbst, ob die Maus auf ihm ruht! <---
        tw.bind("<Enter>", self.enter_tooltip)
        tw.bind("<Leave>", self.leave_tooltip)
        label.bind("<Enter>", self.enter_tooltip)
        label.bind("<Leave>", self.leave_tooltip)
        
    def hide(self):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None
            
# ==========================================
# DUMMY-KLASSEN FÜR DIE TARGET-DETECTION
# ==========================================
class DummyConfig:
    def __init__(self, app):
        self.app = app
        
    def _get_val(self, section, key, fallback):
        if getattr(self.app, 'package_data', None) and self.app.package_data.get('config'):
            parser = self.app.package_data['config']
            if parser.has_option(section, key):
                return parser.get(section, key)
        return fallback

    def getint(self, section, key, fallback=0):
        try: return int(self._get_val(section, key, fallback))
        except ValueError: return fallback
        
    def getfloat(self, section, key, fallback=0.0):
        try: return float(self._get_val(section, key, fallback))
        except ValueError: return fallback
        
    def getboolean(self, section, key, fallback=False):
        val = self._get_val(section, key, str(fallback)).strip().lower()
        if val in ('yes', 'true', '1', 'on'): return True
        if val in ('no', 'false', '0', 'off'): return False
        return fallback
        
    def get(self, section, key, fallback=''):
        return self._get_val(section, key, fallback)

class DummyDateiManager:
    def __init__(self, app):
        self.app = app
        self.debug_images = {}
        self.export_folder = "labor_export"
        
    def save_debug_image(self, name, image):
        self.debug_images[name] = image.copy()
        if self.app.export_images_var.get():
            import os
            if not os.path.exists(self.export_folder):
                os.makedirs(self.export_folder)
            ext = ".png" if "diff" in name.lower() or "mask" in name.lower() else ".jpg"
            path = os.path.join(self.export_folder, f"{name}{ext}")
            cv2.imwrite(path, image)
            
    def load_targets(self):
        # ---> NEU: Holt die echten Zielscheiben-Daten für den StateManager! <---
        return self.app.dm.load_targets()
        
    def write_log(self, msg):
        # ---> NEU: Stummschaltung für den StateManager <---
        pass


# ==========================================
# GUI UND LOGIK
# ==========================================
class OfflineLaborApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Labor & Einstellungen")
        self.root.geometry("1400x850")
        
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
        self.hybrid_riss_faktor_var = tk.DoubleVar(value=1.175)
        self.hybrid_sichel_faktor_var = tk.DoubleVar(value=1.05)
        self.hybrid_discard_faktor_var = tk.DoubleVar(value=2.5)
        self.hough_min_faktor_var = tk.DoubleVar(value=0.85)
        self.hough_max_faktor_var = tk.DoubleVar(value=1.15)
        
        self.hough_param1_var = tk.IntVar(value=25)
        self.hough_param2_var = tk.IntVar(value=4)
        # ---> NEU <---
        self.morph_kernel_var = tk.IntVar(value=6)
        self.max_aspect_ratio_var = tk.DoubleVar(value=3.5)
        # ---> NEU <---
        self.gesamt_anteil_am_200score_var = tk.DoubleVar(value=0.667)
        
        self.zoom_factor = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.view_mode_var = tk.IntVar(value=1)
        
        self.setup_ui()
        
    def make_slider(self, parent, label_text, tk_var, from_, to_, res=1, section="Erkennung", key=None):
        """Hilfsfunktion für Slider mit direkter Eingabe, Reset und Live-Data-Binding"""
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)
        
        lbl = tk.Label(frame, text=label_text, width=25, anchor="w")
        lbl.pack(side=tk.LEFT)
        # ---> NEU: Tooltip aus dem Handbuch anhängen, falls vorhanden <---
        if key and key in PARAMETER_LEXIKON:
            ToolTip(lbl, PARAMETER_LEXIKON[key])
        
        # ---> DER FIX: Wir trennen das Textfeld von der strengen Slider-Variable! <---
        entry = tk.Entry(frame, width=6, justify="right")
        entry.pack(side=tk.RIGHT, padx=(5, 0))
        entry.insert(0, str(tk_var.get()))
        
        scale = tk.Scale(frame, from_=from_, to_=to_, resolution=res, orient=tk.HORIZONTAL, 
                         variable=tk_var, command=self.on_param_change)
        scale.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        
        # ---> NEU: Wert erst bei Enter oder Klick woanders übernehmen <---
        def apply_entry_val(event=None):
            try:
                # Prüfen, ob es eine Kommazahl oder Ganzzahl sein soll
                if isinstance(tk_var, tk.IntVar):
                    val = int(float(entry.get()))
                else:
                    val = float(entry.get())
                    
                # Nur neu berechnen, wenn sich die Zahl WIRKLICH geändert hat!
                if val != tk_var.get():
                    tk_var.set(val)
                    self.on_param_change(force=True)
                    
            except ValueError:
                pass # Wenn jemand "abc" tippt, ignorieren wir es
                
            # Nach der Übernahme formatieren wir das Feld wieder sauber 
            entry.delete(0, tk.END)
            entry.insert(0, str(tk_var.get()))
            
            # ---> DER FIX: Fokus nur bei 'Enter' klauen, nicht bei Mausklicks! <---
            #if event and getattr(event, 'keysym', '') == 'Return':
            #    self.root.focus()

        # Löst aus, wenn Enter gedrückt wird oder das Textfeld den Fokus verliert
        entry.bind('<Return>', apply_entry_val)
        entry.bind('<FocusOut>', apply_entry_val)
        
        # ---> NEU: Wenn der SLIDER bewegt wird, updaten wir das Textfeld (außer der Nutzer tippt gerade!) <---
        def sync_entry(*args):
            if self.root.focus_get() != entry:
                entry.delete(0, tk.END)
                entry.insert(0, str(tk_var.get()))
                
        tk_var.trace_add("write", sync_entry)

        # ---> NEU: Der Trace-Spion (Live-Data-Binding für die Config) <---
        if key:
            def sync_to_config(*args):
                if getattr(self, 'package_data', None) and self.package_data.get('config'):
                    parser = self.package_data['config']
                    if not parser.has_section(section):
                        parser.add_section(section)
                    parser.set(section, key, str(tk_var.get()))
            
            tk_var.trace_add("write", sync_to_config)

        # ---> Mittelklick-Reset <---
        def reset_to_original(event):
            var_key = str(tk_var)
            if hasattr(self, 'original_values') and var_key in self.original_values:
                tk_var.set(self.original_values[var_key])
                self.on_param_change(force=True)
            return "break" 
                
        scale.bind('<Button-2>', reset_to_original)
        lbl.bind('<Button-2>', reset_to_original)
        entry.bind('<Button-2>', reset_to_original)

    def setup_ui(self):
        # TOP FRAME
        top_frame = tk.Frame(self.root, pady=10, padx=10)
        top_frame.pack(fill=tk.X)
        
        tk.Button(top_frame, text="📦 ZIP-Paket laden", command=self.load_zip, font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        
        # ---> lbl_file wurde hier komplett gelöscht! <---
        
        self.btn_compare = tk.Button(top_frame, text="📊 Abweichung messen", command=self.show_comparison, font=("Arial", 10, "bold"))
        self.btn_compare.pack(side=tk.LEFT, padx=20)        
        
        btn_export = tk.Button(top_frame, text="💾 Test-Case exportieren", command=self.export_test_case)
        btn_export.pack(side=tk.LEFT, pady=5, padx=(0, 20))
        
        btn_einstellungen = tk.Button(top_frame, text="⚙️ Erweiterte Einstellungen", command=self.open_all_settings_dialog, bg="#34495e", fg="white")
        btn_einstellungen.pack(side=tk.LEFT, pady=5, padx=(0, 20))
        
        # ---> NEU: Der lange, eindeutige Button-Text <---
        self.btn_apply = tk.Button(top_frame, text="✅ Einstellungen speichern und Labor schließen", 
                                   command=self.apply_to_live, bg="#27ae60", fg="white", font=("Arial", 10, "bold"))
        self.btn_apply.pack(side=tk.LEFT, pady=5)
        
        self.lbl_coords = tk.Label(top_frame, text="Maus nicht im Bild", font=("Consolas", 12, "bold"), fg="#3498db")
        self.lbl_coords.pack(side=tk.RIGHT, padx=15)
        
        # MAIN FRAME
        main_frame = tk.Frame(self.root, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # LINKS: Bild-Ansicht (Text für den Nutzer als Hilfestellung angepasst)
        self.image_frame = tk.LabelFrame(main_frame, text=" Live-Labor (Mausrad = Zoom | Linksklick = Bewegen | Rechtsklick = Reset) ", bg="#222222", fg="white")
        self.image_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        self.lbl_image = tk.Label(self.image_frame, text="Warte auf ZIP-Datei...", bg="#222222", fg="gray", font=("Arial", 14))
        self.lbl_image.place(x=0, y=0, anchor=tk.NW)
        
        # ---> NEU: Maus-Events binden <---
        self.lbl_image.bind('<Motion>', self.on_mouse_move)
        self.lbl_image.bind('<Leave>', self.on_mouse_leave)
        
        # ---> NEU: Zoom-Events (Mausrad) <---
        self.lbl_image.bind('<MouseWheel>', self.on_mouse_scroll) # Windows / Mac
        self.lbl_image.bind('<Button-4>', self.on_mouse_scroll)   # Linux (Hoch)
        self.lbl_image.bind('<Button-5>', self.on_mouse_scroll)   # Linux (Runter)
        
        # ---> NEU: Drag & Drop (Verschieben) + Reset <---
        self.lbl_image.bind('<ButtonPress-1>', self.on_drag_start)
        self.lbl_image.bind('<B1-Motion>', self.on_drag_motion)
        self.lbl_image.bind('<Button-3>', self.reset_view) # Rechtsklick = Reset
        self.log_text = tk.Text(self.image_frame, height=18, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        self.log_text.pack(side=tk.BOTTOM, fill=tk.X)
        # -------------------------------------------
        
        # RECHTS: Steuerpult (Nur noch EINMAL definiert!)
        control_frame = tk.Frame(main_frame, width=400)
        control_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        # ==========================================================
        # ---> DER KAMERA-UMSCHALTER <---
        # ==========================================================
        cam_frame = tk.LabelFrame(control_frame, text=" Aktive Kamera ", pady=5, padx=5)
        cam_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.active_camera_var = tk.StringVar(value="left")
        
        self.rb_cam_left = tk.Radiobutton(cam_frame, text="Kamera Links", variable=self.active_camera_var, value="left", command=self.switch_camera)
        self.rb_cam_left.pack(side=tk.LEFT, expand=True)
        
        self.rb_cam_right = tk.Radiobutton(cam_frame, text="Kamera Rechts", variable=self.active_camera_var, value="right", command=self.switch_camera)
        self.rb_cam_right.pack(side=tk.LEFT, expand=True)
        # ==========================================================
        
        # Bild-Navigation (Nur noch EINMAL definiert!)
        nav_frame = tk.LabelFrame(control_frame, text=" Bild-Navigation ", pady=10, padx=10)
        nav_frame.pack(fill=tk.X, pady=(0, 15))
        
        # ---> 5 Buttons mit fester Breite und ohne Expand <---
        self.btn_first = tk.Button(nav_frame, text="<<", state=tk.DISABLED, command=self.first_shot, width=3)
        self.btn_first.pack(side=tk.LEFT, padx=(0, 2))
        self.btn_prev = tk.Button(nav_frame, text="◀ Zurück", state=tk.DISABLED, command=self.prev_shot, width=8)
        self.btn_prev.pack(side=tk.LEFT)
        # ---> NEU: Interaktiver Bereich in der Mitte <---
        self.shot_nav_frame = tk.Frame(nav_frame)
        self.shot_nav_frame.pack(side=tk.LEFT, expand=True)
        tk.Label(self.shot_nav_frame, text="Bild ", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.shot_jump_var = tk.StringVar(value="-")
        self.entry_shot_jump = tk.Entry(self.shot_nav_frame, textvariable=self.shot_jump_var, width=4, font=("Arial", 10, "bold"), justify="center")
        self.entry_shot_jump.pack(side=tk.LEFT)
        # Binde die Enter-Taste an unsere neue Funktion
        self.entry_shot_jump.bind('<Return>', self.jump_to_shot)
        self.lbl_shot_total = tk.Label(self.shot_nav_frame, text=" / -", font=("Arial", 10, "bold"))
        self.lbl_shot_total.pack(side=tk.LEFT)
        
        
        self.btn_last = tk.Button(nav_frame, text=">>", state=tk.DISABLED, command=self.last_shot, width=3)
        self.btn_last.pack(side=tk.RIGHT, padx=(2, 0))
        self.btn_next = tk.Button(nav_frame, text="Weiter ▶", state=tk.DISABLED, command=self.next_shot, width=8)
        self.btn_next.pack(side=tk.RIGHT)
        
        ## ---> NEU: Der Vergleichs-Button <---
        #self.btn_compare = tk.Button(nav_frame, text="📊 Abweichung zum Original messen", command=self.show_comparison, bg="#2c3e50", fg="white")
        #self.btn_compare.pack(side=tk.BOTTOM, fill=tk.X, pady=(10,0))
        
        # ---> NEU: Ansichts-Steuerung UND Ringwertung im Doppel-Layout <---
        view_outer_frame = tk.Frame(control_frame)
        view_outer_frame.pack(fill=tk.X, pady=(0, 15))
        
        view_frame = tk.LabelFrame(view_outer_frame, text=" Rechte Bildhälfte ", pady=10, padx=10)
        view_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        tk.Radiobutton(view_frame, text="1) Diff-Bild", variable=self.view_mode_var, value=1, command=self.update_image_display).pack(anchor=tk.W)
        tk.Radiobutton(view_frame, text="2) Diff-Gesamt", variable=self.view_mode_var, value=2, command=self.update_image_display).pack(anchor=tk.W)
        tk.Radiobutton(view_frame, text="3) Überlagerung", variable=self.view_mode_var, value=3, command=self.update_image_display).pack(anchor=tk.W)
        tk.Radiobutton(view_frame, text="4) Raw-Diff", variable=self.view_mode_var, value=4, command=self.update_image_display).pack(anchor=tk.W)
        tk.Radiobutton(view_frame, text="5) Rohes Bild", variable=self.view_mode_var, value=5, command=self.update_image_display).pack(anchor=tk.W)

        self.score_frame = tk.LabelFrame(view_outer_frame, text=" Ringwertung (Live) ", pady=10, padx=10)
        self.score_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        self.lbl_current_scores = tk.Label(self.score_frame, text="-", justify=tk.LEFT, anchor="nw", font=("Consolas", 12, "bold"), fg="#27ae60")
        self.lbl_current_scores.pack(fill=tk.BOTH, expand=True)
        
        # ---> NEU: Scrollbarer Bereich für die Parameter <---
        param_outer_frame = tk.LabelFrame(control_frame, text=" Erkennungs-Parameter (Live) ", pady=5, padx=5)
        param_outer_frame.pack(fill=tk.BOTH, expand=True)

        # Canvas und Scrollbar erstellen
        canvas = tk.Canvas(param_outer_frame, borderwidth=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(param_outer_frame, orient="vertical", command=canvas.yview)
        
        # Das eigentliche Frame für die Slider, das im Canvas liegt
        param_frame = tk.Frame(canvas)
        
        # Scrollregion dynamisch anpassen, wenn Slider hinzugefügt werden
        param_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        # Fenster im Canvas erstellen und so konfigurieren, dass es die volle Breite nutzt
        canvas_window = canvas.create_window((0, 0), window=param_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # --- Hier kommen die Slider in das neue scrollbare param_frame ---
        self.make_slider(param_frame, "hit_tolerance:", self.hit_tolerance_var, 1, 100, key="hit_tolerance")
        self.make_slider(param_frame, "min_hole_area:", self.min_hole_area_var, 5, 500, key="min_hole_area")
        #self.make_slider(param_frame, "caliber_radius:", self.caliber_radius_var, 5.0, 50.0, res=0.1, key="caliber_radius")
        self.make_slider(param_frame, "caliber_durchmesser (mm):", self.caliber_durchmesser_var, 3.00, 10.00, res=0.01, key="caliber_durchmesser")
        tk.Label(param_frame, text="--- Hybrid & Hough Faktoren ---", fg="gray").pack(pady=(10, 5))
        self.make_slider(param_frame, "hybrid_sichel_faktor:", self.hybrid_sichel_faktor_var, 0.1, 1.5, 0.01, key="hybrid_sichel_faktor")
        self.make_slider(param_frame, "hybrid_riss_faktor:", self.hybrid_riss_faktor_var, 1.0, 3.0, 0.001, key="hybrid_riss_faktor")
        self.make_slider(param_frame, "hybrid_discard_faktor:", self.hybrid_discard_faktor_var, 1.5, 5.0, 0.1, key="hybrid_discard_faktor")
        self.make_slider(param_frame, "hough_min_faktor:", self.hough_min_faktor_var, 0.5, 1.0, 0.01, key="hough_min_faktor")
        self.make_slider(param_frame, "hough_max_faktor:", self.hough_max_faktor_var, 1.0, 2.0, 0.01, key="hough_max_faktor")
        self.make_slider(param_frame, "hough_param1 (Kanten):", self.hough_param1_var, 10, 100, key="hough_param1")
        self.make_slider(param_frame, "hough_param2 (Strenge):", self.hough_param2_var, 1, 20, key="hough_param2")
        tk.Label(param_frame, text="--- Bild-Filterung ---", fg="gray").pack(pady=(10, 5))
        self.make_slider(param_frame, "morph_kernel_size:", self.morph_kernel_var, 0, 15, key="morph_kernel_size")
        self.make_slider(param_frame, "max_aspect_ratio (Sichel):", self.max_aspect_ratio_var, 1.5, 6.0, 0.1, key="max_aspect_ratio")
        tk.Label(param_frame, text="--- Score-Gewichtung ---", fg="gray").pack(pady=(10, 5))
        self.make_slider(param_frame, "gesamt_anteil (Raw):", self.gesamt_anteil_am_200score_var, 0.1, 0.9, 0.001, key="gesamt_anteil_am_200score")
        
        tk.Checkbutton(param_frame, text="💾 Simulations-Bilder exportieren", 
                       variable=self.export_images_var, fg="#00aaff").pack(anchor=tk.W, pady=(15, 0))

        # ---> NEU: Scroll-Fix für das Mausrad im gesamten Parameter-Block <---
        def _on_mousewheel(event):
            # Check für Scrollrichtung (Windows/Mac: delta, Linux: num 4/5)
            if event.num == 4 or getattr(event, 'delta', 0) > 0:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5 or getattr(event, 'delta', 0) < 0:
                canvas.yview_scroll(1, "units")

        def _bind_scroll_recursive(widget):
            # Bindet das Event an das aktuelle Element
            widget.bind("<MouseWheel>", _on_mousewheel)
            widget.bind("<Button-4>", _on_mousewheel)
            widget.bind("<Button-5>", _on_mousewheel)
            # Geht rekursiv durch alle Unter-Elemente (Labels, Slider, Frames)
            for child in widget.winfo_children():
                _bind_scroll_recursive(child)

        # Die Funktion auf das Canvas und das Frame loslassen
        _bind_scroll_recursive(canvas)
        _bind_scroll_recursive(param_frame)
        
        # ---> NEU: Pfeiltasten global an das Fenster binden <---
        self.root.bind('<Left>', self.safe_prev_shot)
        self.root.bind('<Right>', self.safe_next_shot)
    
        # ---> NEU: Original-Treffer Checkbox <---
        self.show_orig_hits_var = tk.BooleanVar(value=False)
        tk.Checkbutton(param_frame, text="🟡 Original-Treffer (match.json) einblenden", 
                       variable=self.show_orig_hits_var, fg="#f1c40f", 
                       command=lambda: self.on_param_change(force=True)).pack(anchor=tk.W, pady=(5, 0))

    def switch_camera(self):
        """Wird aufgerufen, wenn man zwischen Links/Rechts umschaltet."""
        self.current_index = 0 # Zurück auf Start!
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
        if parser and parser.has_section('Erkennung'):
            self.hit_tolerance_var.set(parser.getint('Erkennung', 'hit_tolerance', fallback=22))
            self.min_hole_area_var.set(parser.getint('Erkennung', 'min_hole_area', fallback=25))
            #self.caliber_radius_var.set(parser.getfloat('Erkennung', 'caliber_radius', fallback=11))
            self.hybrid_riss_faktor_var.set(parser.getfloat('Erkennung', 'hybrid_riss_faktor', fallback=1.175))
            self.hybrid_sichel_faktor_var.set(parser.getfloat('Erkennung', 'hybrid_sichel_faktor', fallback=1.05))
            self.hybrid_discard_faktor_var.set(parser.getfloat('Erkennung', 'hybrid_discard_faktor', fallback=2.5))
            self.hough_min_faktor_var.set(parser.getfloat('Erkennung', 'hough_min_faktor', fallback=0.85))
            self.hough_max_faktor_var.set(parser.getfloat('Erkennung', 'hough_max_faktor', fallback=1.15))
            self.hough_param1_var.set(parser.getint('Erkennung', 'hough_param1', fallback=25))
            self.hough_param2_var.set(parser.getint('Erkennung', 'hough_param2', fallback=4))
            self.morph_kernel_var.set(parser.getint('Erkennung', 'morph_kernel_size', fallback=6))
            self.max_aspect_ratio_var.set(parser.getfloat('Erkennung', 'max_aspect_ratio', fallback=3.5))
            self.gesamt_anteil_am_200score_var.set(parser.getfloat('Erkennung', 'gesamt_anteil_am_200score', fallback=0.667))
            # ---> NEU: Den alten Radius ignorieren, wenn ein Durchmesser da ist <---
            if parser.has_option('Erkennung', 'caliber_durchmesser'):
                val = parser.get('Erkennung', 'caliber_durchmesser')
                if val.strip().lower() == 'auto':
                    self.caliber_durchmesser_var.set(4.50) # Fallback für die GUI
                else:
                    self.caliber_durchmesser_var.set(float(val))
            else:
                # Falls wir eine uralte Config laden, konvertieren wir den Pixel-Wert grob in mm für den Slider
                alt_r = parser.getfloat('Erkennung', 'caliber_radius', fallback=15.0)
                self.caliber_durchmesser_var.set(round((alt_r * 2) / 8.5, 2))
            
            # Reset-Punkte für den Mittelklick auf den Slidern speichern
            self.original_values = {
                str(self.hit_tolerance_var): self.hit_tolerance_var.get(),
                str(self.min_hole_area_var): self.min_hole_area_var.get(),
                #str(self.caliber_radius_var): self.caliber_radius_var.get(),
                str(self.caliber_durchmesser_var): self.caliber_durchmesser_var.get(),
                str(self.hybrid_riss_faktor_var): self.hybrid_riss_faktor_var.get(),
                str(self.hybrid_sichel_faktor_var): self.hybrid_sichel_faktor_var.get(),
                str(self.hybrid_discard_faktor_var): self.hybrid_discard_faktor_var.get(),
                str(self.hough_min_faktor_var): self.hough_min_faktor_var.get(),
                str(self.hough_max_faktor_var): self.hough_max_faktor_var.get(),
                str(self.hough_param1_var): self.hough_param1_var.get(),
                str(self.hough_param2_var): self.hough_param2_var.get(),
                str(self.morph_kernel_var): self.morph_kernel_var.get(),
                str(self.max_aspect_ratio_var): self.max_aspect_ratio_var.get(),
                str(self.gesamt_anteil_am_200score_var): self.gesamt_anteil_am_200score_var.get()
            }

    def get_img(self, name):
        """Holt ein Bild blitzschnell aus dem vorbereiteten RAM-Speicher"""
        return self.package_data['images'].get(name)

    def load_local_config(self):
        """Lädt die lokale config.ini im Stand-Alone Modus."""
        parser = self.dm.load_or_create_config()
        
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
            self.current_zip_path = filepath
            self.root.title(f"Labor & Einstellungen - {os.path.basename(filepath)}")
            
            self.package_data = self.dm.import_match_package(filepath)
            if not self.package_data:
                messagebox.showerror("Fehler", "Konnte ZIP-Paket nicht laden!")
                return
                
            parser = self.package_data.get('config')
            self.apply_config_to_ui(parser)
            self.original_match_data = self.package_data.get('match_data')
            
            self.all_files = list(self.package_data['images'].keys())
            self.orig_files = sorted([f for f in self.all_files if "_orig" in f])
            
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
            self.process_and_display()

    def prev_shot(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.process_and_display()

    def next_shot(self):
        if self.current_index < len(self.get_current_side_origs()):
            self.current_index += 1
            self.process_and_display()

    def safe_prev_shot(self, event=None):
        if self.root.focus_get() != self.entry_shot_jump: self.prev_shot()

    def safe_next_shot(self, event=None):
        if self.root.focus_get() != self.entry_shot_jump: self.next_shot()

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

 
    def on_param_change(self, event=None, force=False):
        if not self.current_zip_path:
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
            
        x, y = event.x, event.y
        img_h, img_w = self.base_combined_img.shape[:2]
        
        # Sicherheits-Check: Befindet sich die Maus überhaupt innerhalb des Bildes?
        if x < 0 or y < 0 or x >= img_w or y >= img_h:
            self.on_mouse_leave(event)
            return
            
        # Wir nehmen das Base-Image und zeichnen nur auf dieser Kopie herum
        temp_img = self.base_combined_img.copy()
        
        # Den aktuellen Radius an den Zoom-Faktor anpassen
        base_r = getattr(self, 'current_radius_px', 15) # Holt den perfekten Radius aus Schritt 1
        r = int(base_r * self.current_scale)
        
        # Neon-Blau / Cyan in BGR-Farbraum
        neon_blue = (255, 255, 0)
        
        # Prüfen, ob wir im linken oder rechten Bild sind
        if x < self.current_img_w:
            real_x = int(x / self.current_scale)
            real_y = int(y / self.current_scale)
            
            # ---> NEU: Diff-Wert auslesen <---
            diff_val = self.last_raw_diff[real_y, real_x] if hasattr(self, 'last_raw_diff') else 0
            self.lbl_coords.config(text=f"Live-Bild -> X:{real_x:04d} | Y:{real_y:04d} | DIFF:{diff_val:03d}")
            
            # ---> NEU: Fadenkreuz im RECHTEN Bild einzeichnen <---
            mirror_x = x + self.current_img_w
            cv2.circle(temp_img, (mirror_x, y), r, neon_blue, 2)
            cv2.circle(temp_img, (mirror_x, y), 2, neon_blue, -1) 
            
        else:
            real_x = int((x - self.current_img_w) / self.current_scale)
            real_y = int(y / self.current_scale)
            
            # ---> NEU: Diff-Wert auslesen <---
            diff_val = self.last_raw_diff[real_y, real_x] if hasattr(self, 'last_raw_diff') else 0
            self.lbl_coords.config(text=f"Rechtes Bild -> X:{real_x:04d} | Y:{real_y:04d} | DIFF:{diff_val:03d}")
            
            # ---> NEU: Fadenkreuz im LINKEN Bild einzeichnen <---
            mirror_x = x - self.current_img_w
            cv2.circle(temp_img, (mirror_x, y), r, neon_blue, 2)
            cv2.circle(temp_img, (mirror_x, y), 2, neon_blue, -1) 

        # Das temporäre Bild mit dem Overlay blitzschnell ins Tkinter-Label werfen
        img_pil = Image.fromarray(cv2.cvtColor(temp_img, cv2.COLOR_BGR2RGB))
        self.tk_image = ImageTk.PhotoImage(img_pil)
        self.lbl_image.config(image=self.tk_image)

    def on_mouse_leave(self, event):
        self.lbl_coords.config(text="Maus nicht im Bild")
        
        # ---> NEU: Wieder das cleane Base-Image anzeigen, wenn die Maus weg ist <---
        if getattr(self, 'base_combined_img', None) is not None:
            img_pil = Image.fromarray(cv2.cvtColor(self.base_combined_img, cv2.COLOR_BGR2RGB))
            self.tk_image = ImageTk.PhotoImage(img_pil)
            self.lbl_image.config(image=self.tk_image)

    def on_drag_start(self, event):
        """Merkt sich die Startkoordinaten beim Klicken"""
        # Wir nutzen x_root/y_root, weil das die absoluten Bildschirmkoordinaten sind.
        # So zittert das Bild nicht, wenn sich das Label unter der Maus wegbewegt.
        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root
        self.start_pan_x = self.pan_x
        self.start_pan_y = self.pan_y

    def on_drag_motion(self, event):
        """Verschiebt das Bild während des Ziehens"""
        if getattr(self, 'tk_image', None) is None: return
        
        dx = event.x_root - self.drag_start_x
        dy = event.y_root - self.drag_start_y
        
        self.pan_x = self.start_pan_x + dx
        self.pan_y = self.start_pan_y + dy
        
        # Das ist der ganze Trick: Wir verschieben einfach das Tkinter-Label!
        self.lbl_image.place(x=self.pan_x, y=self.pan_y)
        
    def reset_view(self, event=None):
        """Setzt Zoom und Position zurück (z.B. bei Rechtsklick)"""
        self.zoom_factor = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.lbl_image.place(x=0, y=0)
        self.update_image_display()
        
    def on_mouse_scroll(self, event):
        old_zoom = self.zoom_factor
        
        # Prüfen, ob nach oben (num 4 / delta > 0) oder unten gescrollt wurde
        if event.num == 4 or getattr(event, 'delta', 0) > 0:
            self.zoom_factor *= 1.15  # 15% Reinzoomen
        elif event.num == 5 or getattr(event, 'delta', 0) < 0:
            self.zoom_factor *= 0.85  # 15% Rauszoomen
            
        # Grenzen setzen (Minimal 20% der Originalgröße, Maximal 10-facher Zoom)
        self.zoom_factor = max(0.2, min(self.zoom_factor, 10.0))
        
        # ---> NEU: Das Bild zur Maus hin zoomen (wie bei Google Maps) <---
        if self.zoom_factor != old_zoom:
            scale_change = self.zoom_factor / old_zoom
            
            # Berechnet, wie weit der Pixel unter der Maus "wegrutschen" würde und zieht das Label nach
            self.pan_x -= (event.x * scale_change - event.x)
            self.pan_y -= (event.y * scale_change - event.y)
            self.lbl_image.place(x=self.pan_x, y=self.pan_y)
        
        # Bild blitzschnell neu zeichnen
        self.update_image_display()
        
        # Koordinaten-Anzeige manuell triggern, damit sie nach dem Zoom sofort stimmt
        self.on_mouse_move(event)   

    def process_and_display(self):
        self.root.focus()
        if not self.current_zip_path: return
        
        side = self.active_camera_var.get()
        side_origs = self.get_current_side_origs()
        
        # UI updaten
        self.shot_jump_var.set(str(self.current_index))
        self.lbl_shot_total.config(text=f" / {len(side_origs)}")
        self.log_text.delete(1.0, tk.END)
        
        # ==========================================================
        # ---> SONDERFALL: INDEX 0 = DAS REFERENZBILD <---
        # ==========================================================
        if self.current_index == 0:
            self.image_frame.config(text=f" Live-Labor (Referenz & Startmaske)  |  📷 Kamera {side.upper()} ")
            self.print_log("SYSTEM", f"Zeige initialen Zustand für Kamera {side.upper()}.")
            
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
            
            self.update_image_display()
            return
            
        # ==========================================================
        # ---> NORMALE SCHÜSSE (Index > 0) <---
        # ==========================================================
        target_idx = self.current_index - 1
        orig_name = side_origs[target_idx]
        
        self.image_frame.config(text=f" Live-Labor (Mausrad = Zoom | Klick = Bewegen | Rechtsklick = Reset)  |  📄 {orig_name} ")
        
        # 1. DUMMYS AUFBAUEN
        d_config = DummyConfig(self)
        d_dm = DummyDateiManager(self)
        d_sm = StateManager(d_config, d_dm)
        
        # 2. ECHTE ENGINE STARTEN
        detector = TargetDetector(d_config, d_dm, d_sm, self.print_log)
        
        ref_name = next((f for f in self.all_files if f"referenz_{side}" in f), None)
        if not ref_name: return
        ref_img = self.get_img(ref_name)
        detector.set_reference_image(ref_img, side)
        
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
                
                d_dm.debug_images.pop(f"diff_letzter_treffer_{side}", None)
                d_dm.debug_images.pop(f"diff_letzte_verworfene_auswertung_{side}", None)
                
                live_img = img.copy()
                clean_live_img = img.copy()
                
                temp_state = d_sm.state_left if side == 'left' else d_sm.state_right
                if temp_state.cumulative_mask is not None:
                    history_mask = temp_state.cumulative_mask.copy()
                else:
                    history_mask = np.zeros(img.shape[:2], dtype=np.uint8)
                
            detector.detect_new_shot(img, side)

        # 4. VISUALISIERUNG DER ENGINE-ERGEBNISSE
        # ... (Ab hier geht der bisherige Code von "Hole das Diff-Bild direkt aus dem Dummy..." exakt wie gewohnt weiter!)

        # 4. VISUALISIERUNG DER ENGINE-ERGEBNISSE
        # Hole das Diff-Bild direkt aus dem Dummy-DateiManager der Engine!
        # ---> NEU: Ringwertung aus dem StateManager in die GUI schreiben (MIT SCHUSS-NUMMER) <---
        side_shots = [s for s in d_sm.shots if s['side'] == side]
        lines = []
        for i, s in enumerate(side_shots):
            if s.get('is_new', False):
                # i ist der Index (0, 1, 2...), also ist i+1 die echte Schuss-Nummer!
                lines.append(f"🎯 Schuss #{i+1}: {s['score']:.1f} Ringe")
                
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
            
        # Kreise auf das Live-Bild zeichnen (aus dem StateManager der Engine!)
        # ---> NEU: Dynamischen Radius verwenden!
        r = int(detector.get_caliber_radius(side))
        self.current_radius_px = r  # <--- NEU: Für das Maus-Fadenkreuz speichern!
        for shot in d_sm.shots:
            if shot['side'] == side:
                # Grün für alte, Rot für diesen Frame
                color = (0, 0, 255) if shot.get('is_new', False) else (0, 255, 0)
                cv2.circle(live_img, shot['pos'], r, color, 2)
                
                
        # ====================================================================
        # ---> NEU: Original-Treffer (Gelbe Linien) einblenden (SYNCHRONISIERT) <---
        # ====================================================================
        if getattr(self, 'show_orig_hits_var', None) and self.show_orig_hits_var.get() and getattr(self, 'original_match_data', None):
            side_char = 'l' if side == 'left' else 'r'
            
            orig_shots_side = [s for s in self.original_match_data.get("timeline", []) if s.get('s') == side_char]
            curr_shots_side = [s for s in d_sm.shots if s.get('side') == side]
            #cal_r = self.caliber_radius_var.get()
            # Wir holen uns den perfekten, linsenkorrigierten Pixel-Radius direkt aus der Engine!
            cal_r = detector.get_caliber_radius(side)
            
            # Wir nutzen das smarte Alignment, um die gelben Kreise an die neuen Treffer zu koppeln!
            aligned = self.align_shots(orig_shots_side, curr_shots_side, cal_r * 2.5)
            
            # Finde den Punkt in der Timeline, an dem der aktuell letzte neue Schuss (curr_idx) steht
            last_valid_align_idx = -1
            for idx, (o_idx, c_idx, dist) in enumerate(aligned):
                if c_idx is not None:
                    last_valid_align_idx = idx
                    
            # Wir zeichnen alle Original-Schüsse, die chronologisch bis zu diesem Punkt passiert sind
            shots_to_draw = []
            if last_valid_align_idx >= 0:
                for idx in range(last_valid_align_idx + 1):
                    o_idx = aligned[idx][0]
                    if o_idx is not None:
                        shots_to_draw.append(orig_shots_side[o_idx])
            else:
                # Fallback: Falls noch gar kein neuer Schuss da ist, nutzen wir den Bild-Index
                shots_to_draw = orig_shots_side[:target_idx + 1]
            
            for s in shots_to_draw:
                ox, oy = s['x'], s['y']
                # Gelb in BGR = (0, 255, 255), Dicke = 1
                cv2.circle(live_img, (ox, oy), int(cal_r), (0, 255, 255), 1)
        # ====================================================================

        # ---> NEU: Daten für den späteren Vergleich merken <---
        self.current_engine_shots = d_sm.shots 
        self.current_side = side

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

        
        
        # ==========================================================
        # ---> NEU: Den echten RAW-Diff-Wert berechnen (Modus 4) <---
        # ==========================================================
        if len(ref_img.shape) == 3 and 'clean_live_img' in locals():
            # 1. Wir nutzen zwingend das saubere Bild OHNE gezeichnete Kreise!
            live_blur = cv2.GaussianBlur(clean_live_img, (7, 7), 0)
            
            # ---> DER FEHLER WAR HIER: ref_img war noch UNBLURRED! <---
            # Die Engine nutzt intern self.ref_left, und das ist geblurrt gespeichert.
            ref_blur = cv2.GaussianBlur(ref_img, (7, 7), 0)
            
            norm_live = detector.normalize_brightness(ref_blur, live_blur)
            diff_bgr = cv2.absdiff(ref_blur, norm_live)
            raw_diff = np.max(diff_bgr, axis=2) # Unser Farb-Hack!
            
            # ---> NEU: Wir führen den Threshold VORHER aus, genau wie die Engine! <---
            hit_tol = self.hit_tolerance_var.get()
            _, thresh_raw = cv2.threshold(raw_diff, hit_tol, 255, cv2.THRESH_BINARY)
            self.last_thresh_raw = thresh_raw.copy()

            self.last_raw_diff = raw_diff.copy() # Für die farbige Anzeige
            
            if 'history_mask' in locals():
                self.last_history_mask = history_mask.copy()
            else:
                self.last_history_mask = np.zeros((h, w), dtype=np.uint8)        

        
        self.update_image_display()

    def align_shots(self, orig_shots, curr_shots, threshold):
        """Sequenz-Alignment mit Lookahead, um Original-JSON und neu berechnete Treffer zu synchronisieren."""
        i = 0
        j = 0
        aligned = []
        while i < len(orig_shots) or j < len(curr_shots):
            if i < len(orig_shots) and j < len(curr_shots):
                ox, oy = orig_shots[i]['x'], orig_shots[i]['y']
                cx, cy = int(curr_shots[j]['pos'][0]), int(curr_shots[j]['pos'][1])
                dist = np.hypot(cx - ox, cy - oy)
                
                if dist < threshold:
                    aligned.append((i, j, dist))
                    i += 1
                    j += 1
                else:
                    found_match = False
                    for lookahead in range(1, min(6, len(curr_shots) - j)):
                        nx, ny = int(curr_shots[j + lookahead]['pos'][0]), int(curr_shots[j + lookahead]['pos'][1])
                        if np.hypot(nx - ox, ny - oy) < threshold:
                            found_match = True
                            for k in range(lookahead):
                                aligned.append((None, j + k, None))
                            j += lookahead
                            break
                    if found_match: continue
                    
                    for lookahead in range(1, min(6, len(orig_shots) - i)):
                        nx, ny = orig_shots[i + lookahead]['x'], orig_shots[i + lookahead]['y']
                        if np.hypot(cx - nx, cy - ny) < threshold:
                            found_match = True
                            for k in range(lookahead):
                                aligned.append((i + k, None, None))
                            i += lookahead
                            break
                    if found_match: continue
                    
                    aligned.append((i, j, dist))
                    i += 1
                    j += 1
            elif i < len(orig_shots):
                aligned.append((i, None, None))
                i += 1
            elif j < len(curr_shots):
                aligned.append((None, j, None))
                j += 1
        return aligned

    def show_comparison(self):
        if not self.current_zip_path or not getattr(self, 'original_match_data', None) or not self.orig_files:
            return

        # 1. Info-Fenster öffnen
        comp_win = tk.Toplevel(self.root)
        comp_win.title(f"📊 Integrations-Check: Live-Parameter vs. Original-Match")
        comp_win.geometry("950x750")

        txt = tk.Text(comp_win, font=("Consolas", 12), bg="#1e1e1e", fg="#00ff00", padx=10, pady=10)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert(tk.END, "Führe komplette Neuberechnung aller Schüsse durch... Bitte warten...\n")
        comp_win.update()

        # 2. Voller Simulations-Durchlauf (Stumm im Hintergrund)
        d_config = DummyConfig(self)
        d_dm = DummyDateiManager(self)
        d_sm = StateManager(d_config, d_dm)
        # Stumme Log-Funktion, damit die Konsole nicht überflutet wird
        detector = TargetDetector(d_config, d_dm, d_sm, lambda side, text, show_gui=False: None) 

        ### START WEG with zipfile.ZipFile(self.current_zip_path, 'r') as zf:
        # Setze Referenzen und Startmasken für BEIDE Seiten
        for s in ['left', 'right']:
            ref_name = next((f for f in self.all_files if f"referenz_{s}" in f), None)
            if ref_name:
                ref_img = self.get_img( ref_name)
                detector.set_reference_image(ref_img, s)
            
            startmask_name = next((f for f in self.all_files if f"cumulative_startmask_{s}" in f), None)
            if startmask_name:
                startmask_bgr = self.get_img( startmask_name)
                startmask_gray = cv2.cvtColor(startmask_bgr, cv2.COLOR_BGR2GRAY)
                state = d_sm.state_left if s == 'left' else d_sm.state_right
                state.cumulative_mask = startmask_gray

        # Alle orig-Bilder durchjagen
        for orig_name in self.orig_files:
            img = self.get_img( orig_name)
            s = 'left' if 'left' in orig_name else 'right'
            detector.detect_new_shot(img, s)

        ### ENDE WEG 

        # 3. Ausgabe aufbereiten
        txt.delete(1.0, tk.END)
        txt.insert(tk.END, f"VERGLEICH: KOMPLETTES MATCH (Aktuelle Slider-Werte vs. Original-JSON)\n")
        txt.insert(tk.END, "="*85 + "\n")

        cal_r = self.caliber_radius_var.get()
        
        # Hilfsfunktion zum Zeichnen der Tabellen
        def build_side_comparison(side_name, side_char):
            cal_r = detector.get_caliber_radius(side_name) # <--- NEU HIER DRIN!
            orig_shots = [s for s in self.original_match_data.get("timeline", []) if s.get('s') == side_char]
            curr_shots = [s for s in d_sm.shots if s.get('side') == side_name]
            
            if not orig_shots and not curr_shots: return 
            
            txt.insert(tk.END, f"\n--- KAMERA {side_name.upper()} ---\n")
            txt.insert(tk.END, f"Original Treffer: {len(orig_shots)} | Neu berechnet: {len(curr_shots)}\n")
            txt.insert(tk.END, "Legende: 'E' markiert manuell editierte Original-Treffer\n") # <--- NEU
            
            # Exakte Breiten: dX(4), dY(4), Distanz(8), Orig-CV(7), Neu-CV(7), % Kaliber(13)
            header = f"{'Nr':>3} | {'Orig (Idx X,Y)':<16} | {'Neu (Idx X,Y)':<16} | {'dX':>4} | {'dY':>4} | {'Distanz':>8} | {'Orig-CV':>7} | {'Neu-CV':>7} | {'% Kaliber':<13}\n"
            txt.insert(tk.END, header)
            txt.insert(tk.END, "-"*99 + "\n")
            
            # ---> NEUER ALGORITHMUS: Sequenz-Alignment mit Lookahead (ausgelagert) <---
            threshold = cal_r * 2.5  
            aligned = self.align_shots(orig_shots, curr_shots, threshold)
                    
            # ---> AUSGABE DER ALIGNIERTEN LISTE (NEU FORMATIERT) <---
            total_dist = 0.0
            match_count = 0
            
            for idx, (orig_idx, curr_idx, dist) in enumerate(aligned):
                if orig_idx is not None and curr_idx is not None:
                    orig = orig_shots[orig_idx]
                    curr = curr_shots[curr_idx]
                    ox, oy = orig['x'], orig['y']
                    cx, cy = int(curr['pos'][0]), int(curr['pos'][1])
                    dx = cx - ox
                    dy = cy - oy
                    dist = np.hypot(dx, dy)
                    
                    cal_d = cal_r * 2
                    pct = (dist / cal_d) * 100 if cal_d else 0
                    
                    total_dist += dist
                    match_count += 1
                    
                    warn = "⚠️" if pct > 25.0 else ""
                    
                    # ---> NEU: Wir checken, ob der Treffer editiert wurde <---
                    is_edited = orig.get('edited', False)
                    edit_marker = "E" if is_edited else " "
                    
                    # Das 'E' oder Leerzeichen wird direkt an die Nummer gehängt
                    orig_str = f"O:{orig_idx+1:02d}{edit_marker} {ox:>3},{oy:>3}"
                    curr_str = f"N:{curr_idx+1:02d}  {cx:>3},{cy:>3}"
                    
                    # ---> NEU: Wir laden beide Scores! <---
                    orig_cv = orig.get('cv_score', 0.0)
                    curr_cv = curr.get('cv_score', 0.0)
                    
                    # Der Trick: Wir packen pct und warn in EINEN String und richten diesen linksbündig auf 13 Zeichen aus
                    pct_str = f"{pct:.1f}% {warn}"
                    
                    txt.insert(tk.END, f"{idx+1:3d} | {orig_str:<16} | {curr_str:<16} | {dx:+4d} | {dy:+4d} | {dist:7.1f}p | {orig_cv:7.1f} | {curr_cv:7.1f} | {pct_str:<13}\n")
                    
                elif orig_idx is not None:
                    orig = orig_shots[orig_idx]
                    
                    # ---> NEU: Auch hier den Marker prüfen <---
                    is_edited = orig.get('edited', False)
                    edit_marker = "E" if is_edited else " "
                    
                    orig_str = f"O:{orig_idx+1:02d}{edit_marker} {orig['x']:>3},{orig['y']:>3}"
                    orig_cv = orig.get('cv_score', 0.0)
                    txt.insert(tk.END, f"{idx+1:3d} | {orig_str:<16} | {'--- FEHLT ---':<16} |   -- |   -- |       -- | {orig_cv:7.1f} |      -- |         -- ❌\n")
                    
                elif curr_idx is not None:
                    curr = curr_shots[curr_idx]
                    cx, cy = int(curr['pos'][0]), int(curr['pos'][1])
                    curr_str = f"N:{curr_idx+1:02d}  {cx:>3},{cy:>3}"
                    curr_cv = curr.get('cv_score', 0.0)
                    txt.insert(tk.END, f"{idx+1:3d} | {'--- FEHLT ---':<16} | {curr_str:<16} |   -- |   -- |       -- |      -- | {curr_cv:7.1f} |         -- 🆕\n")

            if match_count > 0:
                avg_dist = total_dist / match_count
                txt.insert(tk.END, "-"*99 + "\n")
                txt.insert(tk.END, f"Ø Abweichung {side_name.upper()} (nur gematchte Treffer): {avg_dist:.2f} Pixel\n")

        # Tabellen ausgeben
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
            d_config = DummyConfig(self)
            d_dm = DummyDateiManager(self)
            d_sm = StateManager(d_config, d_dm)
            detector = TargetDetector(d_config, d_dm, d_sm, lambda side, text, show_gui=False: None) 

            #with zipfile.ZipFile(self.current_zip_path, 'r') as zf:
            ### Start WEG
            # Setze Referenzen und Startmasken
            for s in ['left', 'right']:
                ref_name = next((f for f in self.all_files if f"referenz_{s}" in f), None)
                if ref_name:
                    ref_img = self.get_img( ref_name)
                    detector.set_reference_image(ref_img, s)
                
                startmask_name = next((f for f in self.all_files if f"cumulative_startmask_{s}" in f), None)
                if startmask_name:
                    startmask_bgr = self.get_img( startmask_name)
                    startmask_gray = cv2.cvtColor(startmask_bgr, cv2.COLOR_BGR2GRAY)
                    state = d_sm.state_left if s == 'left' else d_sm.state_right
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
                
                # Wenn wir im Offline-Labor per Slider arbeiten, sind das CV-generierte Schüsse, also "edited=False" 
                # (es sei denn, wir bauen später noch manuelles Schuss-Verschieben per Maus ins Labor ein).
                
                # Für den Moment: Einfach als neuen, perfekten Schuss in die Timeline schreiben.
                new_match_data["timeline"].append({
                    "t": float(len(new_match_data["timeline"]) + 1.0), # Chronologischer Dummy-Zeitstempel
                    "s": side_char,
                    "x": int(s['pos'][0]),
                    "y": int(s['pos'][1]),
                    "a": round(float(s['area']), 1),
                    "score": float(s.get('score', 0.0)),
                    "cv_score": round(float(s.get('cv_score', 0.0)), 1),
                    "edited": False # Ein neu vom CV-Skript berechneter Schuss ist niemals "edited"
                })


            # =========================================================================
            # NEU: 6. ELA Export (Einfach den RAM-String ziehen!)
            # =========================================================================
            parser = self.package_data.get('config')
            if parser:
                string_io = io.StringIO()
                parser.write(string_io)
                new_ini_str = string_io.getvalue()
            else:
                new_ini_str = None
                
            success = self.dm.export_match_package(
                filepath=save_path,
                match_data=new_match_data,
                config_string=new_ini_str,
                source_zip=self.current_zip_path,
                apply_diet_filter=True
            )
            
            if success:
                messagebox.showinfo("Erfolg", f"Test-Case erfolgreich erstellt:\n{os.path.basename(save_path)}\n\n(Match.json und config.ini wurden basierend auf der aktuellen Auswertung generiert!)")
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
                d_config = DummyConfig(self)
                d_dm = DummyDateiManager(self)
                d_sm = StateManager(d_config, d_dm)
                detector = TargetDetector(d_config, d_dm, d_sm, lambda side, text, show_gui=False: None) 

                for s in ['left', 'right']:
                    ref_name = next((f for f in self.all_files if f"referenz_{s}" in f), None)
                    if ref_name:
                        detector.set_reference_image(self.get_img(ref_name), s)
                    
                    startmask_name = next((f for f in self.all_files if f"cumulative_startmask_{s}" in f), None)
                    if startmask_name:
                        startmask_gray = cv2.cvtColor(self.get_img(startmask_name), cv2.COLOR_BGR2GRAY)
                        state = d_sm.state_left if s == 'left' else d_sm.state_right
                        state.cumulative_mask = startmask_gray

                for orig_name in self.orig_files:
                    s = 'left' if 'left' in orig_name else 'right'
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
                        "x": int(s['pos'][0]),
                        "y": int(s['pos'][1]),
                        "a": round(float(s['area']), 1),
                        "score": float(s.get('score', 0.0)),
                        "cv_score": round(float(s.get('cv_score', 0.0)), 1),
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
            messagebox.showerror("Kritischer Fehler", f"Fehler beim Übernehmen:\n{str(e)}")
        
    def update_image_display(self):
        """Zeichnet die zwischengespeicherten Bilder mit dem aktuellen Zoom-Faktor neu"""
        if getattr(self, 'last_live_img', None) is None: return

        h, w = self.last_live_img.shape[:2]
        mode = self.view_mode_var.get()
        
        # Hilfsfunktion, um Graustufen-Bilder sicher in Farbe (3 Kanäle) zu konvertieren
        def to_bgr(img):
            if img is None: return np.zeros((h, w, 3), dtype=np.uint8)
            if len(img.shape) == 2: return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            return img

        diff_bgr = to_bgr(self.last_diff_img)
        
        # Entscheidung, was rechts angezeigt werden soll
        if mode == 1:
            right_img = diff_bgr
        elif mode == 2:
            right_img = to_bgr(self.last_diff_gesamt_img)
        elif mode == 4: 
            # ---> DIE MAGISCHE HEATMAP (Neue Logik: Erst stanzen, dann flicken!) <---
            raw = getattr(self, 'last_raw_diff', np.zeros((h, w), dtype=np.uint8))
            thresh_raw = getattr(self, 'last_thresh_raw', np.zeros((h, w), dtype=np.uint8))
            hist_mask = getattr(self, 'last_history_mask', np.zeros((h, w), dtype=np.uint8))
            
            # Hintergrund bereinigen
            raw_display = raw.copy()
            if hist_mask is not None and cv2.countNonZero(hist_mask) > 0:
                raw_display[hist_mask > 0] = 0
            base_gray = cv2.cvtColor(raw_display, cv2.COLOR_GRAY2BGR)
            
            # 1. ERST die Historie abziehen! (Wir erhalten isolierte, nackte Risse)
            if hist_mask is not None and cv2.countNonZero(hist_mask) > 0:
                new_fragments_raw = cv2.subtract(thresh_raw, hist_mask)
            else:
                new_fragments_raw = thresh_raw.copy()
                
            # Reste köpfen
            _, new_fragments_raw = cv2.threshold(new_fragments_raw, 127, 255, cv2.THRESH_BINARY)
            
            # 2. DANN den Morph-Filter anwenden (Schließt jetzt echte Lücken!)
            k_size = self.morph_kernel_var.get()
            if k_size > 0:
                kernel = np.ones((k_size, k_size), np.uint8)
                new_fragments_morphed = cv2.morphologyEx(new_fragments_raw, cv2.MORPH_CLOSE, kernel)
            else:
                new_fragments_morphed = new_fragments_raw.copy()
                
            ## ====================================================================
            ## ---> DEIN DEBUG-EXPORT-BLOCK <---
            ## ====================================================================
            #import os
            #export_dir = "labor_export"
            #os.makedirs(export_dir, exist_ok=True)
            #
            #cv2.imwrite(os.path.join(export_dir, "debug_00_final_morphed_gesamt.png"), new_fragments_morphed)
            #contours, _ = cv2.findContours(new_fragments_morphed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            #
            #for i, cnt in enumerate(contours):
            #    area = cv2.contourArea(cnt)
            #    single_contour_mask = np.zeros_like(new_fragments_morphed)
            #    cv2.drawContours(single_contour_mask, [cnt], -1, 255, -1)
            #    
            #    x, y, cw, ch = cv2.boundingRect(cnt)
            #    if cw > 0 and ch > 0:
            #        cropped_contour = single_contour_mask[y:y+ch, x:x+cw]
            #        filename = f"debug_contour_{i:03d}_area_{area:.1f}.png"
            #        cv2.imwrite(os.path.join(export_dir, filename), cropped_contour)
            ## ====================================================================

            # 3. Differenz bilden: Was genau hat der Morph-Filter hinzugefügt?
            added_by_morph = cv2.subtract(new_fragments_morphed, new_fragments_raw)
            
            # 4. Einfärben: Rot = Nackter Riss | Blau = Neue Morph-Brücke
            bool_base = new_fragments_raw > 0
            bool_morph = added_by_morph > 0
            
            red_overlay = np.zeros_like(base_gray)
            red_overlay[:,:,2] = np.maximum(raw_display, 100) 
            
            blue_overlay = np.zeros_like(base_gray)
            blue_overlay[:,:,0] = 255 
            
            right_img = base_gray.copy()
            right_img[bool_base] = red_overlay[bool_base]
            right_img[bool_morph] = blue_overlay[bool_morph]
        elif mode == 5:
            # ---> NEU: Das völlig rohe, nackte Bild <---
            if hasattr(self, 'last_clean_live_img'):
                right_img = self.last_clean_live_img.copy()
            else:
                right_img = np.zeros((h, w, 3), dtype=np.uint8)
                
        
        
        
        else: # Modus 3: Die Überlagerung
            ref = to_bgr(self.last_ref_img)
            
            # Mitte: Aktuelles Diff-Bild mit 80% Transparenz auf das Referenzbild legen
            composite = cv2.addWeighted(ref, 0.65, diff_bgr, 0.65, 0)
            
            # Oben: Diff-Gesamt-Bild (Schwarz ausblenden, Weiß zu Grün machen)
            diff_gesamt = self.last_diff_gesamt_img
            if diff_gesamt is not None:
                ## Maske aus dem Gesamt-Diff generieren (alles Weiße wird zu True)
                #mask = (cv2.cvtColor(diff_gesamt, cv2.COLOR_BGR2GRAY) > 127) if len(diff_gesamt.shape) == 3 else (diff_gesamt > 127)
                # ---> KORREKTUR: Alles Schwarze (< 127) wird zu True für die grüne Farbe <---
                mask = (cv2.cvtColor(diff_gesamt, cv2.COLOR_BGR2GRAY) < 127) if len(diff_gesamt.shape) == 3 else (diff_gesamt < 127)
                
                # Komplett grünes Bild in der Größe des Composites erzeugen
                green_overlay = np.zeros_like(composite)
                green_overlay[:] = (0, 255, 0) # Grün in BGR
                
                # Nur dort, wo die Maske weiß ist, das Grün mit 50% über das Composite blenden
                composite[mask] = cv2.addWeighted(composite[mask], 0.5, green_overlay[mask], 0.5, 0)
                
            right_img = composite
        
        # Zoom-Faktor einrechnen
        self.current_scale = (550 / h) * self.zoom_factor
        self.current_img_w = int(w * self.current_scale)
        new_h = int(h * self.current_scale)
        
        # NEAREST-Interpolation für scharfe Pixel-Grenzen beim Zoomen
        resized_live = cv2.resize(self.last_live_img, (self.current_img_w, new_h), interpolation=cv2.INTER_NEAREST)
        resized_right = cv2.resize(right_img, (self.current_img_w, new_h), interpolation=cv2.INTER_NEAREST)
        
        combined = np.hstack((resized_live, resized_right))
        
        # ---> NEU: Das nackte Bild ohne Maus-Overlay als Base-Image merken <---
        self.base_combined_img = combined.copy()
        
        img_pil = Image.fromarray(cv2.cvtColor(combined, cv2.COLOR_BGR2RGB))
        self.tk_image = ImageTk.PhotoImage(img_pil)
        self.lbl_image.config(image=self.tk_image, text="")

    def open_all_settings_dialog(self):
        """Öffnet ein dynamisches Fenster mit allen ERWEITERTEN Werten aus der aktuellen config.ini."""
        if not getattr(self, 'package_data', None) or not self.package_data.get('config'):
            messagebox.showwarning("Fehler", "Es ist kein ZIP-Paket geladen!")
            return

        parser = self.package_data['config']

        # ---> NEU: Diese Keys haben bereits einen Slider in der Haupt-GUI und werden hier versteckt <---
        ignore_keys = {
            'hit_tolerance', 'min_hole_area', 'caliber_radius', 
            'hybrid_sichel_faktor', 'hybrid_riss_faktor', 'hybrid_discard_faktor', 
            'hough_min_faktor', 'hough_max_faktor', 'hough_param1', 'hough_param2', 
            'morph_kernel_size', 'max_aspect_ratio', 'gesamt_anteil_am_200score'
        }

        # Neues Fenster erstellen
        dialog = tk.Toplevel(self.root)
        dialog.title("Erweiterte Einstellungen (Live Data-Binding)")
        dialog.geometry("550x800")
        dialog.attributes('-topmost', True)

        # =========================================================================
        # ---> NEU: Der universelle, wartungsfreie Hinweis-Banner <---
        # =========================================================================
        info_frame = tk.Frame(dialog, bg="#fff3cd", bd=1, relief=tk.SOLID)
        info_frame.pack(fill=tk.X, padx=10, pady=(10, 0))
        info_lbl = tk.Label(info_frame, 
                            text="⚠️ WICHTIGER HINWEIS:\nTiefe Systemeinstellungen (wie Kameras, Bild-Zuschnitte/Crops oder Vollbild)\nwerden erst nach einem Neustart von TargetVision aktiv.\nAlle Erkennungs-Parameter (Filter, Toleranzen) greifen sofort!",
                            bg="#fff3cd", fg="#856404", font=("Arial", 9), justify=tk.CENTER)
        info_lbl.pack(padx=5, pady=5)
        # =========================================================================

        # Scrollbereich aufbauen
        canvas = tk.Canvas(dialog, borderwidth=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Zielscheiben für das Dropdown laden
        targets = list(self.dm.load_targets().keys()) if self.dm.load_targets() else ["Luftgewehr_10m"]

        # Durch die Config schleifen
        for section in parser.sections():
            
            # ---> NEU: Vorab prüfen, ob überhaupt noch Keys übrig sind, die wir anzeigen wollen <---
            visible_keys = [k for k in parser.options(section) if k not in ignore_keys]
            if not visible_keys:
                continue # Sektion überspringen, falls sie durch den Filter komplett leer wäre

            sec_frame = tk.LabelFrame(scrollable_frame, text=f" {section} ", font=("Arial", 11, "bold"), pady=8, padx=8)
            sec_frame.pack(fill=tk.X, pady=5, padx=10)

            for key, val in parser.items(section):
                # ---> NEU: Slider-Keys rigoros ignorieren <---
                if key in ignore_keys:
                    continue
                    
                val_str = str(val).strip()
                
                row = tk.Frame(sec_frame)
                row.pack(fill=tk.X, pady=2)
                
                # ---> NEU: Label in Variable speichern und Tooltip anheften <---
                lbl_key = tk.Label(row, text=key, width=32, anchor="w")
                lbl_key.pack(side=tk.LEFT)
                
                if key in PARAMETER_LEXIKON:
                    ToolTip(lbl_key, PARAMETER_LEXIKON[key])

                # Der universelle Trace-Spion
                def make_trace_cmd(s, k, var_obj):
                    def cmd(*args):
                        try:
                            v = var_obj.get()
                        except tk.TclError:
                            # Der Nutzer tippt gerade und das Feld ist leer ("") oder hat nur ein Minus ("-").
                            # Wir ignorieren das einfach und warten auf die nächste Ziffer!
                            return
                            
                        # Booleans wieder als yes/no in die Config schreiben
                        if isinstance(v, bool):
                            v_str = "yes" if v else "no"
                        else:
                            v_str = str(v)
                        
                        parser.set(s, k, v_str)
                        # Trigger Live-Update in der Haupt-GUI
                        self.on_param_change() 
                    return cmd

                # 1. SPECIAL CASE: Aktive Scheibe
                if key == 'aktive_scheibe':
                    var = tk.StringVar(value=val_str)
                    cb = ttk.Combobox(row, textvariable=var, values=targets, state="readonly", width=20)
                    cb.pack(side=tk.RIGHT)
                    var.trace_add("write", make_trace_cmd(section, key, var))

                # 2. BOOLEAN (yes/no) - '0' und '1' wurden hier als Trigger entfernt!
                elif val_str.lower() in ['yes', 'no', 'true', 'false', 'on', 'off']:
                    is_true = val_str.lower() in ['yes', 'true', 'on']
                    var = tk.BooleanVar(value=is_true)
                    chk = tk.Checkbutton(row, text="Aktiv", variable=var)
                    chk.pack(side=tk.RIGHT)
                    var.trace_add("write", make_trace_cmd(section, key, var))

                # 3. FLOAT (Hat einen Punkt und besteht sonst aus Zahlen/Minus)
                elif '.' in val_str and val_str.replace('.', '', 1).replace('-', '', 1).isdigit():
                    var = tk.DoubleVar(value=float(val_str))
                    entry = tk.Entry(row, textvariable=var, width=12, justify="right")
                    entry.pack(side=tk.RIGHT)
                    var.trace_add("write", make_trace_cmd(section, key, var))

                # 4. INTEGER (Besteht nur aus Zahlen/Minus)
                elif val_str.replace('-', '', 1).isdigit():
                    var = tk.IntVar(value=int(val_str))
                    entry = tk.Entry(row, textvariable=var, width=12, justify="right")
                    entry.pack(side=tk.RIGHT)
                    var.trace_add("write", make_trace_cmd(section, key, var))

                # 5. STRING (Alles andere)
                else:
                    var = tk.StringVar(value=val_str)
                    entry = tk.Entry(row, textvariable=var, width=22, justify="right")
                    entry.pack(side=tk.RIGHT)
                    var.trace_add("write", make_trace_cmd(section, key, var))

        # Scroll-Fix fürs Mausrad
        def _on_mousewheel(event):
            if event.num == 4 or getattr(event, 'delta', 0) > 0:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5 or getattr(event, 'delta', 0) < 0:
                canvas.yview_scroll(1, "units")

        dialog.bind("<MouseWheel>", _on_mousewheel)
        dialog.bind("<Button-4>", _on_mousewheel)
        dialog.bind("<Button-5>", _on_mousewheel)

if __name__ == "__main__":
    import sys # Für sys.argv
    root = tk.Tk()
    app = OfflineLaborApp(root)
    
    # Wurde uns vom Live-System ein ZIP-Pfad in die Hand gedrückt?
    if len(sys.argv) > 1:
        zip_path = sys.argv[1]
        # Wir warten 100ms, damit die GUI erst kurz aufploppt, bevor sie rechnet
        root.after(100, lambda: app.load_zip(zip_path))
    else:
        # ---> NEU: Das Labor wurde manuell gestartet! Lade die lokale Config <---
        root.after(100, lambda: app.load_local_config())
        
    root.mainloop()