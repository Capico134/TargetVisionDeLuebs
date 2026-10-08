import tkinter as tk
from tkinter import ttk, messagebox
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
        self.hide_id = self.widget.after(200, self.hide)
        
    def cancel_hide(self):
        if self.hide_id:
            self.widget.after_cancel(self.hide_id)
            self.hide_id = None
            
    def show(self):
        if self.tip_window or not self.text: return
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 45
        y += self.widget.winfo_rooty() + 30
        
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.attributes('-topmost', True) 
        tw.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("Arial", 10), wraplength=350, padx=5, pady=5)
        label.pack()
        
        tw.bind("<Enter>", self.enter_tooltip)
        tw.bind("<Leave>", self.leave_tooltip)
        label.bind("<Enter>", self.enter_tooltip)
        label.bind("<Leave>", self.leave_tooltip)
        
    def hide(self):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


# ==========================================
# DER UI-BAUMEISTER
# ==========================================
class LaborUIBuilder:
    def __init__(self, app):
        """Der Baumeister erhält Zugriff auf das Zentralhirn (app)"""
        self.app = app

    def make_slider(self, parent, label_text, tk_var, from_, to_, res=1, section="Erkennung", key=None, odd_only=False, tooltip_key=None):
        """Hilfsfunktion für Slider mit direkter Eingabe, Reset und Live-Data-Binding"""
        if key:
            self.app.registered_sliders[key] = tk_var  
            
        if odd_only:
            tk_var._last_val = tk_var.get() 
            
        frame = tk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)
        
        lbl = tk.Label(frame, text=label_text, width=25, anchor="w")
        lbl.pack(side=tk.LEFT)
        
        t_key = tooltip_key if tooltip_key else key
        if t_key and t_key in PARAMETER_LEXIKON:
            ToolTip(lbl, PARAMETER_LEXIKON[t_key])
        
        is_float = isinstance(tk_var, tk.DoubleVar)
        vcmd = self.app.vcmd_float if is_float else self.app.vcmd_int
        
        entry = tk.Entry(frame, width=8, justify="right", validate="key", validatecommand=vcmd)
        entry.pack(side=tk.RIGHT, padx=(5, 0))
        entry.insert(0, str(tk_var.get()))
        
        def scale_cmd(val_str):
            if getattr(scale, '_ignore_cmd', False):
                return
            try:
                v = int(float(val_str)) if isinstance(tk_var, tk.IntVar) else float(val_str)
                if odd_only and isinstance(tk_var, tk.IntVar):
                    if v > 0 and v % 2 == 0:
                        last = getattr(tk_var, '_last_val', v)
                        v = v - 1 if v < last else v + 1
                    scale._ignore_cmd = True
                    scale.set(v)
                    scale._ignore_cmd = False
                    
                if tk_var.get() != v:
                    tk_var.set(v)
                    if odd_only:
                        tk_var._last_val = v
                    self.app.on_param_change()
            except ValueError:
                pass

        scale = tk.Scale(frame, from_=from_, to_=to_, resolution=res, orient=tk.HORIZONTAL, command=scale_cmd, showvalue=0)
        scale._ignore_cmd = True
        scale.set(tk_var.get())
        scale._ignore_cmd = False
        scale.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        
        def apply_entry_val(event=None):
            try:
                val = int(float(entry.get())) if isinstance(tk_var, tk.IntVar) else float(entry.get())
                if odd_only and isinstance(tk_var, tk.IntVar):
                    #print(f"apply_entry_val: {val}")
                    if val > 0 and val % 2 == 0:
                        val += 1 
                if val != tk_var.get():
                    tk_var.set(val)
                    if odd_only:
                        tk_var._last_val = val
                    self.app.on_param_change(force=True)
            except ValueError:
                print("apply_entry_val ERROR")
                pass 
                
            entry.delete(0, tk.END)
            entry.insert(0, str(tk_var.get()))

            if event and hasattr(event, 'keysym') and event.keysym == 'Return':
                self.app.root.focus_set()

        entry.bind('<Return>', apply_entry_val)
        entry.bind('<FocusOut>', apply_entry_val)
        
        def sync_entry(*args):
            if self.app.root.focus_get() != entry:
                entry.delete(0, tk.END)
                entry.insert(0, str(tk_var.get()))
                
            scale._ignore_cmd = True
            scale.set(tk_var.get())
            scale._ignore_cmd = False
                
            var_key = str(tk_var)
            if hasattr(self.app, 'original_values') and var_key in self.app.original_values:
                if str(tk_var.get()) != str(self.app.original_values[var_key]):
                    lbl.config(fg="#e74c3c", font=("Segoe UI", 9, "bold"))
                    if not lbl.cget("text").startswith("*"):
                        lbl.config(text=f"* {label_text}")
                else:
                    lbl.config(fg="black", font=("Segoe UI", 9, "normal")) 
                    lbl.config(text=label_text)
                
        tk_var.trace_add("write", sync_entry)

        if key:
            def sync_to_config(*args):
                if getattr(self.app, 'package_data', None) and self.app.package_data.get('config'):
                    parser = self.app.package_data['config']
                    if not parser.has_section(section):
                        parser.add_section(section)
                    parser.set(section, key, str(tk_var.get()))
            tk_var.trace_add("write", sync_to_config)

        def reset_to_original(event):
            self.app.root.focus_set()
            var_key = str(tk_var)
            if hasattr(self.app, 'original_values') and var_key in self.app.original_values:
                tk_var.set(self.app.original_values[var_key])
                if odd_only:
                    tk_var._last_val = tk_var.get()
                self.app.on_param_change(force=True)
            return "break" 
                
        scale.bind('<Button-2>', reset_to_original)
        lbl.bind('<Button-2>', reset_to_original)
        entry.bind('<Button-2>', reset_to_original)

    def setup_ui(self):
        # TOP FRAME
        top_frame = tk.Frame(self.app.root, pady=10, padx=10)
        top_frame.pack(fill=tk.X)
        
        tk.Button(top_frame, text="📦 ZIP-Paket laden", command=self.app.load_zip, font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        
        self.app.color_picker_active = False
        self.app.btn_pick_color = tk.Button(top_frame, text="🎨 Farbe picken", command=self.app.toggle_color_picker, bg="#f39c12", fg="white", font=("Arial", 10, "bold"))
        self.app.btn_pick_color.pack(side=tk.LEFT, padx=(20, 0))
        
        self.app.calib_mode_active = False
        self.app.calib_points = []
        self.app.btn_calib_assist = tk.Button(top_frame, text="📏 Kalibrierung", command=self.app.start_calibration_assist, bg="#8e44ad", fg="white", font=("Arial", 10, "bold"))
        self.app.btn_calib_assist.pack(side=tk.LEFT, padx=(20, 0))
        
        self.app.btn_compare = tk.Button(top_frame, text="📊 Abweichungen", command=self.app.show_comparison, font=("Arial", 10, "bold"))
        self.app.btn_compare.pack(side=tk.LEFT, padx=20)        
        
        btn_export = tk.Button(top_frame, text="💾 Test-Case-Export", command=self.app.export_test_case)
        btn_export.pack(side=tk.LEFT, pady=5, padx=(0, 20))
        
        btn_einstellungen = tk.Button(top_frame, text="⚙️ Erweiterte Einstellungen", command=self.open_all_settings_dialog, bg="#34495e", fg="white")
        btn_einstellungen.pack(side=tk.LEFT, pady=5, padx=(0, 20))
        
        self.app.btn_apply = tk.Button(top_frame, text="✅ Einstellungen speichern", 
                                   command=self.app.apply_to_live, bg="#27ae60", fg="white", font=("Arial", 10, "bold"))
        self.app.btn_apply.pack(side=tk.LEFT, pady=5)
        
        self.app.lbl_coords = tk.Label(top_frame, text="Maus nicht im Bild", font=("Consolas", 12, "bold"), fg="#3498db")
        self.app.lbl_coords.pack(side=tk.RIGHT, padx=15)
        
        # MAIN FRAME
        main_frame = tk.Frame(self.app.root, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        self.app.image_frame = tk.LabelFrame(main_frame, text=" Zoom: 1.0x  |  Rad: Zoom  |  L-Klick: Bewegen  |  R-Klick: Reset  |  M-Klick: Zentrieren  |  Strg+Ziehen: Rahmen  |  Warte auf ZIP... ", bg="#222222", fg="white")
        self.app.image_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        self.app.paned_window = tk.PanedWindow(self.app.image_frame, orient=tk.VERTICAL, sashwidth=9, sashrelief=tk.RAISED, bg="#555555")
        self.app.paned_window.pack(fill=tk.BOTH, expand=True)

        self.app.img_container = tk.Frame(self.app.paned_window, bg="#222222")
        
        self.app.lbl_image = tk.Label(self.app.img_container, text="Warte auf ZIP-Datei...", bg="#222222", fg="gray", font=("Arial", 14))
        self.app.lbl_image.place(x=0, y=0, anchor=tk.NW)
        
        self.app.lbl_image.bind('<Motion>', self.app.on_mouse_move)
        self.app.lbl_image.bind('<Leave>', self.app.on_mouse_leave)
        self.app.lbl_image.bind('<MouseWheel>', self.app.on_mouse_scroll)
        self.app.lbl_image.bind('<Button-4>', self.app.on_mouse_scroll)
        self.app.lbl_image.bind('<Button-5>', self.app.on_mouse_scroll)
        
        # Standard Drag & Drop (Verschieben)
        self.app.lbl_image.bind('<ButtonPress-1>', self.app.on_drag_start)
        self.app.lbl_image.bind('<B1-Motion>', self.app.on_drag_motion)
        self.app.lbl_image.bind('<ButtonRelease-1>', self.app.on_drag_stop)
        
        # ---> DER FIX: Wir zwingen Tkinter, beim Box-Zoom NUR die speziellen Funktionen aufzurufen 
        # und ignorieren die normalen Motion-Events komplett! <---
        self.app.lbl_image.bind('<Control-ButtonPress-1>', self.app.on_zoom_box_start)
        self.app.lbl_image.bind('<Shift-ButtonPress-1>', self.app.on_zoom_box_start)
        self.app.lbl_image.bind('<Control-B1-Motion>', self.app.on_zoom_box_motion)
        self.app.lbl_image.bind('<Shift-B1-Motion>', self.app.on_zoom_box_motion)
        self.app.lbl_image.bind('<Control-ButtonRelease-1>', self.app.on_zoom_box_stop)
        self.app.lbl_image.bind('<Shift-ButtonRelease-1>', self.app.on_zoom_box_stop)
        
        self.app.lbl_image.bind('<Button-3>', self.app.reset_view)
        self.app.lbl_image.bind('<Button-2>', self.app.center_on_last_shot)
        
        self.app.log_text = tk.Text(self.app.paned_window, height=12, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        # =====================================================================
        # ---> DER FIX: Monospace-Schriftart erzwingen (für saubere Tabellen) <---
        # =====================================================================
        # Fallback auf Courier, falls Consolas auf dem System nicht existiert
        self.app.log_text.configure(font=("Consolas", 10, "normal"))
        # Ein Tag definieren, das wir für alles verwenden, um sicherzugehen
        self.app.log_text.tag_configure("mono", font=("Consolas", 10, "normal"))
        
        # =====================================================================
        # ---> NEU: STRG+A zum schnellen Markieren des gesamten Logs <---
        # =====================================================================
        def select_all_log(event):
            event.widget.tag_add(tk.SEL, "1.0", tk.END)
            event.widget.mark_set(tk.INSERT, "1.0")
            event.widget.see(tk.INSERT)
            return "break" # Blockiert das sture Standard-Verhalten von Tkinter
        self.app.log_text.bind("<Control-a>", select_all_log)
        self.app.log_text.bind("<Control-A>", select_all_log)
        self.app.paned_window.add(self.app.img_container, stretch="always")
        self.app.paned_window.add(self.app.log_text, stretch="never")
        
        # RECHTS: Steuerpult
        control_frame = tk.Frame(main_frame, width=400)
        control_frame.pack(side=tk.RIGHT, fill=tk.Y)
        
        # ==========================================================
        # ---> DER KAMERA-UMSCHALTER <---
        # ==========================================================
        cam_frame = tk.LabelFrame(control_frame, text=" Aktive Kamera ", pady=5, padx=5)
        cam_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.app.active_camera_var = tk.StringVar(value="left") # <--- HIER WAR DER FEHLER
        
        self.app.rb_cam_left = tk.Radiobutton(cam_frame, text="Kamera Links", variable=self.app.active_camera_var, value="left", command=self.app.switch_camera)
        self.app.rb_cam_left.pack(side=tk.LEFT, expand=True)
        
        self.app.rb_cam_right = tk.Radiobutton(cam_frame, text="Kamera Rechts", variable=self.app.active_camera_var, value="right", command=self.app.switch_camera)
        self.app.rb_cam_right.pack(side=tk.LEFT, expand=True)
        
        nav_frame = tk.LabelFrame(control_frame, text=" Bild-Navigation ", pady=10, padx=10)
        nav_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.app.btn_first = tk.Button(nav_frame, text="<<", state=tk.DISABLED, command=self.app.first_shot, width=3)
        self.app.btn_first.pack(side=tk.LEFT, padx=(0, 2))
        self.app.btn_prev = tk.Button(nav_frame, text="◀ Zurück", state=tk.DISABLED, command=self.app.prev_shot, width=8)
        self.app.btn_prev.pack(side=tk.LEFT)
        
        self.app.shot_nav_frame = tk.Frame(nav_frame)
        self.app.shot_nav_frame.pack(side=tk.LEFT, expand=True)
        tk.Label(self.app.shot_nav_frame, text="Bild ", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        
        self.app.shot_jump_var = tk.StringVar(value="-") # <--- DIESE ZEILE EINFÜGEN!
        
        self.app.entry_shot_jump = tk.Entry(self.app.shot_nav_frame, textvariable=self.app.shot_jump_var, width=4, font=("Arial", 10, "bold"), justify="center")
        self.app.entry_shot_jump.pack(side=tk.LEFT)
        self.app.entry_shot_jump.bind('<Return>', self.app.jump_to_shot)
        self.app.lbl_shot_total = tk.Label(self.app.shot_nav_frame, text=" / -", font=("Arial", 10, "bold"))
        self.app.lbl_shot_total.pack(side=tk.LEFT)
        
        self.app.btn_last = tk.Button(nav_frame, text=">>", state=tk.DISABLED, command=self.app.last_shot, width=3)
        self.app.btn_last.pack(side=tk.RIGHT, padx=(2, 0))
        self.app.btn_next = tk.Button(nav_frame, text="Weiter ▶", state=tk.DISABLED, command=self.app.next_shot, width=8)
        self.app.btn_next.pack(side=tk.RIGHT)
        
        view_outer_frame = tk.Frame(control_frame)
        view_outer_frame.pack(fill=tk.X, pady=(0, 15))
        
        view_frame = tk.LabelFrame(view_outer_frame, text=" Rechte Bildhälfte ", pady=10, padx=10)
        view_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        tk.Radiobutton(view_frame, text="1) Diff-Bild", variable=self.app.view_mode_var, value=1, command=self.app.renderer.update_image_display).pack(anchor=tk.W)
        tk.Radiobutton(view_frame, text="2) Diff-Gesamt", variable=self.app.view_mode_var, value=2, command=self.app.renderer.update_image_display).pack(anchor=tk.W)
        tk.Radiobutton(view_frame, text="3) Überlagerung", variable=self.app.view_mode_var, value=3, command=self.app.renderer.update_image_display).pack(anchor=tk.W)
        tk.Radiobutton(view_frame, text="4) Raw-Diff", variable=self.app.view_mode_var, value=4, command=self.app.renderer.update_image_display).pack(anchor=tk.W)
        tk.Radiobutton(view_frame, text="5) Rohes Bild", variable=self.app.view_mode_var, value=5, command=self.app.renderer.update_image_display).pack(anchor=tk.W)

        self.app.score_frame = tk.LabelFrame(view_outer_frame, text=" Ringwertung (Live) ", pady=10, padx=10)
        self.app.score_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        self.app.lbl_current_scores = tk.Label(self.app.score_frame, text="-", justify=tk.LEFT, anchor="nw", font=("Consolas", 12, "bold"), fg="#27ae60")
        self.app.lbl_current_scores.pack(fill=tk.BOTH, expand=True)
        
        param_outer_frame = tk.LabelFrame(control_frame, text=" Erkennungs-Parameter (Live) ", pady=5, padx=5)
        param_outer_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(param_outer_frame, borderwidth=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(param_outer_frame, orient="vertical", command=canvas.yview)
        param_frame = tk.Frame(canvas)
        
        param_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=param_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.app.calib_outer_frame = tk.LabelFrame(param_frame, text=" Kalibrierung: Kamera Links ", pady=5, padx=5, fg="#2980b9", font=("Arial", 10, "bold"))
        self.app.calib_outer_frame.pack(fill=tk.X, pady=(5, 10))
        
        # ---> HIER HABEN DIE DREI VARIABLEN GEFEHLT <---
        self.app.calib_x_var = tk.DoubleVar(value=5.0)
        self.app.calib_y_var = tk.DoubleVar(value=5.0)
        self.app.calib_fischauge_var = tk.DoubleVar(value=0.0)
        
        self.make_slider(self.app.calib_outer_frame, "Pixel pro mm (X):", self.app.calib_x_var, 1.0, 15.0, 0.001, key=None, tooltip_key="px_pro_mm")
        self.make_slider(self.app.calib_outer_frame, "Pixel pro mm (Y):", self.app.calib_y_var, 1.0, 15.0, 0.001, key=None, tooltip_key="px_pro_mm")
        self.make_slider(self.app.calib_outer_frame, "Fischaugen-Korr.:", self.app.calib_fischauge_var, -0.01, 0.01, 0.00001, key=None, tooltip_key="fischaugenkorrektur")

        def sync_calib_config(*args):
            if getattr(self.app, 'package_data', None) and self.app.package_data.get('config'):
                parser = self.app.package_data['config']
                side = self.app.active_camera_var.get()
                seite_str = "links" if side == 'left' else "rechts"
                
                if not parser.has_section('Kameras'): parser.add_section('Kameras')
                
                parser.set('Kameras', f'px_pro_mm_x_{seite_str}', str(self.app.calib_x_var.get()))
                parser.set('Kameras', f'px_pro_mm_y_{seite_str}', str(self.app.calib_y_var.get()))
                parser.set('Kameras', f'fischaugenkorrektur_{seite_str}', str(self.app.calib_fischauge_var.get()))
                
                self.app.on_param_change()
                
        self.app.calib_x_var.trace_add("write", sync_calib_config)
        self.app.calib_y_var.trace_add("write", sync_calib_config)
        self.app.calib_fischauge_var.trace_add("write", sync_calib_config)
        
        tk.Label(param_frame, text="--- Engine Parameter ---", fg="#3498db").pack(pady=(5, 5))
        
        self.make_slider(param_frame, "hit_tolerance:", self.app.hit_tolerance_var, 1, 100, key="hit_tolerance")
        self.make_slider(param_frame, "min_hole_area:", self.app.min_hole_area_var, 5, 500, key="min_hole_area")
        self.make_slider(param_frame, "caliber_durchmesser (mm):", self.app.caliber_durchmesser_var, 3.00, 10.00, res=0.01, key="caliber_durchmesser")
        tk.Label(param_frame, text="--- Hybrid & Hough Faktoren ---", fg="#3498db").pack(pady=(10, 5))
        self.make_slider(param_frame, "discard_big_hits:", self.app.discard_big_hits_var, 1.5, 5.0, 0.1, key="discard_big_hits")
        self.make_slider(param_frame, "grenzwert_hough:", self.app.grenzwert_hough_var, 0.0, 20.0, 0.5, key="grenzwert_hough") 
        self.make_slider(param_frame, "hough_min_faktor:", self.app.hough_min_faktor_var, 0.5, 1.0, 0.01, key="hough_min_faktor")
        self.make_slider(param_frame, "hough_max_faktor:", self.app.hough_max_faktor_var, 1.0, 2.0, 0.01, key="hough_max_faktor")
        self.make_slider(param_frame, "hough_param1 (Kanten):", self.app.hough_param1_var, 10, 100, key="hough_param1")
        self.make_slider(param_frame, "hough_param2 (Strenge):", self.app.hough_param2_var, 1, 20, key="hough_param2")
        tk.Label(param_frame, text="--- Bild-Filterung ---", fg="#3498db").pack(pady=(10, 5))
        self.make_slider(param_frame, "blur_kernel_size:", self.app.blur_kernel_size_var, 1, 31, key="blur_kernel_size", odd_only=True)
        self.make_slider(param_frame, "randaufschlag_cumulative:", self.app.randaufschlag_cumulative_var, 0, 10, key="randaufschlag_cumulative")
        self.make_slider(param_frame, "morph_kernel_size:", self.app.morph_kernel_var, 0, 15, key="morph_kernel_size", odd_only=True)
        self.make_slider(param_frame, "max_aspect_ratio (Sichel):", self.app.max_aspect_ratio_var, 1.5, 6.0, 0.1, key="max_aspect_ratio")
        tk.Label(param_frame, text="--- Score-Gewichtung ---", fg="#3498db").pack(pady=(10, 5))
        self.make_slider(param_frame, "gesamt_anteil (Raw):", self.app.gesamt_anteil_am_200score_var, 0.1, 0.9, 0.001, key="gesamt_anteil_am_200score")
        tk.Label(param_frame, text="--- Heuristik & Limits ---", fg="#3498db").pack(pady=(10, 5))
        self.make_slider(param_frame, "abriss_max_edge_percent:", self.app.abriss_max_edge_percent_var, 0.4, 1.5, 0.01, key="abriss_max_edge_percent")
        self.make_slider(param_frame, "abriss_base_bonus:", self.app.abriss_base_bonus_var, 0.0, 30.0, 0.5, key="abriss_base_bonus")
        self.make_slider(param_frame, "abriss_min_hebel (px):", self.app.abriss_min_hebel_var, 0.0, 10.0, 0.5, key="abriss_min_hebel") 
        self.make_slider(param_frame, "min_score_valid (Discard):", self.app.min_score_valid_var, 10.0, 150.0, 1.0, key="min_score_valid")
        tk.Label(param_frame, text="--- Anti-Doppelzählung ---", fg="#3498db").pack(pady=(10, 5))
        self.make_slider(param_frame, "clipping_factor_history:", self.app.clipping_factor_history_var, 0.05, 0.5, 0.01, key="clipping_factor_history")
        self.make_slider(param_frame, "clipping_factor_current:", self.app.clipping_factor_current_var, 0.5, 1.5, 0.01, key="clipping_factor_current")
        self.make_slider(param_frame, "max_treffer_je_frame:", self.app.max_treffer_je_frame_var, 0, 10, key="max_treffer_je_frame")
        tk.Label(param_frame, text="--- Anti-Weiß Filter (Farb-Bonus) ---", fg="#3498db").pack(pady=(10, 5))
        
        base_text_farb = "🟢 farb_bonus_aktiv"
        chk_farb = tk.Checkbutton(param_frame, text=base_text_farb, variable=self.app.farb_bonus_aktiv_var)
        chk_farb.pack(anchor=tk.W)
        self.app.registered_sliders["farb_bonus_aktiv"] = self.app.farb_bonus_aktiv_var
        
        if "farb_bonus_aktiv" in PARAMETER_LEXIKON:
            ToolTip(chk_farb, PARAMETER_LEXIKON["farb_bonus_aktiv"])
        
        def sync_farb_config(*args):
            if getattr(self.app, 'package_data', None) and self.app.package_data.get('config'):
                parser = self.app.package_data['config']
                if not parser.has_section('Erkennung'): parser.add_section('Erkennung')
                val_str = "yes" if self.app.farb_bonus_aktiv_var.get() else "no"
                parser.set('Erkennung', "farb_bonus_aktiv", val_str)
                self.app.on_param_change()
                
            var_key = str(self.app.farb_bonus_aktiv_var)
            if hasattr(self.app, 'original_values') and var_key in self.app.original_values:
                if self.app.farb_bonus_aktiv_var.get() != self.app.original_values[var_key]:
                    chk_farb.config(fg="#e74c3c", font=("Segoe UI", 9, "bold"), text=f"* {base_text_farb}")
                else:
                    chk_farb.config(fg="black", font=("Segoe UI", 9, "normal"), text=base_text_farb)
                    
        self.app.farb_bonus_aktiv_var.trace_add("write", sync_farb_config)

        def reset_farb_to_original(event):
            var_key = str(self.app.farb_bonus_aktiv_var)
            if hasattr(self.app, 'original_values') and var_key in self.app.original_values:
                self.app.farb_bonus_aktiv_var.set(self.app.original_values[var_key])
                self.app.on_param_change(force=True)
            return "break" 
            
        chk_farb.bind('<Button-2>', reset_farb_to_original)
        
        self.make_slider(param_frame, "farb_bonus_limit (Distanz):", self.app.farb_bonus_limit_var, 50.0, 750.0, 5.0, key="farb_bonus_limit")
        self.make_slider(param_frame, "farb_bonus_kurve (Exponent):", self.app.farb_bonus_kurve_var, 1.0, 5.0, 0.1, key="farb_bonus_kurve")
        
        tk.Checkbutton(param_frame, text="💾 Simulations-Bilder exportieren", 
                       variable=self.app.export_images_var, fg="#00aaff").pack(anchor=tk.W, pady=(15, 0))

        self.app.show_target_rings_var = tk.BooleanVar(value=False)
        tk.Checkbutton(param_frame, text="🎯 Zielscheibe (Ringe) einblenden", 
                       variable=self.app.show_target_rings_var, fg="#27ae60", 
                       command=lambda: self.app.on_param_change(force=True)).pack(anchor=tk.W, pady=(5, 0))

        def _on_mousewheel(event):
            if event.num == 4 or getattr(event, 'delta', 0) > 0:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5 or getattr(event, 'delta', 0) < 0:
                canvas.yview_scroll(1, "units")

        def _bind_scroll_recursive(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            widget.bind("<Button-4>", _on_mousewheel)
            widget.bind("<Button-5>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_scroll_recursive(child)

        _bind_scroll_recursive(canvas)
        _bind_scroll_recursive(param_frame)
        
        self.app.root.bind('<Left>', self.app.safe_prev_shot)
        self.app.root.bind('<Right>', self.app.safe_next_shot)
        # ---> NEU: Tasten-Bindings für das Battle Royale VAR <---
        self.app.root.bind('<Up>', lambda e: self.app.toggle_var_mode(1))#, e))
        self.app.root.bind('<Down>', lambda e: self.app.toggle_var_mode(-1))#, e))

        for key_char in ['w', 'a', 's', 'd', 'W', 'A', 'S', 'D']:
            self.app.root.bind(f'<{key_char}>', self.app.nudge_center)
    
        self.app.show_orig_hits_var = tk.BooleanVar(value=False)
        tk.Checkbutton(param_frame, text="🟡 Original-Treffer (match.json) einblenden", 
                       variable=self.app.show_orig_hits_var, fg="#f1c40f", 
                       command=lambda: self.app.on_param_change(force=True)).pack(anchor=tk.W, pady=(5, 0))

        def release_focus(event):
            try:
                valid_classes = ('Entry', 'TCombobox', 'Text', 'Listbox', 'Scrollbar', 'TScrollbar')
                if event.widget.winfo_class() not in valid_classes:
                    # ---> DER FIX: Wir ignorieren das Hauptbild! Es kümmert sich selbst um seinen Fokus, 
                    # damit die Drag-and-Drop / Zoom-Mechanik nicht abgewürgt wird. <---
                    if event.widget != self.app.lbl_image:
                        self.app.root.focus_set()
            except AttributeError:
                pass
        self.app.root.bind_all('<Button-1>', release_focus, add="+")

        # ---> DER FIX: Kombiniertes ESC-Binding <---
        def handle_escape(event):
            self.app.root.focus_set()
            self.app.abort_zoom_box(event)
            
            # ---> NEU: Beendet das Battle Royale Overlay <---
            if hasattr(self.app, 'clear_var_mode'):
                self.app.clear_var_mode()
                
            # ---> Bricht den Lila-Kreis sofort ab (falls man keine 5 Sek warten will) <---
            self.app.clear_highlight()
            
        self.app.root.bind_all('<Escape>', handle_escape, add="+")

    def open_all_settings_dialog(self):
        """Öffnet ein dynamisches Fenster mit allen ERWEITERTEN Werten aus der aktuellen config.ini."""
        if not getattr(self.app, 'package_data', None) or not self.app.package_data.get('config'):
            messagebox.showwarning("Fehler", "Es ist kein ZIP-Paket geladen!")
            return

        parser = self.app.package_data['config']

        ignore_keys = set(self.app.registered_sliders.keys())
        ignore_keys.add('caliber_radius') 
        ignore_keys.update([
            'px_pro_mm_x_links', 'px_pro_mm_y_links', 'fischaugenkorrektur_links',
            'px_pro_mm_x_rechts', 'px_pro_mm_y_rechts', 'fischaugenkorrektur_rechts'
        ])

        dialog = tk.Toplevel(self.app.root)
        dialog.title("Erweiterte Einstellungen (Live Data-Binding)")
        
        sf = self.app.root.winfo_fpixels('1i') / 96.0
        w, h = int(550 * sf), int(800 * sf)
        dialog.geometry(f"{w}x{h}")
        
        dialog.transient(self.app.root)  
        dialog.focus_force()         

        info_frame = tk.Frame(dialog, bg="#fff3cd", bd=1, relief=tk.SOLID)
        info_frame.pack(fill=tk.X, padx=10, pady=(10, 0))
        info_lbl = tk.Label(info_frame, 
                            text="⚠️ WICHTIGER HINWEIS:\nTiefe Systemeinstellungen (wie Kameras, Bild-Zuschnitte/Crops oder Vollbild)\nwerden erst nach einem Neustart von TargetVision aktiv.\nAlle Erkennungs-Parameter (Filter, Toleranzen) greifen sofort!",
                            bg="#fff3cd", fg="#856404", font=("Arial", 9), justify=tk.CENTER)
        info_lbl.pack(padx=5, pady=5)

        canvas = tk.Canvas(dialog, borderwidth=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        targets = list(self.app.dm.load_targets().keys()) if self.app.dm.load_targets() else ["Luftgewehr_10m"]

        for section in parser.sections():
            visible_keys = [k for k in parser.options(section) if k not in ignore_keys]
            if not visible_keys:
                continue 

            sec_frame = tk.LabelFrame(scrollable_frame, text=f" {section} ", font=("Arial", 11, "bold"), pady=8, padx=8)
            sec_frame.pack(fill=tk.X, pady=5, padx=10)

            for key, val in parser.items(section):
                if key in ignore_keys:
                    continue
                    
                val_str = str(val).strip()
                
                row = tk.Frame(sec_frame)
                row.pack(fill=tk.X, pady=2)
                
                lbl_key = tk.Label(row, text=key, width=32, anchor="w")
                lbl_key.pack(side=tk.LEFT)
                
                if key in PARAMETER_LEXIKON:
                    ToolTip(lbl_key, PARAMETER_LEXIKON[key])

                def make_trace_cmd(s, k, var_obj):
                    def cmd(*args):
                        try:
                            v = var_obj.get()
                        except tk.TclError:
                            return
                            
                        if isinstance(v, bool):
                            v_str = "yes" if v else "no"
                        else:
                            v_str = str(v)
                        
                        parser.set(s, k, v_str)
                        self.app.on_param_change() 
                    return cmd

                if key == 'aktive_scheibe':
                    var = tk.StringVar(value=val_str)
                    cb = ttk.Combobox(row, textvariable=var, values=targets, state="readonly", width=20)
                    cb.pack(side=tk.RIGHT)
                    cb.var_ref = var 
                    var.trace_add("write", make_trace_cmd(section, key, var))
                    
                    # =========================================================================
                    # ---> DER FIX: Scrollrad-Hijacking der Combobox verhindern! <---
                    # =========================================================================
                    def block_cb_scroll(event):
                        # 1. Wir leiten den Scroll-Befehl manuell an das Haupt-Canvas weiter
                        if event.num == 4 or getattr(event, 'delta', 0) > 0:
                            canvas.yview_scroll(-1, "units")
                        elif event.num == 5 or getattr(event, 'delta', 0) < 0:
                            canvas.yview_scroll(1, "units")
                        # 2. "break" blockiert die interne Werte-Änderung der Combobox
                        return "break" 
                        
                    cb.bind("<MouseWheel>", block_cb_scroll)
                    cb.bind("<Button-4>", block_cb_scroll) # Für Linux
                    cb.bind("<Button-5>", block_cb_scroll) # Für Linux

                elif val_str.lower() in ['yes', 'no', 'true', 'false', 'on', 'off']:
                    is_true = val_str.lower() in ['yes', 'true', 'on']
                    var = tk.BooleanVar(value=is_true)
                    chk = tk.Checkbutton(row, text="Aktiv", variable=var)
                    chk.pack(side=tk.RIGHT)
                    var.trace_add("write", make_trace_cmd(section, key, var))

                elif '.' in val_str and val_str.replace('.', '', 1).replace('-', '', 1).isdigit():
                    var = tk.DoubleVar(value=float(val_str))
                    entry = tk.Entry(row, textvariable=var, width=12, justify="right", validate="key", validatecommand=self.app.vcmd_float)
                    entry.pack(side=tk.RIGHT)
                    var.trace_add("write", make_trace_cmd(section, key, var))

                elif val_str.replace('-', '', 1).isdigit():
                    var = tk.IntVar(value=int(val_str))
                    entry = tk.Entry(row, textvariable=var, width=12, justify="right", validate="key", validatecommand=self.app.vcmd_int)
                    entry.pack(side=tk.RIGHT)
                    var.trace_add("write", make_trace_cmd(section, key, var))

                else:
                    var = tk.StringVar(value=val_str)
                    entry = tk.Entry(row, textvariable=var, width=22, justify="right")
                    entry.pack(side=tk.RIGHT)
                    var.trace_add("write", make_trace_cmd(section, key, var))

        def _on_mousewheel(event):
            if event.num == 4 or getattr(event, 'delta', 0) > 0:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5 or getattr(event, 'delta', 0) < 0:
                canvas.yview_scroll(1, "units")

        dialog.bind("<MouseWheel>", _on_mousewheel)
        dialog.bind("<Button-4>", _on_mousewheel)
        dialog.bind("<Button-5>", _on_mousewheel)