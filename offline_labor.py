import json
import tkinter as tk
from tkinter import filedialog, ttk
import zipfile
import cv2
import numpy as np
import configparser
import io
from PIL import Image, ImageTk

# ---> HIER IMPORTIEREN WIR DEINE ECHTE ENGINE! <---
from DetectionDeLuebs import TargetDetector

# ==========================================
# DUMMY-KLASSEN FÜR DIE TARGET-DETECTION
# ==========================================
class DummyConfig:
    def __init__(self, app):
        self.app = app
        
    def getint(self, section, key, fallback=0):
        if key == 'min_hole_area': return self.app.min_hole_area_var.get()
        if key == 'caliber_radius': return self.app.caliber_radius_var.get()
        if key == 'hit_tolerance': return self.app.hit_tolerance_var.get()
        if key == 'hough_param1': return self.app.hough_param1_var.get()
        if key == 'hough_param2': return self.app.hough_param2_var.get()
        # ---> NEU <---
        if key == 'morph_kernel_size': return self.app.morph_kernel_var.get()
        return fallback
        
    def getfloat(self, section, key, fallback=0.0):
        if key == 'hybrid_riss_faktor': return self.app.hybrid_riss_faktor_var.get()
        if key == 'hybrid_sichel_faktor': return self.app.hybrid_sichel_faktor_var.get()
        if key == 'hybrid_discard_faktor': return self.app.hybrid_discard_faktor_var.get()
        if key == 'hough_min_faktor': return self.app.hough_min_faktor_var.get()
        if key == 'hough_max_faktor': return self.app.hough_max_faktor_var.get()
        if key == 'max_image_change_percent': return 90.0
        # ---> NEU <---
        if key == 'max_aspect_ratio': return self.app.max_aspect_ratio_var.get()
        return fallback
        
    def get(self, section, key, fallback=''):
        if key == 'erkennungs_methode': return 'C'
        if key == 'aktive_scheibe': return 'Luftgewehr_10m'
        return fallback
        
    def getboolean(self, section, key, fallback=False):
        return fallback

class DummyState:
    def __init__(self, side):
        self.side = side
        self.cumulative_mask = None
        self.target_present = True

class DummyStateManager:
    def __init__(self):
        self.state_left = DummyState('left')
        self.state_right = DummyState('right')
        self.shots = []
        
    def add_shot(self, side, cx, cy, area, cv_score=0.0, **kwargs):
        shot = {'side': side, 'pos': (cx, cy), 'area': area, 'score': 10.9, 'is_new': True, 'cv_score': cv_score}
        self.shots.append(shot)
        return shot
        
    def set_nullpunkt(self, side, x, y): pass

class DummyDateiManager:
    def __init__(self, app):
        self.app = app
        self.debug_images = {}
        self.export_folder = "labor_export"
        
    def save_debug_image(self, name, image):
        # 1. Immer in den RAM für die GUI
        self.debug_images[name] = image.copy()
        
        # 2. Optional auf die Festplatte, wenn Checkbox aktiv ist
        if self.app.export_images_var.get():
            import os
            if not os.path.exists(self.export_folder):
                os.makedirs(self.export_folder)
            
            ext = ".png" if "diff" in name.lower() or "mask" in name.lower() else ".jpg"
            path = os.path.join(self.export_folder, f"{name}{ext}")
            cv2.imwrite(path, image)
            
    def load_targets(self):
        return {}


# ==========================================
# GUI UND LOGIK
# ==========================================
class OfflineLaborApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TargetVision Replay-Labor (Live Engine)")
        self.root.geometry("1400x850")
        
        self.current_zip_path = None
        self.all_files = []
        self.orig_files = []
        self.current_index = 0
        self.tk_image = None
        self.export_images_var = tk.BooleanVar(value=False)
        
        # TK-Variablen für Slider
        self.hit_tolerance_var = tk.IntVar(value=22)
        self.min_hole_area_var = tk.IntVar(value=25)
        self.caliber_radius_var = tk.IntVar(value=11)
        self.hybrid_riss_faktor_var = tk.DoubleVar(value=1.35)
        self.hybrid_sichel_faktor_var = tk.DoubleVar(value=1.05)
        self.hybrid_discard_faktor_var = tk.DoubleVar(value=2.5)
        self.hough_min_faktor_var = tk.DoubleVar(value=0.85)
        self.hough_max_faktor_var = tk.DoubleVar(value=1.15)
        
        self.hough_param1_var = tk.IntVar(value=25)
        self.hough_param2_var = tk.IntVar(value=5)
        # ---> NEU <---
        self.morph_kernel_var = tk.IntVar(value=6)
        self.max_aspect_ratio_var = tk.DoubleVar(value=3.5)
        
        self.zoom_factor = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.view_mode_var = tk.IntVar(value=1)
        
        self.setup_ui()
        
    def make_slider(self, parent, label_text, tk_var, from_, to_, res=1):
        """Hilfsfunktion für einheitliche Slider"""
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)
        tk.Label(frame, text=label_text, width=25, anchor="w").pack(side=tk.LEFT)
        scale = tk.Scale(frame, from_=from_, to_=to_, resolution=res, orient=tk.HORIZONTAL, 
                         variable=tk_var, command=self.on_param_change)
        scale.pack(side=tk.RIGHT, fill=tk.X, expand=True)

    def setup_ui(self):
        # TOP FRAME
        top_frame = tk.Frame(self.root, pady=10, padx=10)
        top_frame.pack(fill=tk.X)
        
        tk.Button(top_frame, text="📦 ZIP-Paket laden", command=self.load_zip, font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.lbl_file = tk.Label(top_frame, text="Kein ZIP ausgewählt", fg="gray", font=("Arial", 10))
        self.lbl_file.pack(side=tk.LEFT, padx=15)
        
        # ---> HIER WANDERT DER BUTTON HIN <---
        self.btn_compare = tk.Button(top_frame, text="📊 Match-Abweichung messen", command=self.show_comparison, font=("Arial", 10, "bold"))
        self.btn_compare.pack(side=tk.LEFT, padx=20)        
        
        # ---> NEU: Das Koordinaten-Label oben rechts <---
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
        
        # RECHTS: Steuerpult
        control_frame = tk.Frame(main_frame, width=400)
        control_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        nav_frame = tk.LabelFrame(control_frame, text=" Schuss-Navigation ", pady=10, padx=10)
        nav_frame.pack(fill=tk.X, pady=(0, 15))
        
        # ---> NEU: 5 Buttons mit fester Breite und ohne Expand <---
        self.btn_first = tk.Button(nav_frame, text="<<", state=tk.DISABLED, command=self.first_shot, width=3)
        self.btn_first.pack(side=tk.LEFT, padx=(0, 2))
        self.btn_prev = tk.Button(nav_frame, text="◀ Zurück", state=tk.DISABLED, command=self.prev_shot, width=8)
        self.btn_prev.pack(side=tk.LEFT)
        # Das Label in der Mitte dehnt sich aus (expand=True), um den Platz zu füllen
        self.lbl_shot_info = tk.Label(nav_frame, text="Schuss - / -", font=("Arial", 10, "bold"))
        self.lbl_shot_info.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.btn_last = tk.Button(nav_frame, text=">>", state=tk.DISABLED, command=self.last_shot, width=3)
        self.btn_last.pack(side=tk.RIGHT, padx=(2, 0))
        self.btn_next = tk.Button(nav_frame, text="Weiter ▶", state=tk.DISABLED, command=self.next_shot, width=8)
        self.btn_next.pack(side=tk.RIGHT)
        
        ## ---> NEU: Der Vergleichs-Button <---
        #self.btn_compare = tk.Button(nav_frame, text="📊 Abweichung zum Original messen", command=self.show_comparison, bg="#2c3e50", fg="white")
        #self.btn_compare.pack(side=tk.BOTTOM, fill=tk.X, pady=(10,0))
        
        # ---> NEU: Ansichts-Steuerung <---
        view_frame = tk.LabelFrame(control_frame, text=" Rechte Bildhälfte ", pady=10, padx=10)
        view_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Radiobutton(view_frame, text="1) Diff-Bild (Letzter Schuss)", variable=self.view_mode_var, value=1, command=self.update_image_display).pack(anchor=tk.W)
        tk.Radiobutton(view_frame, text="2) Diff-Gesamt-Bild (Historie)", variable=self.view_mode_var, value=2, command=self.update_image_display).pack(anchor=tk.W)
        tk.Radiobutton(view_frame, text="3) Überlagerung (Ref + Diff + Gesamt)", variable=self.view_mode_var, value=3, command=self.update_image_display).pack(anchor=tk.W)
        
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
        self.make_slider(param_frame, "hit_tolerance:", self.hit_tolerance_var, 1, 100)
        self.make_slider(param_frame, "min_hole_area:", self.min_hole_area_var, 5, 500)
        self.make_slider(param_frame, "caliber_radius:", self.caliber_radius_var, 5, 50)
        
        tk.Label(param_frame, text="--- Hybrid & Hough Faktoren ---", fg="gray").pack(pady=(10, 5))
        
        self.make_slider(param_frame, "hybrid_sichel_faktor:", self.hybrid_sichel_faktor_var, 0.1, 1.5, 0.05)
        self.make_slider(param_frame, "hybrid_riss_faktor:", self.hybrid_riss_faktor_var, 1.0, 3.0, 0.05)
        self.make_slider(param_frame, "hybrid_discard_faktor:", self.hybrid_discard_faktor_var, 1.5, 5.0, 0.1)
        self.make_slider(param_frame, "hough_min_faktor:", self.hough_min_faktor_var, 0.5, 1.0, 0.05)
        self.make_slider(param_frame, "hough_max_faktor:", self.hough_max_faktor_var, 1.0, 2.0, 0.05)
        
        self.make_slider(param_frame, "hough_param1 (Kanten):", self.hough_param1_var, 10, 100)
        self.make_slider(param_frame, "hough_param2 (Strenge):", self.hough_param2_var, 1, 20)
        
        tk.Label(param_frame, text="--- Bild-Filterung ---", fg="gray").pack(pady=(10, 5))
        self.make_slider(param_frame, "morph_kernel_size:", self.morph_kernel_var, 3, 15)
        self.make_slider(param_frame, "max_aspect_ratio (Sichel):", self.max_aspect_ratio_var, 1.5, 6.0, 0.1)
        
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

    # ---> NEU: Parameter 'show_gui' hinzugefügt, damit das Programm nicht crasht <---
    def print_log(self, side, msg, show_gui=False):
        """Simuliert den Log-Output der Engine in der GUI"""
        self.log_text.insert(tk.END, f"[{side.upper()}] {msg}\n")
        self.log_text.see(tk.END)

    def load_zip(self):
        filepath = filedialog.askopenfilename(title="Wähle ZIP", filetypes=[("ZIP", "*.zip")])
        if filepath:
            self.current_zip_path = filepath
            self.lbl_file.config(text=f"📂 {filepath.split('/')[-1]}", fg="black")
            
            with zipfile.ZipFile(filepath, 'r') as zf:
                self.all_files = zf.namelist()
                
                # Config.ini parsen
                config_name = next((f for f in self.all_files if "config.ini" in f), None)
                if config_name:
                    parser = configparser.ConfigParser()
                    parser.read_file(io.StringIO(zf.read(config_name).decode('utf-8')))
                    if parser.has_section('Erkennung'):
                        self.hit_tolerance_var.set(parser.getint('Erkennung', 'hit_tolerance', fallback=22))
                        self.min_hole_area_var.set(parser.getint('Erkennung', 'min_hole_area', fallback=25))
                        self.caliber_radius_var.set(parser.getint('Erkennung', 'caliber_radius', fallback=11))
                        self.hybrid_riss_faktor_var.set(parser.getfloat('Erkennung', 'hybrid_riss_faktor', fallback=1.5))
                        self.hybrid_sichel_faktor_var.set(parser.getfloat('Erkennung', 'hybrid_sichel_faktor', fallback=0.75))
                        self.hybrid_discard_faktor_var.set(parser.getfloat('Erkennung', 'hybrid_discard_faktor', fallback=2.5))
                        self.hough_min_faktor_var.set(parser.getfloat('Erkennung', 'hough_min_faktor', fallback=0.85))
                        self.hough_max_faktor_var.set(parser.getfloat('Erkennung', 'hough_max_faktor', fallback=1.15))
                
                # ---> NEU: Match.json laden <---
                match_json_name = next((f for f in self.all_files if "match.json" in f), None)
                if match_json_name:
                    self.original_match_data = json.loads(zf.read(match_json_name).decode('utf-8'))
                else:
                    self.original_match_data = None
                
            # Finde alle "_orig" Bilder und sortiere sie streng alphabetisch
            self.orig_files = sorted([f for f in self.all_files if "_orig" in f])
            if not self.orig_files:
                self.lbl_image.config(text="⚠️ Keine Schuss-Bilder (_orig) gefunden!", fg="red")
                return
                
            self.current_index = 0
            self.btn_prev.config(state=tk.NORMAL)
            self.btn_next.config(state=tk.NORMAL)
            self.btn_first.config(state=tk.NORMAL)  # <--- NEU
            self.btn_last.config(state=tk.NORMAL)   # <--- NEU
            self.process_and_display()

    def get_img(self, zf, name):
        return cv2.imdecode(np.frombuffer(zf.read(name), np.uint8), cv2.IMREAD_COLOR)

    def prev_shot(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.process_and_display()

    def next_shot(self):
        if self.current_index < len(self.orig_files) - 1:
            self.current_index += 1
            self.process_and_display()

    def first_shot(self):
        if self.orig_files and self.current_index > 0:
            self.current_index = 0
            self.process_and_display()

    def last_shot(self):
        if self.orig_files and self.current_index < len(self.orig_files) - 1:
            self.current_index = len(self.orig_files) - 1
            self.process_and_display() 

 
    def on_param_change(self, event=None):
        if self.current_zip_path:
            # Tkinter feuert Events oft mehrfach bei Scrollen, process_and_display regelt das
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
        r = int(self.caliber_radius_var.get() * self.current_scale)
        
        # Neon-Blau / Cyan in BGR-Farbraum
        neon_blue = (255, 255, 0)
        
        # Prüfen, ob wir im linken oder rechten Bild sind
        if x < self.current_img_w:
            real_x = int(x / self.current_scale)
            real_y = int(y / self.current_scale)
            self.lbl_coords.config(text=f"Live-Bild -> X: {real_x:04d} | Y: {real_y:04d}")
            
            # ---> NEU: Fadenkreuz im RECHTEN Bild einzeichnen <---
            mirror_x = x + self.current_img_w
            cv2.circle(temp_img, (mirror_x, y), r, neon_blue, 2)
            cv2.circle(temp_img, (mirror_x, y), 2, neon_blue, -1) # Kleiner Punkt in der Mitte
            
        else:
            real_x = int((x - self.current_img_w) / self.current_scale)
            real_y = int(y / self.current_scale)
            self.lbl_coords.config(text=f"Diff-Bild -> X: {real_x:04d} | Y: {real_y:04d}")
            
            # ---> NEU: Fadenkreuz im LINKEN Bild einzeichnen <---
            mirror_x = x - self.current_img_w
            cv2.circle(temp_img, (mirror_x, y), r, neon_blue, 2)
            cv2.circle(temp_img, (mirror_x, y), 2, neon_blue, -1) # Kleiner Punkt in der Mitte

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
        if not self.orig_files or not self.current_zip_path: return
        self.lbl_shot_info.config(text=f"Schuss {self.current_index + 1} / {len(self.orig_files)}")
        self.log_text.delete(1.0, tk.END) # Log leeren
        
        orig_name = self.orig_files[self.current_index]
        side = 'left' if 'left' in orig_name else 'right'
        
        # Alle Schüsse DIESER Seite bis zum aktuellen ermitteln (für Time-Travel)
        side_origs = sorted([f for f in self.orig_files if side in f])
        try:
            target_idx = side_origs.index(orig_name)
        except ValueError:
            return

        # 1. DUMMYS AUFBAUEN
        d_config = DummyConfig(self)
        d_dm = DummyDateiManager(self)
        d_sm = DummyStateManager()
        
        # 2. ECHTE ENGINE STARTEN
        detector = TargetDetector(d_config, d_dm, d_sm, self.print_log)
        
        with zipfile.ZipFile(self.current_zip_path, 'r') as zf:
            ref_name = next((f for f in self.all_files if f"referenz_{side}" in f), None)
            if not ref_name: return
            
            ref_img = self.get_img(zf, ref_name)
            detector.set_reference_image(ref_img, side)
            
            # ---> NEU: Start-Maske (Fortsetzung) suchen und injizieren <---
            startmask_name = next((f for f in self.all_files if f"cumulative_startmask_{side}" in f), None)
            if startmask_name:
                # Bild laden und in Graustufen (1 Kanal) wandeln, wie es die cumulative_mask erwartet
                startmask_bgr = self.get_img(zf, startmask_name)
                startmask_gray = cv2.cvtColor(startmask_bgr, cv2.COLOR_BGR2GRAY)
                
                # In den Dummy-State schmuggeln
                state = d_sm.state_left if side == 'left' else d_sm.state_right
                state.cumulative_mask = startmask_gray
                self.print_log("SYSTEM", f"Fortsetzung erkannt! Start-Maske für {side} geladen.")
            # -------------------------------------------------------------
            
            # 3. TIME-TRAVEL SIMULATION
            # Wir spielen alle Bilder der Seite ab, um die Maske perfekt aufzubauen
            for i in range(target_idx + 1):
                img = self.get_img(zf, side_origs[i])
                
                # ---> NEU: Die unübersehbare Trennlinie vor dem aktuellen Schuss <---
                if i == target_idx:
                    self.log_text.insert(tk.END, "\n" + "▼"*70 + "\n")
                    self.log_text.insert(tk.END, f"███  START DER LIVE-ANALYSE FÜR DEN AKTUELLEN SCHUSS ({i+1})  ███\n")
                    self.log_text.insert(tk.END, "▼"*70 + "\n\n")
                    
                    live_img = img.copy()
                    
                detector.detect_new_shot(img, side)

        # 4. VISUALISIERUNG DER ENGINE-ERGEBNISSE
        # Hole das Diff-Bild direkt aus dem Dummy-DateiManager der Engine!
        diff_img = d_dm.debug_images.get(f"diff_letzter_treffer_{side}")
        if diff_img is None:
            # Fallback falls kein Treffer erkannt wurde
            diff_img = d_dm.debug_images.get(f"diff_letzte_verworfene_auswertung_{side}", np.zeros_like(live_img))
        
        if len(diff_img.shape) == 2:
            diff_img = cv2.cvtColor(diff_img, cv2.COLOR_GRAY2BGR)
            
        # Kreise auf das Live-Bild zeichnen (aus dem StateManager der Engine!)
        r = self.caliber_radius_var.get()
        for shot in d_sm.shots:
            if shot['side'] == side:
                # Grün für alte, Rot für diesen Frame
                color = (0, 0, 255) if shot.get('is_new', False) else (0, 255, 0)
                cv2.circle(live_img, shot['pos'], r, color, 2)

        # ---> NEU: Daten für den späteren Vergleich merken <---
        self.current_engine_shots = d_sm.shots 
        self.current_side = side

        # ---> NEU: Alle nötigen Bilder aus der Engine fischen <---
        h, w = live_img.shape[:2]
        
        diff_gesamt_img = d_dm.debug_images.get(f"diff_gesamt_{side}")
        if diff_gesamt_img is None:
            diff_gesamt_img = np.zeros((h, w), dtype=np.uint8)
            
            
        ref_img = d_dm.debug_images.get(f"referenz_{side}")
        if ref_img is None:
            ref_img = np.zeros((h, w, 3), dtype=np.uint8)

        # Bilder für butterweiches Zoomen im RAM zwischenspeichern
        self.last_live_img = live_img
        self.last_diff_img = diff_img
        self.last_diff_gesamt_img = diff_gesamt_img
        self.last_ref_img = ref_img
        
        self.update_image_display()

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
        d_sm = DummyStateManager()
        # Stumme Log-Funktion, damit die Konsole nicht überflutet wird
        detector = TargetDetector(d_config, d_dm, d_sm, lambda side, text, show_gui=False: None) 

        with zipfile.ZipFile(self.current_zip_path, 'r') as zf:
            # Setze Referenzen und Startmasken für BEIDE Seiten
            for s in ['left', 'right']:
                ref_name = next((f for f in self.all_files if f"referenz_{s}" in f), None)
                if ref_name:
                    ref_img = self.get_img(zf, ref_name)
                    detector.set_reference_image(ref_img, s)
                
                startmask_name = next((f for f in self.all_files if f"cumulative_startmask_{s}" in f), None)
                if startmask_name:
                    startmask_bgr = self.get_img(zf, startmask_name)
                    startmask_gray = cv2.cvtColor(startmask_bgr, cv2.COLOR_BGR2GRAY)
                    state = d_sm.state_left if s == 'left' else d_sm.state_right
                    state.cumulative_mask = startmask_gray

            # Alle orig-Bilder durchjagen
            for orig_name in self.orig_files:
                img = self.get_img(zf, orig_name)
                s = 'left' if 'left' in orig_name else 'right'
                detector.detect_new_shot(img, s)

        # 3. Ausgabe aufbereiten
        txt.delete(1.0, tk.END)
        txt.insert(tk.END, f"VERGLEICH: KOMPLETTES MATCH (Aktuelle Slider-Werte vs. Original-JSON)\n")
        txt.insert(tk.END, "="*85 + "\n")

        cal_r = self.caliber_radius_var.get()
        
        # Hilfsfunktion zum Zeichnen der Tabellen
        def build_side_comparison(side_name, side_char):
            orig_shots = [s for s in self.original_match_data.get("timeline", []) if s.get('s') == side_char]
            curr_shots = [s for s in d_sm.shots if s.get('side') == side_name]
            
            if not orig_shots and not curr_shots: return 
            
            txt.insert(tk.END, f"\n--- KAMERA {side_name.upper()} ---\n")
            txt.insert(tk.END, f"Original Treffer: {len(orig_shots)} | Neu berechnet: {len(curr_shots)}\n")
            
            # Exakte Breiten: dX(4), dY(4), Distanz(8), % Kaliber(13), CV-Score(8)
            header = f"{'Nr':>3} | {'Orig (Idx X,Y)':<16} | {'Neu (Idx X,Y)':<16} | {'dX':>4} | {'dY':>4} | {'Distanz':>8} | {'% Kaliber':<13} | {'CV-Score':>8}\n"
            txt.insert(tk.END, header)
            txt.insert(tk.END, "-"*99 + "\n")
            
            # ---> NEUER ALGORITHMUS: Sequenz-Alignment mit Lookahead <---
            i = 0 # Index für orig
            j = 0 # Index für curr
            aligned = []
            
            # So weit darf ein Schuss abweichen, um noch als "der gleiche Schuss" zu gelten
            threshold = cal_r * 2.5  
            
            while i < len(orig_shots) or j < len(curr_shots):
                if i < len(orig_shots) and j < len(curr_shots):
                    ox, oy = orig_shots[i]['x'], orig_shots[i]['y']
                    cx, cy = int(curr_shots[j]['pos'][0]), int(curr_shots[j]['pos'][1])
                    dist = np.hypot(cx - ox, cy - oy)
                    
                    if dist < threshold:
                        # Perfektes Match
                        aligned.append((i, j, dist))
                        i += 1
                        j += 1
                    else:
                        # LOOKAHEAD 1: Wurde ein neuer Schuss DAZWISCHEN gemogelt? (Einfügung)
                        found_match = False
                        for lookahead in range(1, min(6, len(curr_shots) - j)):
                            nx, ny = int(curr_shots[j + lookahead]['pos'][0]), int(curr_shots[j + lookahead]['pos'][1])
                            if np.hypot(nx - ox, ny - oy) < threshold:
                                found_match = True
                                # Alle Schüsse bis zum gefundenen Match sind NEU
                                for k in range(lookahead):
                                    aligned.append((None, j + k, None))
                                j += lookahead
                                break
                                
                        if found_match: continue
                        
                        # LOOKAHEAD 2: Wurde ein alter Schuss VERSCHLUCKT? (Löschung)
                        for lookahead in range(1, min(6, len(orig_shots) - i)):
                            nx, ny = orig_shots[i + lookahead]['x'], orig_shots[i + lookahead]['y']
                            if np.hypot(cx - nx, cy - ny) < threshold:
                                found_match = True
                                # Alle Schüsse bis zum gefundenen Match FEHLEN nun
                                for k in range(lookahead):
                                    aligned.append((i + k, None, None))
                                i += lookahead
                                break
                                
                        if found_match: continue
                        
                        # Weder noch? Dann ist die Abweichung so extrem, dass wir es als "Ersetzt" werten
                        aligned.append((i, j, dist))
                        i += 1
                        j += 1
                        
                elif i < len(orig_shots):
                    aligned.append((i, None, None))
                    i += 1
                elif j < len(curr_shots):
                    aligned.append((None, j, None))
                    j += 1
                    
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
                    
                    orig_str = f"O:{orig_idx+1:02d}  {ox:>3},{oy:>3}"
                    curr_str = f"N:{curr_idx+1:02d}  {cx:>3},{cy:>3}"
                    cv_score = curr.get('cv_score', 0.0)
                    
                    # Der Trick: Wir packen pct und warn in EINEN String und richten diesen linksbündig auf 13 Zeichen aus
                    pct_str = f"{pct:.1f}% {warn}"
                    
                    txt.insert(tk.END, f"{idx+1:3d} | {orig_str:<16} | {curr_str:<16} | {dx:+4d} | {dy:+4d} | {dist:7.1f}p | {pct_str:<13} | {cv_score:8.1f}\n")
                    
                elif orig_idx is not None:
                    orig = orig_shots[orig_idx]
                    orig_str = f"O:{orig_idx+1:02d}  {orig['x']:>3},{orig['y']:>3}"
                    txt.insert(tk.END, f"{idx+1:3d} | {orig_str:<16} | {'--- FEHLT ---':<16} |   -- |   -- |       -- |         -- ❌ |       --\n")
                    
                elif curr_idx is not None:
                    curr = curr_shots[curr_idx]
                    cx, cy = int(curr['pos'][0]), int(curr['pos'][1])
                    curr_str = f"N:{curr_idx+1:02d}  {cx:>3},{cy:>3}"
                    cv_score = curr.get('cv_score', 0.0)
                    txt.insert(tk.END, f"{idx+1:3d} | {'--- FEHLT ---':<16} | {curr_str:<16} |   -- |   -- |       -- |         -- 🆕 | {cv_score:8.1f}\n")

            if match_count > 0:
                avg_dist = total_dist / match_count
                txt.insert(tk.END, "-"*99 + "\n")
                txt.insert(tk.END, f"Ø Abweichung {side_name.upper()} (nur gematchte Treffer): {avg_dist:.2f} Pixel\n")

        # Tabellen ausgeben
        build_side_comparison('left', 'l')
        build_side_comparison('right', 'r')
        
        txt.config(state=tk.DISABLED)
        
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

if __name__ == "__main__":
    root = tk.Tk()
    app = OfflineLaborApp(root)
    root.mainloop()