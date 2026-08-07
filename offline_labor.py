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
        return fallback
        
    def getfloat(self, section, key, fallback=0.0):
        if key == 'hybrid_riss_faktor': return self.app.hybrid_riss_faktor_var.get()
        if key == 'hybrid_sichel_faktor': return self.app.hybrid_sichel_faktor_var.get()
        if key == 'hybrid_discard_faktor': return self.app.hybrid_discard_faktor_var.get()
        if key == 'hough_min_faktor': return self.app.hough_min_faktor_var.get()
        if key == 'hough_max_faktor': return self.app.hough_max_faktor_var.get()
        if key == 'max_image_change_percent': return 90.0 # Hoch setzen, damit das Labor alles frisst
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
        
    def add_shot(self, side, cx, cy, area):
        shot = {'side': side, 'pos': (cx, cy), 'area': area, 'score': 10.9, 'is_new': True}
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
        self.hybrid_riss_faktor_var = tk.DoubleVar(value=1.5)
        self.hybrid_sichel_faktor_var = tk.DoubleVar(value=0.75)
        self.hybrid_discard_faktor_var = tk.DoubleVar(value=2.5)
        self.hough_min_faktor_var = tk.DoubleVar(value=0.85)
        self.hough_max_faktor_var = tk.DoubleVar(value=1.15)
        
        
        
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
        
        # MAIN FRAME
        main_frame = tk.Frame(self.root, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # LINKS: Bild-Ansicht
        self.image_frame = tk.LabelFrame(main_frame, text=" Live-Labor (Original + Marker | Aktuelles Diff) ", bg="#222222", fg="white")
        self.image_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        self.lbl_image = tk.Label(self.image_frame, text="Warte auf ZIP-Datei...", bg="#222222", fg="gray", font=("Arial", 14))
        self.lbl_image.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        self.log_text = tk.Text(self.image_frame, height=10, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        self.log_text.pack(side=tk.BOTTOM, fill=tk.X)
        
        # RECHTS: Steuerpult
        control_frame = tk.Frame(main_frame, width=400)
        control_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        nav_frame = tk.LabelFrame(control_frame, text=" Schuss-Navigation ", pady=10, padx=10)
        nav_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.btn_prev = tk.Button(nav_frame, text="◀ Zurück", state=tk.DISABLED, command=self.prev_shot)
        self.btn_prev.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.lbl_shot_info = tk.Label(nav_frame, text="Schuss - / -", font=("Arial", 10, "bold"))
        self.lbl_shot_info.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.btn_next = tk.Button(nav_frame, text="Weiter ▶", state=tk.DISABLED, command=self.next_shot)
        self.btn_next.pack(side=tk.RIGHT, expand=True, fill=tk.X)
        
        param_frame = tk.LabelFrame(control_frame, text=" Erkennungs-Parameter (Live) ", pady=10, padx=10)
        param_frame.pack(fill=tk.BOTH, expand=True)
        
        self.make_slider(param_frame, "hit_tolerance:", self.hit_tolerance_var, 1, 100)
        self.make_slider(param_frame, "min_hole_area:", self.min_hole_area_var, 5, 500)
        self.make_slider(param_frame, "caliber_radius:", self.caliber_radius_var, 5, 50)
        
        tk.Label(param_frame, text="--- Hybrid & Hough Faktoren ---", fg="gray").pack(pady=(10, 5))
        
        self.make_slider(param_frame, "hybrid_sichel_faktor:", self.hybrid_sichel_faktor_var, 0.1, 1.5, 0.05)
        self.make_slider(param_frame, "hybrid_riss_faktor:", self.hybrid_riss_faktor_var, 1.0, 3.0, 0.05)
        self.make_slider(param_frame, "hybrid_discard_faktor:", self.hybrid_discard_faktor_var, 1.5, 5.0, 0.1)
        self.make_slider(param_frame, "hough_min_faktor:", self.hough_min_faktor_var, 0.5, 1.0, 0.05)
        self.make_slider(param_frame, "hough_max_faktor:", self.hough_max_faktor_var, 1.0, 2.0, 0.05)
        
        tk.Checkbutton(param_frame, text="💾 Simulations-Bilder auf SSD exportieren", 
                       variable=self.export_images_var, fg="#00aaff").pack(anchor=tk.W, pady=(15, 0))

    def print_log(self, side, msg):
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
                
            # Finde alle "_orig" Bilder und sortiere sie streng alphabetisch
            self.orig_files = sorted([f for f in self.all_files if "_orig" in f])
            if not self.orig_files:
                self.lbl_image.config(text="⚠️ Keine Schuss-Bilder (_orig) gefunden!", fg="red")
                return
                
            self.current_index = 0
            self.btn_prev.config(state=tk.NORMAL)
            self.btn_next.config(state=tk.NORMAL)
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
            
    def on_param_change(self, event=None):
        if self.current_zip_path:
            # Tkinter feuert Events oft mehrfach bei Scrollen, process_and_display regelt das
            self.process_and_display()

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
                detector.detect_new_shot(img, side)
                if i == target_idx:
                    live_img = img.copy()

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

        # Side-by-Side anordnen
        h, w = live_img.shape[:2]
        scale = 550 / h
        new_w, new_h = int(w * scale), int(h * scale)
        
        combined = np.hstack((cv2.resize(live_img, (new_w, new_h)), cv2.resize(diff_img, (new_w, new_h))))
        img_pil = Image.fromarray(cv2.cvtColor(combined, cv2.COLOR_BGR2RGB))
        
        self.tk_image = ImageTk.PhotoImage(img_pil)
        self.lbl_image.config(image=self.tk_image, text="")

if __name__ == "__main__":
    root = tk.Tk()
    app = OfflineLaborApp(root)
    root.mainloop()