import tkinter as tk
from tkinter import filedialog, messagebox
import json
import math
import numpy as np
import os
from StateManagerDeLuebs import StateManager
from HelperDeLuebs import Helfer

class Kalibrator:
    def __init__(self, app):
        """Erhält das Zentralhirn (LaborApp) als Referenz"""
        self.app = app

    def start_calibration_assist(self):
        """Startet den Kalibrierungs-Assistenten ODER bricht ihn ab."""
        if not getattr(self.app, 'package_data', None):
            messagebox.showwarning("Fehler", "Bitte lade zuerst ein ZIP-Paket!")
            return
            
        if getattr(self.app, 'calib_mode_active', False):
            self.cancel_calibration()
            return
            
        # =========================================================================
        # ---> Der erweiterte JSON-Import für Klick-Koordinaten & Parameter! <---
        # =========================================================================
        load_existing = messagebox.askyesno("Klicks importieren", "Möchtest du eine gespeicherte 20-Punkte-Liste laden, um das manuelle Klicken zu überspringen?")
        if load_existing:
            filepath = filedialog.askopenfilename(title="Kalibrierung laden", filetypes=[("JSON", "*.json")])
            if filepath:
                try:
                    with open(filepath, "r") as f:
                        data = json.load(f)
                        
                    # Kompatibilität: Altes Array (16 Punkte) vs. neues Dictionary (20 Punkte + Params)
                    if isinstance(data, list):
                        pts = data
                        params = {}
                    else:
                        pts = data.get("points", [])
                        params = data.get("params", {})
                        
                    if len(pts) in [16, 20]:
                        # ---> NEU: Sicherheits-Prüfung der Zielscheibe! <---
                        d_config = self.app.package_data['config']
                        aktuelle_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Unbekannt')
                        gespeicherte_scheibe = params.get("zielscheibe", "Unbekannt")
                        
                        if gespeicherte_scheibe != "Unbekannt" and gespeicherte_scheibe != aktuelle_scheibe:
                            msg = (f"⚠️ WARNUNG: Profil-Konflikt!\n\n"
                                   f"Diese Kalibrierung wurde für die Scheibe '{gespeicherte_scheibe}' erstellt.\n"
                                   f"Du nutzt aktuell jedoch '{aktuelle_scheibe}'.\n\n"
                                   f"Die errechneten Distanzen (Ringe) werden voraussichtlich falsch sein.\n"
                                   f"Trotzdem laden?")
                            if not messagebox.askyesno("Profil-Konflikt", msg):
                                return # Ladevorgang abbrechen!
                                
                        self.app.calib_mode_active = True
                        self.app.calib_points = pts
                        
                        # ---> NEU: Parameter aus der JSON in die Slider laden (mit r4-Abwärtskompatibilität) <---
                        if params:
                            if 'px_x' in params: self.app.calib_x_var.set(params['px_x'])
                            if 'px_y' in params: self.app.calib_y_var.set(params['px_y'])
                            if 'korr' in params: self.app.calib_linsen_verzerrung_var.set(params['korr'])
                            
                            # r4-Term auslesen (alte JSONs haben diesen Key noch nicht -> Fallback auf 0.0)
                            korr_r4_val = params.get('korr_r4', 0.0)
                            self.app.calib_linsen_verzerrung_r4_var.set(korr_r4_val)
                            
                            if 'off_x' in params: self.app.calib_lens_offset_x_var.set(params['off_x'])
                            if 'off_y' in params: self.app.calib_lens_offset_y_var.set(params['off_y'])
                            
                            # ---> NEU: Gespeichertes Zentrum merken! <---
                            if 'cx' in params: self.loaded_cx = params['cx']
                            if 'cy' in params: self.loaded_cy = params['cy']
                            
                            # ---> NEU: Verhindert, dass Auto-Fit die Werte gleich wieder plattmacht <---
                            self.skip_initial_autofit = True
                            
                        self.finish_calibration() # Direkt in die Werkbank springen!
                        return
                    else:
                        messagebox.showerror("Fehler", f"Die Datei enthält {len(pts)} statt 16 oder 20 Punkte!")
                except Exception as e:
                    messagebox.showerror("Fehler", f"Konnte Datei nicht laden:\n{e}")
                    
        self.app.calib_mode_active = True
        self.app.calib_points = []
        self.app.btn_calib_assist.config(bg="#e74c3c", text="🔴 Assistent aktiv (Abbrechen)")
        self.app.lbl_image.config(cursor="crosshair")
        
        d_config = self.app.package_data['config']
        aktive_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
        
        self.app.print_log("KALIB", "▼" * 70, show_gui=True)
        self.app.print_log("KALIB", f"🛑  !!! AKTIVES PROFIL: {aktive_scheibe.upper()} !!!  🛑", show_gui=True)
        self.app.print_log("KALIB", "▲" * 70, show_gui=True)
        
        if "Laufende" in aktive_scheibe:
            self.app.print_log("KALIB", "⚠️ Achtung: Es ist ein Profil für Laufende Scheiben aktiv!", show_gui=True)
            
        self.app.print_log("KALIB", "----------------------------------------------------------------------", show_gui=True)
        self.app.print_log("KALIB", "📐 BEDIENUNG DER KALIBRIERUNG:", show_gui=True)
        self.app.print_log("KALIB", "[Linksklick]         : Punkt setzen", show_gui=True)
        self.app.print_log("KALIB", "[Mausrad / Zoom-Box] : Nah heranzoomen für Subpixel-Präzision!", show_gui=True)
        self.app.print_log("KALIB", "[Rechtsklick]        : Zoom zurücksetzen (Bildausschnitt anpassen)", show_gui=True)
        self.app.print_log("KALIB", "[Backspace / ESC]    : Letzten Klick rückgängig machen", show_gui=True)
        self.app.print_log("KALIB", "----------------------------------------------------------------------\n", show_gui=True)
            
        self.update_calibration_instruction()
        
    def undo_calibration_click(self, event=None):
        """Macht den letzten Klick im Assistenten rückgängig."""
        if not getattr(self.app, 'calib_mode_active', False) or not self.app.calib_points:
            return
            
        removed_pt = self.app.calib_points.pop()
        self.app.print_log("KALIB", f"Letzter Klick rückgängig gemacht (noch {len(self.app.calib_points)}/16 Punkte).", show_gui=True)
        
        self.app.renderer.update_image_display()
        self.update_calibration_instruction()  

    def cancel_calibration(self):
        """Bricht den Assistenten ab."""
        self.app.calib_mode_active = False
        self.app.calib_points = []
        self.app.btn_calib_assist.config(bg="#8e44ad", text="📏 Kalibrierung")
        self.app.lbl_image.config(cursor="")
        self.app.print_log("KALIB", "Assistent manuell abgebrochen.", show_gui=True)
        self.app.renderer.update_image_display()

    def update_calibration_instruction(self):
        """Aktualisiert die Anweisungen für den Benutzer, je nachdem, wie viele Klicks schon erfolgt sind."""
        steps = [
            "1/20: Klicke auf den LINKEN Rand des schwarzen Spiegels",
            "2/20: Klicke auf den RECHTEN Rand des schwarzen Spiegels",
            "3/20: Klicke auf den OBEREN Rand des schwarzen Spiegels",
            "4/20: Klicke auf den UNTEREN Rand des schwarzen Spiegels",
            "5/20: Klicke DIAGONAL LINKS OBEN am schwarzen Spiegel",
            "6/20: Klicke DIAGONAL RECHTS UNTEN am schwarzen Spiegel",
            "7/20: Klicke DIAGONAL RECHTS OBEN am schwarzen Spiegel",
            "8/20: Klicke DIAGONAL LINKS UNTEN am schwarzen Spiegel",
            "9/20: Klicke auf den LINKEN Rand des 9er-Rings",
            "10/20: Klicke auf den RECHTEN Rand des 9er-Rings",
            "11/20: Klicke auf den OBEREN Rand des 9er-Rings",
            "12/20: Klicke auf den UNTEREN Rand des 9er-Rings",
            "13/20: Klicke auf den LINKEN Rand des 6er-Rings",
            "14/20: Klicke auf den RECHTEN Rand des 6er-Rings",
            "15/20: Klicke auf den OBEREN Rand des 6er-Rings",
            "16/20: Klicke auf den UNTEREN Rand des 6er-Rings",
            "17/20: Klicke auf den LINKEN Rand des äußersten Rings",
            "18/20: Klicke auf den RECHTEN Rand des äußersten Rings",
            "19/20: Klicke auf den OBEREN Rand des äußersten Rings",
            "20/20: Klicke auf den UNTEREN Rand des äußersten Rings"
        ]
        
        if len(self.app.calib_points) < len(steps):
            self.app.print_log("KALIBRIERUNG", steps[len(self.app.calib_points)], show_gui=True)
            self.app.lbl_coords.config(text=f"Aktion: {steps[len(self.app.calib_points)]}")
        else:
            self.finish_calibration()

    def handle_calibration_click(self, event):
        """Sammelt die Klicks des Benutzers und löst ein Neuzeichnen aus."""
        if getattr(self.app, 'base_combined_img', None) is None or not hasattr(self.app, 'current_scale'):
            return
            
        x, y = event.x, event.y
        img_h, img_w = self.app.base_combined_img.shape[:2]
        if x < 0 or y < 0 or x >= img_w or y >= img_h: return

        is_left = (x < self.app.current_img_w)
        raw_x = x if is_left else (x - self.app.current_img_w)
        real_x = round(raw_x / self.app.current_scale, 4)
        real_y = round(y / self.app.current_scale, 4)
        
        self.app.calib_points.append((real_x, real_y))
        
        schritt = len(self.app.calib_points)
        self.app.print_log("KALIB", f"✓ Punkt {schritt}/16 gesetzt bei (X: {real_x}, Y: {real_y})", show_gui=True)
        
        self.app.renderer.update_image_display()
        self.update_calibration_instruction()

    def finish_calibration(self):
        """Berechnet aus den gesammelten Punkten die Empfehlungen inkl. Best-Fit Validierung."""
        self.app.calib_mode_active = False
        self.app.btn_calib_assist.config(bg="#8e44ad", text="📏 Kalibrierung")
        self.app.lbl_image.config(cursor="")
        
        if len(self.app.calib_points) not in [16, 20]:
            self.app.print_log("KALIB", "Falsche Anzahl Punkte gesammelt. Abbruch.", show_gui=True)
            return
            
        d_config = self.app.package_data['config']
        aktive_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
        targets = self.app.dm.load_targets()
        
        if aktive_scheibe not in targets:
            messagebox.showerror("Fehler", f"Scheibe '{aktive_scheibe}' nicht in zielscheiben.json gefunden!")
            return
            
        target_data = targets[aktive_scheibe]
        
        try:
            spiegel_mm = float(target_data.get('spiegel_durchmesser_mm', 30.5))
            ringe_mm = target_data.get('ringe_durchmesser_mm', {})
            neun_mm = float(ringe_mm.get('9', spiegel_mm * 0.5))
            
            # 6er Ring auslesen
            sechs_mm = float(ringe_mm.get('6', spiegel_mm * 1.5)) 
            
            if '1' in ringe_mm:
                aussen_mm = float(ringe_mm['1'])
            else:
                 aussen_mm = max([float(v) for v in ringe_mm.values()]) if ringe_mm else spiegel_mm * 2.0

            # ---> ELA: Linienstärke aus der zielscheiben.json auslesen (Default 0.2 mm) <---
            linienstaerke_mm = float(target_data.get('linienstaerke_mm', 0.2))
            halbe_linie = linienstaerke_mm / 2.0
            
        except ValueError:
            messagebox.showerror("Fehler", "Ungültige Millimeter-Werte in der zielscheiben.json!")
            return

        pts = self.app.calib_points
        spiegel_l, spiegel_r, spiegel_o, spiegel_u = pts[0], pts[1], pts[2], pts[3]
        diag1_o, diag1_u, diag2_o, diag2_u = pts[4], pts[5], pts[6], pts[7]
        neun_l, neun_r, neun_o, neun_u = pts[8], pts[9], pts[10], pts[11]
        
        # ---> GEÄNDERT: Dynamische Zuweisung für 16 vs 20 Punkte <---
        if len(pts) == 20:
            sechs_l, sechs_r, sechs_o, sechs_u = pts[12], pts[13], pts[14], pts[15]
            aussen_l, aussen_r, aussen_o, aussen_u = pts[16], pts[17], pts[18], pts[19]
        else:
            # Fallback für alte 16-Punkte JSONs (Wir tun so, als gäbe es keinen Klick)
            sechs_l, sechs_r, sechs_o, sechs_u = None, None, None, None
            aussen_l, aussen_r, aussen_o, aussen_u = pts[12], pts[13], pts[14], pts[15]

        init_cx = (neun_l[0] + neun_r[0] + spiegel_l[0] + spiegel_r[0] + aussen_l[0] + aussen_r[0]) / 6.0
        init_cy = (neun_o[1] + neun_u[1] + spiegel_o[1] + spiegel_u[1] + aussen_o[1] + aussen_u[1]) / 6.0
        
        # WAHRE physikalische Wertungsgrenzen (Außenkante der Linie = Radius + halbe Linienstärke)
        r_9 = (neun_mm / 2.0) + halbe_linie
        r_s = (spiegel_mm / 2.0) # Der Spiegel ist eine Hell/Dunkel-Kante ohne dicke Linie
        r_a = (aussen_mm / 2.0) + halbe_linie
        if sechs_l is not None:
            r_6 = (sechs_mm / 2.0) + halbe_linie
        
        p_9_x = abs(neun_r[0] - neun_l[0]) / 2.0
        p_s_x = abs(spiegel_r[0] - spiegel_l[0]) / 2.0
        p_a_x = abs(aussen_r[0] - aussen_l[0]) / 2.0
        p_9_y = abs(neun_u[1] - neun_o[1]) / 2.0
        p_s_y = abs(spiegel_u[1] - spiegel_o[1]) / 2.0
        p_a_y = abs(aussen_u[1] - aussen_o[1]) / 2.0
        
        y_data_x = np.array([p_9_x / r_9, p_s_x / r_s, p_a_x / r_a])
        y_data_y = np.array([p_9_y / r_9, p_s_y / r_s, p_a_y / r_a])

        side = self.app.active_camera_var.get()
        seite_str = "links" if side == 'left' else "rechts"
        crop_sec = "Crop_Links" if side == 'left' else "Crop_Rechts"
        cam_w = d_config.getint('Kameras', f'cam_width_{seite_str}', fallback=1280)
        cam_h = d_config.getint('Kameras', f'cam_height_{seite_str}', fallback=720)
        cut_l = d_config.getint(crop_sec, 'cut_left', fallback=0)
        cut_t = d_config.getint(crop_sec, 'cut_top', fallback=0)
        
        info_win = tk.Toplevel(self.app.root)
        info_win.title("Interaktive Kalibrierungs-Werkbank")
        
        info_win.lift()
        info_win.focus_force()
        
        sf = self.app.root.winfo_fpixels('1i') / 96.0
        info_win.geometry(f"{int(750 * sf)}x{int(850 * sf)}")
        
        tk.Label(info_win, text="Kalibrierungs-Werkbank", font=("Arial", 12, "bold")).pack(pady=(10, 5))
        
        control_frame = tk.Frame(info_win)
        control_frame.pack(fill=tk.X, padx=15, pady=5)
        
        if getattr(self, 'loaded_cx', None) is not None:
            var_cx = tk.DoubleVar(value=round(self.loaded_cx, 2))
            var_cy = tk.DoubleVar(value=round(self.loaded_cy, 2))
            self.loaded_cx = None
            self.loaded_cy = None
        else:
            var_cx = tk.DoubleVar(value=round(init_cx, 2))
            var_cy = tk.DoubleVar(value=round(init_cy, 2))
            
        var_px_x = tk.DoubleVar(value=self.app.calib_x_var.get())
        var_px_y = tk.DoubleVar(value=self.app.calib_y_var.get())
        var_korr = tk.DoubleVar(value=self.app.calib_linsen_verzerrung_var.get())
        var_r4 = tk.DoubleVar(value=self.app.calib_linsen_verzerrung_r4_var.get())
        var_off_x = tk.IntVar(value=self.app.calib_lens_offset_x_var.get())
        var_off_y = tk.IntVar(value=self.app.calib_lens_offset_y_var.get())

        # ---> NEU: Lock-Variablen für die UI <---
        lock_cx = tk.BooleanVar(value=False)
        lock_cy = tk.BooleanVar(value=False)
        lock_px_x = tk.BooleanVar(value=False)
        lock_px_y = tk.BooleanVar(value=False)
        lock_korr = tk.BooleanVar(value=False)
        lock_r4 = tk.BooleanVar(value=False)
        lock_off_x = tk.BooleanVar(value=False)
        lock_off_y = tk.BooleanVar(value=False)
        
        def build_param_row(parent, label, tk_var, res, step, lock_var):
            row = tk.Frame(parent)
            row.pack(fill=tk.X, pady=2)
            
            def toggle_lock():
                lock_var.set(not lock_var.get())
                btn_lock.config(text="🔒" if lock_var.get() else "🔓")
                recalculate()  # <--- HIER: Zwingt das Log zum sofortigen Update!
                
            btn_lock = tk.Button(row, text="🔒" if lock_var.get() else "🔓", command=toggle_lock, font=("Segoe UI Emoji", 8), width=3, relief=tk.FLAT)
            btn_lock.pack(side=tk.LEFT, padx=(0, 2))
            
            tk.Label(row, text=label, width=17, anchor="w").pack(side=tk.LEFT)
            
            def nudge(amount):
                if isinstance(tk_var, tk.IntVar):
                    tk_var.set(int(tk_var.get() + amount))
                else:
                    tk_var.set(round(tk_var.get() + amount, 8))
                recalculate()
                
            tk.Button(row, text="◀", command=lambda: nudge(-step), font=("Arial", 8), padx=2, pady=0).pack(side=tk.LEFT)
            entry = tk.Entry(row, textvariable=tk_var, width=12, justify="center")
            entry.pack(side=tk.LEFT, padx=5)
            tk.Button(row, text="▶", command=lambda: nudge(step), font=("Arial", 8), padx=2, pady=0).pack(side=tk.LEFT)
            
            entry.bind("<Return>", lambda e: recalculate())
            entry.bind("<FocusOut>", lambda e: recalculate())

        # UI-Aufrufe mit zugeordnetem Lock
        build_param_row(control_frame, "Zentrum X (cx):", var_cx, 0.1, 0.2, lock_cx)
        build_param_row(control_frame, "Zentrum Y (cy):", var_cy, 0.1, 0.2, lock_cy)
        build_param_row(control_frame, "Pixel pro mm X:", var_px_x, 0.001, 0.01, lock_px_x)
        build_param_row(control_frame, "Pixel pro mm Y:", var_px_y, 0.001, 0.01, lock_px_y)
        build_param_row(control_frame, "Linsen-Verzerr. (r2):", var_korr, 0.00001, 0.0001, lock_korr)
        build_param_row(control_frame, "Linsen-Verzerr. (r4):", var_r4, 0.0000001, 0.000001, lock_r4)
        build_param_row(control_frame, "Linsen-Offset X:", var_off_x, 1, 5, lock_off_x)
        build_param_row(control_frame, "Linsen-Offset Y:", var_off_y, 1, 5, lock_off_y)

        txt_frame = tk.Frame(info_win)
        txt_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        scrollbar = tk.Scrollbar(txt_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        txt_log = tk.Text(txt_frame, font=("Consolas", 10), bg="#1e1e1e", fg="#00ff00", yscrollcommand=scrollbar.set)
        txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=txt_log.yview)

        final_values = {}

        def recalculate(*args):
            cx = var_cx.get()
            cy = var_cy.get()
            px_mm_x = var_px_x.get()
            px_mm_y = var_px_y.get()
            avg_korrektur = var_korr.get()
            korr_r4 = var_r4.get()
            off_x = var_off_x.get()
            off_y = var_off_y.get()
            
            lens_cx, lens_cy = Helfer.get_optical_center(cam_w, cam_h, cut_l, cut_t, off_x, off_y)

            # Echte physikalische Soll-Radien aus der zielscheiben.json (Außenkanten)
            r_s = spiegel_mm / 2.0
            r_9 = neun_mm / 2.0
            r_a = aussen_mm / 2.0
            r_6 = sechs_mm / 2.0 if sechs_l is not None else 0.0

            # Das dynamische optische Korsett (5 mm hinter dem Außenring)
            r_limit_mm = r_a + 5.0

            # Hilfsfunktion für die Log-Ausgabe
            def lock_str(lock_var):
                return " 🔒 (Fixiert)" if lock_var.get() else ""

            log_lines = []
            log_lines.append(f"AKTUELLE WERKZEUG-PARAMETER:")
            log_lines.append(f"  Zentrum (X/Y) : {cx:.2f}{lock_str(lock_cx)} / {cy:.2f}{lock_str(lock_cy)}")
            log_lines.append(f"  px_pro_mm (X) : {px_mm_x:.4f}{lock_str(lock_px_x)}")
            log_lines.append(f"  px_pro_mm (Y) : {px_mm_y:.4f}{lock_str(lock_px_y)}")
            log_lines.append(f"  Verzerrung r2 : {avg_korrektur:.6f}{lock_str(lock_korr)}")
            log_lines.append(f"  Verzerrung r4 : {korr_r4:.8f}{lock_str(lock_r4)}")
            log_lines.append(f"  Linsen-Offset : X:{off_x}{lock_str(lock_off_x)} / Y:{off_y}{lock_str(lock_off_y)}\n")
            
            log_lines.append("BEST-FIT VALIDIERUNG (Theorie vs. Klick):")
            log_lines.append("(Minus = Klick war näher am Zentrum als berechnet)")

            err_sum_9 = 0
            err_sum_s = 0
            err_sum_6 = 0
            err_sum_a = 0

            # Validierung: Rechnet komplett in der WAHREN PHYSIKALISCHEN EBENE (mm)
            def validate_target_point(pt, r_soll, index):
                true_cx, true_cy = Helfer.undistort_point_mm(cx, cy, lens_cx, lens_cy, px_mm_x, px_mm_y, avg_korrektur, korr_r4, r_limit_mm)
                true_klick_x, true_klick_y = Helfer.undistort_point_mm(pt[0], pt[1], lens_cx, lens_cy, px_mm_x, px_mm_y, avg_korrektur, korr_r4, r_limit_mm)

                dist_klick_mm = math.hypot(true_klick_x - true_cx, true_klick_y - true_cy)
                
                offset_mm = 0.0 if index < 8 else halbe_linie
                dist_red_mm = dist_klick_mm + offset_mm

                err_mm = dist_red_mm - r_soll
                err_px = err_mm * ((px_mm_x + px_mm_y) / 2.0)
                return err_px, err_mm

            def add_validation(section_name, mm_real, r_soll_val, labels, points, start_index):
                nonlocal err_sum_9, err_sum_s, err_sum_6, err_sum_a, log_lines
                log_lines.append(f"\n▶ {section_name} ({mm_real} mm):")
                sum_err = 0
                for idx, (lbl, pt) in enumerate(zip(labels, points)):
                    actual_index = start_index + idx
                    err_px, err_mm = validate_target_point(pt, r_soll_val, actual_index)
                    sum_err += abs(err_mm)
                    log_lines.append(f"  {lbl:<12} -> Abweichung: {err_px:>+5.1f} px  |  {err_mm:>+6.2f} mm")
                
                avg = sum_err / len(points)
                if section_name == "9er-Ring": err_sum_9 = avg
                elif "Spiegel" in section_name: err_sum_s += avg * len(points) 
                elif section_name == "6er-Ring": err_sum_6 = avg
                elif section_name == "Außenring": err_sum_a = avg

            add_validation("9er-Ring", neun_mm, r_9, ["Links", "Rechts", "Oben", "Unten"], [neun_l, neun_r, neun_o, neun_u], 8)
            add_validation("Spiegel (Achsen)", spiegel_mm, r_s, ["Links", "Rechts", "Oben", "Unten"], [spiegel_l, spiegel_r, spiegel_o, spiegel_u], 0)
            add_validation("Spiegel (Diag)", spiegel_mm, r_s, ["Links-Oben", "Rechts-Unten", "Rechts-Oben", "Links-Unten"], [diag1_o, diag1_u, diag2_o, diag2_u], 4)
            err_sum_s = err_sum_s / 8.0 
            
            if sechs_l is not None:
                add_validation("6er-Ring", sechs_mm, r_6, ["Links", "Rechts", "Oben", "Unten"], [sechs_l, sechs_r, sechs_o, sechs_u], 12)
                
            add_validation("Außenring", aussen_mm, r_a, ["Links", "Rechts", "Oben", "Unten"], [aussen_l, aussen_r, aussen_o, aussen_u], 16)

            log_lines.append("\n" + "="*50)
            log_lines.append("Ø ABSOLUTE FEHLERABWEICHUNG:")
            log_lines.append(f"  9er-Ring  : ± {err_sum_9:.2f} mm")
            log_lines.append(f"  Spiegel   : ± {err_sum_s:.2f} mm")
            if sechs_l is not None:
                log_lines.append(f"  6er-Ring  : ± {err_sum_6:.2f} mm")
            log_lines.append(f"  Außenring : ± {err_sum_a:.2f} mm")
            
            txt_log.config(state=tk.NORMAL)
            txt_log.delete(1.0, tk.END)
            txt_log.insert(tk.END, "\n".join(log_lines))
            txt_log.config(state=tk.DISABLED)
            
            final_values['cx'] = cx
            final_values['cy'] = cy
            final_values['px_x'] = px_mm_x
            final_values['px_y'] = px_mm_y
            final_values['korr'] = avg_korrektur
            final_values['r4'] = korr_r4
            final_values['off_x'] = off_x
            final_values['off_y'] = off_y
            final_values['log'] = log_lines
            
            info_win.lift()
            info_win.focus_force()

        def do_auto_fit():
            cx_center = var_cx.get()
            cy_center = var_cy.get()

            r_s = spiegel_mm / 2.0
            r_9 = neun_mm / 2.0
            r_a = aussen_mm / 2.0
            r_6 = sechs_mm / 2.0 if sechs_l is not None else 0.0

            r_limit_mm = r_a + 5.0  # Das Korsett darf erst hinter dem letzten Klick wirken!

            locks = [
                lock_cx.get(), lock_cy.get(),
                lock_px_x.get(), lock_px_y.get(),
                lock_korr.get(), lock_r4.get(),
                lock_off_x.get(), lock_off_y.get()
            ]

            # ---> FIX: Startwerte IMMER vom aktuellen UI-Zustand nehmen! <---
            params = [
                float(var_cx.get()), 
                float(var_cy.get()),
                float(var_px_x.get()),
                float(var_px_y.get()),
                float(var_korr.get()),
                float(var_r4.get()),
                float(var_off_x.get()),
                float(var_off_y.get())
            ]

            calib_targets = [
                (neun_l, r_9, 8), (neun_r, r_9, 9), (neun_o, r_9, 10), (neun_u, r_9, 11),
                (spiegel_l, r_s, 0), (spiegel_r, r_s, 1), (spiegel_o, r_s, 2), (spiegel_u, r_s, 3),
                (diag1_o, r_s, 4), (diag1_u, r_s, 5), (diag2_o, r_s, 6), (diag2_u, r_s, 7),
                (aussen_l, r_a, 16), (aussen_r, r_a, 17), (aussen_o, r_a, 18), (aussen_u, r_a, 19)
            ]
            if sechs_l is not None:
                calib_targets.extend([
                    (sechs_l, r_6, 12), (sechs_r, r_6, 13), (sechs_o, r_6, 14), (sechs_u, r_6, 15)
                ])

            def cost_function(p):
                c_x, c_y, p_x, p_y, k2, k4, ox, oy = p
                
                # Weichere Physik-Schranke, die auf das dynamische r_limit_mm aufbaut
                r_lim_sq = r_limit_mm ** 2
                der_edge = 1.0 + 3.0 * k2 * r_lim_sq + 5.0 * k4 * (r_lim_sq ** 2)
                if der_edge < 0.05: return 1e9  # Verhindert, dass die Linse sich umkehrt
                
                l_cx = (cam_w / 2.0) - cut_l + ox
                l_cy = (cam_h / 2.0) - cut_t + oy
                
                true_cx, true_cy = Helfer.undistort_point_mm(c_x, c_y, l_cx, l_cy, p_x, p_y, k2, k4, r_limit_mm)
                
                total_loss = 0.0
                for pt, r_target, index in calib_targets:
                    true_klick_x, true_klick_y = Helfer.undistort_point_mm(pt[0], pt[1], l_cx, l_cy, p_x, p_y, k2, k4, r_limit_mm)
                    dist_klick_mm = math.hypot(true_klick_x - true_cx, true_klick_y - true_cy)
                    
                    offset_mm = 0.0 if index < 8 else halbe_linie
                    dist_red_mm = dist_klick_mm + offset_mm
                    
                    err_mm = dist_red_mm - r_target
                    weight = 4.0 if 8 <= index <= 11 else (1.2 if 0 <= index <= 3 else (0.8 if 4 <= index <= 7 else 2.0))
                    total_loss += weight * (err_mm ** 2)
                
                total_loss += 0.0000005 * (ox**2 + oy**2)
                return total_loss

            # Erhöhte Suchgeschwindigkeit für r4
            steps = [0.4, 0.4, 0.05, 0.05, 0.0001, 0.000001, 8.0, 8.0]
            best_loss = cost_function(params)
            
            print("\n" + "="*50)
            print(f"🚀 AUTO-FIT START | Init-Loss: {best_loss:.4f}")
            print("="*50)

            for cascade in range(7):
                improved = True
                iters = 0
                while improved and iters < 80:
                    improved = False
                    iters += 1
                    
                    for i in range(len(params)):
                        if locks[i]: continue 
                        
                        orig_val = params[i]
                        step = steps[i]
                        
                        for direction in (-1.0, 1.0):
                            cand_val = orig_val + direction * step
                            
                            # Großzügigere Verzerrungs-Schranken
                            if i == 4: cand_val = max(-0.01, min(0.01, cand_val))
                            elif i == 5: cand_val = max(-0.0001, min(0.0001, cand_val))
                            elif i in (6, 7): cand_val = max(-300.0, min(300.0, cand_val))
                            
                            params[i] = cand_val
                            loss = cost_function(params)
                            
                            if loss < best_loss - 1e-10:
                                best_loss = loss
                                orig_val = cand_val
                                improved = True
                                break
                            else:
                                params[i] = orig_val

                    for direction in (-1.0, 1.0):
                        old_p = params[:]
                        if not locks[2]: params[2] += direction * steps[2] * 0.5
                        if not locks[3]: params[3] += direction * steps[3] * 0.5
                        if not locks[4]: params[4] = max(-0.01, min(0.01, params[4] - direction * steps[4] * 0.8))
                        if not locks[5]: params[5] = max(-0.0001, min(0.0001, params[5] + direction * steps[5] * 0.8))
                        
                        loss = cost_function(params)
                        if loss < best_loss - 1e-10:
                            best_loss = loss
                            improved = True
                        else:
                            params = old_p

                print(f"🏁 Cascade {cascade+1}/7: Loss={best_loss:.4f} | px={params[2]:.4f} | r2={params[4]:.7f} | r4={params[5]:.9f}")
                steps = [s * 0.4 for s in steps]

            print("="*50 + "\n")

            var_cx.set(round(params[0], 2))
            var_cy.set(round(params[1], 2))
            var_px_x.set(round(params[2], 4))
            var_px_y.set(round(params[3], 4))
            var_korr.set(round(params[4], 7))
            var_r4.set(round(params[5], 9))
            var_off_x.set(int(round(params[6])))
            var_off_y.set(int(round(params[7])))
            
            recalculate()

        def apply_preview():
            self.app._is_loading = True
            try:
                self.app.calib_x_var.set(final_values['px_x'])
                self.app.calib_y_var.set(final_values['px_y'])
                self.app.calib_linsen_verzerrung_var.set(final_values['korr']) 
                self.app.calib_linsen_verzerrung_r4_var.set(final_values['r4']) 
                self.app.calib_lens_offset_x_var.set(final_values['off_x']) 
                self.app.calib_lens_offset_y_var.set(final_values['off_y']) 
                
                side = self.app.active_camera_var.get()
                seite_str = "links" if side == 'left' else "rechts"
                if hasattr(self.app, 'package_data') and self.app.package_data and 'config' in self.app.package_data:
                    d_config = self.app.package_data['config']
                    d_config.set('Kameras', f'px_pro_mm_x_{seite_str}', str(final_values['px_x']))
                    d_config.set('Kameras', f'px_pro_mm_y_{seite_str}', str(final_values['px_y']))
                    d_config.set('Kameras', f'linsen_verzerrung_{seite_str}', str(final_values['korr']))
                    d_config.set('Kameras', f'linsen_verzerrung_{seite_str}_r4', str(final_values['r4']))
                    d_config.set('Kameras', f'lens_offset_x_{seite_str}', str(final_values['off_x']))
                    d_config.set('Kameras', f'lens_offset_y_{seite_str}', str(final_values['off_y']))
            finally:
                self.app._is_loading = False
                
            center_key = 'center_l' if side == 'left' else 'center_r'
            if getattr(self.app, 'original_match_data', None) is None:
                self.app.original_match_data = {}
            if 'metadata' not in self.app.original_match_data:
                self.app.original_match_data['metadata'] = {}
                
            self.app.original_match_data['metadata'][center_key] = [final_values['cx'], final_values['cy']]
            
            if hasattr(self.app, 'package_data') and self.app.package_data and 'config' in self.app.package_data:
                d_config = self.app.package_data['config']
                from LaborDeLuebs import DummyDateiManager 
                d_dm = DummyDateiManager(self.app)
                d_sm = StateManager(d_config, d_dm)
                d_sm.set_nullpunkt(side, final_values['cx'], final_values['cy'])
            
            self.app.process_and_display()
            
            info_win.lift()
            info_win.focus_force()

        def apply_and_close():
            self.app.calib_points = []
            apply_preview()
            self.app.print_log("SYSTEM", "✅ Kalibrierungswerte aus der Werkbank übernommen!", show_gui=True)
            info_win.destroy()
            
        def cancel_and_close():
            self.app.calib_points = []
            self.app.renderer.update_image_display()
            info_win.destroy()
            
        info_win.protocol("WM_DELETE_WINDOW", cancel_and_close)

        def copy_to_clipboard():
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append("\n".join(final_values['log']))
            tk.messagebox.showinfo("Kopiert", "Das aktuelle Protokoll wurde in die Zwischenablage kopiert!", parent=info_win)
            
        def export_points():
            match_name = "MATCH_Unbekannt"
            if getattr(self.app, 'current_zip_path', None):
                match_name = os.path.basename(self.app.current_zip_path).replace('.zip', '')
                
            side = self.app.active_camera_var.get()
            seite_str = "Links" if side == 'left' else "Rechts"
            
            default_filename = f"kalibrierung_{match_name}_{seite_str}.json"

            filepath = filedialog.asksaveasfilename(
                title="Kalibrierung speichern", 
                defaultextension=".json", 
                initialfile=default_filename,
                filetypes=[("JSON", "*.json")]
            )
            if filepath:
                try:
                    d_config = self.app.package_data['config']
                    aktive_scheibe_str = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Unbekannt')
                    
                    export_data = {
                        "points": self.app.calib_points,
                        "params": {
                            "px_x": var_px_x.get(),
                            "px_y": var_px_y.get(),
                            "korr": var_korr.get(),
                            "korr_r4": var_r4.get(),
                            "off_x": var_off_x.get(),
                            "off_y": var_off_y.get(),
                            "cx": var_cx.get(),               
                            "cy": var_cy.get(),               
                            "zielscheibe": aktive_scheibe_str
                        }
                    }
                    with open(filepath, "w") as f:
                        json.dump(export_data, f, indent=4)
                    tk.messagebox.showinfo("Erfolg", "Punkte und Parameter erfolgreich gespeichert!", parent=info_win)
                except Exception as e:
                    tk.messagebox.showerror("Fehler", f"Speichern fehlgeschlagen:\n{e}", parent=info_win)
        
        btn_frame_top = tk.Frame(control_frame)
        btn_frame_top.pack(fill=tk.X, pady=10)
        tk.Button(btn_frame_top, text="🤖 Auto-Fit (aus Klicks) ausführen", command=do_auto_fit, bg="#e67e22", fg="white", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        tk.Button(btn_frame_top, text="💾 Speichern / Exportieren", command=export_points, bg="#8e44ad", fg="white", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=10)
        
        pin_var = tk.BooleanVar(value=False)
        def toggle_pin():
            info_win.attributes('-topmost', pin_var.get())
            
        tk.Checkbutton(btn_frame_top, text="📌 Oben anpinnen", variable=pin_var, command=toggle_pin, font=("Arial", 9)).pack(side=tk.RIGHT, padx=10)
        
        btn_frame = tk.Frame(info_win)
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="👁️ Übernehmen", command=apply_preview, bg="#3498db", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="✅ Schließen & Übernehmen", command=apply_and_close, bg="#27ae60", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="📋 Log kopieren", command=copy_to_clipboard, bg="#95a5a6", fg="white").pack(side=tk.LEFT, padx=5)
        
        if getattr(self, 'skip_initial_autofit', False):
            recalculate()
            self.skip_initial_autofit = False
        else:
            do_auto_fit()
            
        self.app.renderer.update_image_display()