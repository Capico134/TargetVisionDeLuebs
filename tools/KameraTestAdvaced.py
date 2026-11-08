import cv2
import time
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from PIL import Image, ImageTk

# =====================================================================
# DER ULTIMATIVE ELP-KAMERA-HÄRTETEST (GUI VERSION)
# =====================================================================
TEST_DURATION = 3.0  # 3 Sekunden Messung pro Kombination

BACKENDS = [
    ("MSMF", cv2.CAP_MSMF),
    ("DSHOW", cv2.CAP_DSHOW)
]
INIT_MODES = ["Pre-Set", "Post-Set"] 
RESOLUTIONS = [(1920, 1080), (1280, 720)]
FPS_TARGETS = [30, 60]  # 60 FPS wieder mit drin!
CODECS = ["MJPG", "YUY2", "None"]

def decode_fourcc(v):
    try:
        v = int(v)
        res = "".join([chr((v >> 8 * i) & 0xFF) for i in range(4)]).strip()
        return res if res.isprintable() and len(res) > 0 else "Unbekannt"
    except Exception:
        return "Unbekannt"

def run_test_iteration(cam_index, backend_name, backend_id, init_mode, w, h, fps_target, codec_str, ui_callback):
    ui_callback(f"Teste: {backend_name:<5} | {init_mode:<8} | {w}x{h}@{fps_target}fps | Codec: {codec_str:<5}...", end="")
    
    t0 = time.perf_counter()
    cap = None
    
    try:
        if init_mode == "Pre-Set":
            params = []
            if codec_str != "None":
                params.extend([cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*codec_str)])
            params.extend([
                cv2.CAP_PROP_FRAME_WIDTH, w,
                cv2.CAP_PROP_FRAME_HEIGHT, h,
                cv2.CAP_PROP_FPS, fps_target
            ])
            cap = cv2.VideoCapture(cam_index, backend_id, params)
        else:
            cap = cv2.VideoCapture(cam_index, backend_id)
            if cap.isOpened():
                if codec_str != "None":
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*codec_str))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                cap.set(cv2.CAP_PROP_FPS, fps_target)
                
        if not cap or not cap.isOpened():
            ui_callback(" ❌ FEHLSCHLAG (Öffnet nicht)\n")
            if cap: cap.release()
            return "FEHLSCHLAG", 0.0, 0, 0, 0, "N/A"
            
        ret, _ = cap.read()
        if not ret:
            ui_callback(" ❌ FEHLSCHLAG (Kein Bild)\n")
            cap.release()
            return "FEHLSCHLAG", 0.0, 0, 0, 0, "N/A"
            
        t_init = time.perf_counter() - t0
        
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        actual_fcc = decode_fourcc(cap.get(cv2.CAP_PROP_FOURCC))
        
        frames = 0
        t_start_measure = time.perf_counter()
        while (time.perf_counter() - t_start_measure) < TEST_DURATION:
            ret, _ = cap.read()
            if ret:
                frames += 1
                
        t_end = time.perf_counter() - t_start_measure
        real_fps = frames / t_end if t_end > 0 else 0
        
        # Toleriere leichte Abweichungen beim FPS (z.B. 29.97 statt 30)
        status = "✅ OK" if real_fps > (fps_target * 0.8) else "⚠️ LANGSAM"
        ui_callback(f" {status} (Init: {t_init:.2f}s | Soll/Ist-FPS: {fps_target}/{real_fps:.1f} | Treffer-Res: {actual_w}x{actual_h} | Codec: {actual_fcc})\n")
        
        cap.release()
        return status, t_init, real_fps, actual_w, actual_h, actual_fcc

    except Exception as e:
        ui_callback(f" ❌ CRASH: {e}\n")
        if cap: cap.release()
        return "CRASH", 0.0, 0.0, 0, 0, "N/A"


class KameraTestApp:
    def __init__(self, master, labor_app=None):
        self.master = master
        self.labor_app = labor_app
        self.win = tk.Toplevel(master)
        self.win.title("ELP Kamera-Härtetest")
        
        # ---> NEU: Dynamische DPI-Skalierung für Windows (z.B. 200%) <---
        sf = master.winfo_fpixels('1i') / 96.0
        w, h = int(950 * sf), int(750 * sf)
        self.win.geometry(f"{w}x{h}")
        
        self.win.transient(master)
        self.win.attributes('-topmost', True)
        self.win.focus_force()
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.results = []
        self.best_result = None
        self.is_running = False
        
        self.preview_cap = None
        self.is_previewing = False
        self.preview_win = None
        self.preview_lbl = None
        self.preview_tk_img = None
        
        # UI Setup - Zweizeilig oder mit genug Platz, damit nichts verzerrt!
        ctrl_frame = tk.Frame(self.win, padx=10, pady=10)
        ctrl_frame.pack(fill=tk.X)
        
        tk.Label(ctrl_frame, text="Kamera-ID:", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.cam_id_var = tk.StringVar(value="0")
        self.entry_cam_id = tk.Entry(ctrl_frame, textvariable=self.cam_id_var, width=5, justify="center", font=("Arial", 10))
        self.entry_cam_id.pack(side=tk.LEFT, padx=8)
        
        self.btn_preview = tk.Button(ctrl_frame, text="👁️ Vorschau", bg="#3498db", fg="white", font=("Arial", 10, "bold"), command=self.toggle_preview)
        self.btn_preview.pack(side=tk.LEFT, padx=(0, 8))
        
        self.btn_start = tk.Button(ctrl_frame, text="🚀 Test Starten", bg="#8e44ad", fg="white", font=("Arial", 10, "bold"), command=self.start_test)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))
        
        self.btn_apply = tk.Button(ctrl_frame, text="💡 Bestes Setup übernehmen", bg="#27ae60", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, command=self.apply_recommendation)
        self.btn_apply.pack(side=tk.RIGHT, padx=(8, 0))
        
        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(ctrl_frame, variable=self.progress_var, maximum=100)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        # Log Output
        log_frame = tk.Frame(self.win, padx=10, pady=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(log_frame, bg="#1e1e1e", fg="#00ff00", font=("Consolas", int(10 * sf)))
        scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_text.insert(tk.END, "Bereit. Bitte Kamera-ID wählen und '👁️ Vorschau' oder '🚀 Test Starten' klicken.\n")
        
    def on_close(self):
        if self.is_previewing:
            self.stop_preview()
        self.win.destroy()

    def _ui_log(self, text, end="\n"):
        if not self.win.winfo_exists():
            return
        self.log_text.insert(tk.END, text + (end if end == "\n" else ""))
        self.log_text.see(tk.END)
        self.win.update_idletasks()
        
    def stop_preview(self):
        self.is_previewing = False
        if self.btn_preview.winfo_exists():
            self.btn_preview.config(text="👁️ Vorschau", bg="#3498db", state=tk.NORMAL)
        if self.preview_cap is not None:
            try:
                self.preview_cap.release()
            except Exception:
                pass
            self.preview_cap = None
        if self.preview_win is not None and self.preview_win.winfo_exists():
            try:
                self.preview_win.destroy()
            except Exception:
                pass
        self.preview_win = None
        self.preview_lbl = None

    def toggle_preview(self):
        if self.is_previewing:
            self.stop_preview()
            self._ui_log("⏹️ Vorschau beendet.\n")
        else:
            try:
                cam_index = int(self.cam_id_var.get().strip())
            except ValueError:
                messagebox.showerror("Fehler", "Bitte eine gültige Zahl für die Kamera-ID eingeben!", parent=self.win)
                return
                
            self.btn_preview.config(text="⏳ Suche...", state=tk.DISABLED)
            self._ui_log(f"🔎 Suche funktionierenden Stream für Kamera-ID {cam_index} (prüfe Backends)...")
            
            # Kamera-Init in Hintergrund-Thread, mit echten Lese-Tests (ret, frame = cap.read())!
            threading.Thread(target=self._async_open_preview, args=(cam_index,), daemon=True).start()

    def _async_open_preview(self, cam_index):
        # -------------------------------------------------------------------------
        # ROBUSTE FALLBACK-KETTE FÜR DIE VORSCHAU:
        # Manche Kameras (wie ChibiOrus) liefern bei DSHOW zwar isOpened()==True,
        # aber kein echtes Bild oder extrem langsames YUY2, oder schlagen bei DSHOW
        # fehl und brauchen MSMF. Deshalb prüfen wir ECHTES Frame-Lesen!
        # -------------------------------------------------------------------------
        candidates = [
            ("DSHOW (MJPG)", cv2.CAP_DSHOW, "MJPG"),
            ("DSHOW (Standard)", cv2.CAP_DSHOW, None),
            ("MSMF (Standard)", cv2.CAP_MSMF, None),
            ("AUTO (Standard)", cv2.CAP_ANY, None),
        ]
        
        working_cap = None
        used_name = ""
        first_frame = None
        
        for name, backend, fourcc in candidates:
            cap = None
            try:
                if fourcc:
                    params = [
                        cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc),
                        cv2.CAP_PROP_FRAME_WIDTH, 1280,
                        cv2.CAP_PROP_FRAME_HEIGHT, 720,
                        cv2.CAP_PROP_FPS, 30
                    ]
                    cap = cv2.VideoCapture(cam_index, backend, params)
                else:
                    cap = cv2.VideoCapture(cam_index, backend)
                    
                if cap is not None and cap.isOpened():
                    # Entscheidend: Wirklich testen, ob ein gültiges Bild kommt!
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        working_cap = cap
                        used_name = name
                        first_frame = frame
                        break
                if cap is not None:
                    cap.release()
            except Exception:
                if cap is not None:
                    try: cap.release()
                    except Exception: pass

        if working_cap is None:
            self.win.after(0, lambda: self._preview_failed(cam_index))
        else:
            self.preview_cap = working_cap
            self.win.after(0, lambda: self._preview_success(cam_index, used_name, first_frame))
            
    def _preview_failed(self, cam_index):
        if not self.win.winfo_exists():
            return
        self._ui_log(f"❌ Vorschau fehlgeschlagen: Kamera-ID {cam_index} liefert auf keinem Backend ein Bild.\n")
        messagebox.showerror(
            "Fehler", 
            f"Kamera {cam_index} konnte auf keinem Backend (DSHOW / MSMF) geöffnet werden\n"
            "oder liefert kein Bild.\n\n"
            "(Tipp: Prüfe die Kamera-ID oder ob die Kamera noch im Hauptprogramm blockiert ist.)", 
            parent=self.win
        )
        self.btn_preview.config(text="👁️ Vorschau", bg="#3498db", state=tk.NORMAL)

    def _preview_success(self, cam_index, used_name, first_frame):
        if not self.win.winfo_exists():
            if self.preview_cap:
                self.preview_cap.release()
            return
            
        h, w = first_frame.shape[:2]
        self._ui_log(f"✅ Vorschau aktiv über [{used_name}] ({w}x{h}).\n")
        
        self.is_previewing = True
        self.btn_preview.config(text="⏹️ Vorschau stoppen", bg="#e74c3c", state=tk.NORMAL)
        
        # ---> NEU: DPI-Skalierung für das Vorschaufenster <---
        sf = self.win.winfo_fpixels('1i') / 96.0
        pw, ph = int(660 * sf), int(400 * sf)
        
        self.preview_win = tk.Toplevel(self.win)
        self.preview_win.title(f"👁️ Kamera-Vorschau (ID {cam_index} - {used_name})")
        self.preview_win.geometry(f"{pw}x{ph}")
        self.preview_win.attributes('-topmost', True)
        self.preview_win.protocol("WM_DELETE_WINDOW", self.stop_preview)
        
        self.preview_lbl = tk.Label(self.preview_win, bg="#111111")
        self.preview_lbl.pack(fill=tk.BOTH, expand=True)
        
        self._display_preview_frame(first_frame)
        self.win.after(30, self._update_preview)

    def _display_preview_frame(self, frame):
        if not self.preview_lbl or not self.preview_lbl.winfo_exists():
            return
        # Auf handliche Vorschaugröße skalieren (640x360), damit das Fenster immer knackig passt
        disp = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
        self.preview_tk_img = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.preview_lbl.config(image=self.preview_tk_img)

    def _update_preview(self):
        if not self.is_previewing: 
            return
            
        if self.preview_win is None or not self.preview_win.winfo_exists():
            self.stop_preview()
            return

        if self.preview_cap is not None:
            ret, frame = self.preview_cap.read()
            if ret and frame is not None:
                self._display_preview_frame(frame)
        
        if self.is_previewing and self.win.winfo_exists():
            self.win.after(33, self._update_preview)

    def start_test(self):
        if getattr(self, 'is_previewing', False):
            self._ui_log("⏹️ Schließe Vorschau automatisch für den Härtetest...")
            self.stop_preview()
            self.win.update_idletasks()
            time.sleep(0.5) # OpenCV Zeit geben, den Kamera-Handle im Treiber sauber freizugeben!

        if self.is_running: return
        try:
            cam_index = int(self.cam_id_var.get().strip())
        except ValueError:
            messagebox.showerror("Fehler", "Bitte eine gültige Zahl für die Kamera-ID eingeben!", parent=self.win)
            return
            
        self.is_running = True
        self.btn_start.config(state=tk.DISABLED)
        self.btn_preview.config(state=tk.DISABLED)
        self.btn_apply.config(state=tk.DISABLED)
        self.entry_cam_id.config(state=tk.DISABLED)
        
        self.log_text.delete(1.0, tk.END)
        self._ui_log("=" * 90)
        self._ui_log(f"🚀 ELP-KAMERA VOLLSTÄNDIGER HÄRTETEST (Kamera-ID: {cam_index})")
        self._ui_log("=" * 90)
        
        # In Thread auslagern, damit GUI nicht blockiert
        threading.Thread(target=self._run_test_suite, args=(cam_index,), daemon=True).start()
        
    def _run_test_suite(self, cam_index):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        save_folder = os.path.abspath(os.path.join(base_dir, '..', 'savegames'))
        os.makedirs(save_folder, exist_ok=True)
        file_path = os.path.join(save_folder, "KameraTestErgebnisse_Vollstaendig.txt")

        header = f"{'Backend':<7} | {'Init':<8} | {'Req Res':<9} | {'Req FPS':<7} | {'Codec':<6} | {'Act Res':<9} | {'Real FPS':<8} | {'Act Codec':<9} | {'Init Zeit':<9} | {'Status'}"
        separator = "-" * len(header)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"=== ELP KAMERA VOLLTEST (ID {cam_index}) - {datetime.now()} ===\n{header}\n{separator}\n")

        self.results = []
        total_tests = len(BACKENDS) * len(INIT_MODES) * len(RESOLUTIONS) * len(CODECS) * len(FPS_TARGETS)
        current_test = 0

        for backend_name, backend_id in BACKENDS:
            for init_mode in INIT_MODES:
                for w, h in RESOLUTIONS:
                    for codec in CODECS:
                        for fps in FPS_TARGETS:
                            res = run_test_iteration(cam_index, backend_name, backend_id, init_mode, w, h, fps, codec, self._ui_log)
                            status, t_init, real_fps, act_w, act_h, act_fcc = res
                            
                            self.results.append({
                                'backend': backend_name,
                                'init_mode': init_mode,
                                'req_w': w, 'req_h': h,
                                'req_fps': fps,
                                'req_codec': codec,
                                'real_fps': real_fps,
                                'act_w': act_w, 'act_h': act_h,
                                'act_fcc': act_fcc,
                                't_init': t_init,
                                'status': status
                            })
                            
                            line = f"{backend_name:<7} | {init_mode:<8} | {w}x{h:<5} | {fps:<7} | {codec:<6} | {act_w}x{act_h:<5} | {real_fps:<8.1f} | {act_fcc:<9} | {t_init:<8.2f}s | {status}"
                            
                            with open(file_path, "a", encoding="utf-8") as f:
                                f.write(line + "\n")
                                
                            current_test += 1
                            if self.win.winfo_exists():
                                self.win.after(0, lambda v=(current_test/total_tests)*100: self.progress_var.set(v))
                            time.sleep(0.3)
                            
        if self.win.winfo_exists():
            self.win.after(0, lambda fp=file_path: self._test_finished(fp))
        
    def _test_finished(self, file_path):
        self._ui_log("\n" + "=" * 90)
        self._ui_log(f"✅ Test vollständig abgeschlossen! Ergebnisse gespeichert unter:\n   {file_path}")
        self._ui_log("=" * 90)
        
        self.is_running = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_preview.config(state=tk.NORMAL)
        self.entry_cam_id.config(state=tk.NORMAL)
        
        # Finde bestes Setup
        valid_results = [r for r in self.results if '✅ OK' in r['status']]
        if valid_results:
            # Sortiere nach:
            # 1. Echte FPS (auf 5 FPS gerundet, damit 29.8 FPS mit 1s Init gegen 30.0 FPS mit 15s Init gewinnt!)
            # 2. Auflösung (höchste zuerst)
            # 3. Kürzeste Init-Zeit (1.1s DSHOW schlägt 15s MSMF haushoch!)
            valid_results.sort(key=lambda x: (round(x['real_fps'] / 5.0), x['act_w']*x['act_h'], -x['t_init']), reverse=True)
            self.best_result = valid_results[0]
            
            self._ui_log("\n🏆 BESTES SETUP GEFUNDEN:")
            self._ui_log(f"Backend: {self.best_result['backend']} | Init: {self.best_result['init_mode']} | Codec: {self.best_result['req_codec']}")
            self._ui_log(f"Auflösung: {self.best_result['act_w']}x{self.best_result['act_h']} | Echte FPS: {self.best_result['real_fps']:.1f} | Startzeit: {self.best_result['t_init']:.2f}s")
            self.btn_apply.config(state=tk.NORMAL)
        else:
            self._ui_log("\n⚠️ Kein Setup hat den Test mit >80% Soll-FPS bestanden (Status OK).")
            self.best_result = None

    def apply_recommendation(self):
        if not self.best_result or not self.labor_app: return
        
        d_config = getattr(self.labor_app, 'package_data', {}).get('config')
        if not d_config:
            messagebox.showerror("Fehler", "Keine Config im Labor geladen!", parent=self.win)
            return
            
        if not d_config.has_section('Kameras'):
            d_config.add_section('Kameras')
            
        backend_val = self.best_result['backend']
        codec_val = self.best_result['req_codec'] if self.best_result['req_codec'] != "None" else "NONE"
        init_mode_val = "PRE" if self.best_result['init_mode'] == "Pre-Set" else "POST"
        fps_val = str(self.best_result['req_fps'])
        
        # Kamera Parameter
        d_config.set('Kameras', 'kamera_backend', backend_val)
        d_config.set('Kameras', 'kamera_codec', codec_val)
        d_config.set('Kameras', 'kamera_init_modus', init_mode_val)
        
        # FPS Parameter
        if not d_config.has_section('Timing'): d_config.add_section('Timing')
        d_config.set('Timing', 'kamera_bildrate', fps_val)
        
        self.labor_app.print_log("SYSTEM", f"💡 Kamera-Tuning angewendet! Neue Empfehlung übernommen:")
        self.labor_app.print_log("SYSTEM", f"   -> Backend: {backend_val} | Codec: {codec_val} | Init: {init_mode_val} | FPS: {fps_val}")
        self.labor_app.print_log("SYSTEM", f"⚠️ WICHTIG: Klicke oben auf 'Einstellungen speichern', damit diese Werte dauerhaft übernommen werden!")
        
        self.labor_app.on_param_change()
        
        messagebox.showinfo(
            "Empfehlung übernommen", 
            f"Die optimalen Kamera-Einstellungen wurden in das aktuelle Labor übernommen:\n\n"
            f"• Backend: {backend_val}\n"
            f"• Init-Modus: {init_mode_val}\n"
            f"• Codec: {codec_val}\n"
            f"• Ziel-Kamerabildrate: {fps_val}\n\n"
            "WICHTIG:\nVergiss nicht, im Labor oben auf '✅ Einstellungen speichern' zu klicken, "
            "um die Änderungen dauerhaft in die config.ini zu schreiben!",
            parent=self.win
        )
        
        self.on_close()

def start_ui(master, labor_app=None):
    KameraTestApp(master, labor_app)

if __name__ == "__main__":
    print("=" * 80)
    print(" 🛠️ HINWEIS: Dieses Tool ist ein Plugin für das TargetVision Labor.")
    print(" Bitte starte es direkt aus dem laufenden Labor über:")
    print(" -> '⚙️ Werkzeuge' -> '🎥 Kamera-Härtetest'")
    print("=" * 80)
    time.sleep(6)
