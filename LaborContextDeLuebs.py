import cv2
import numpy as np
import copy
import os
import io
import json
import shutil
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import time
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

from DetectionDeLuebs import TargetDetector
from StateManagerDeLuebs import StateManager

# =========================================================================
# ---> NEU HIER: Der Dummy-Manager ist ins Model umgezogen! <---
# =========================================================================
class DummyDateiManager:
    def __init__(self, app):
        self.app = app
        self.debug_images = {}
        self.export_folder = "labor_export"
        
    def get_current_version(self):
        return self.app.dm.get_current_version()
        
    def save_debug_image(self, name, image):
        self.debug_images[name] = image.copy()
        if self.app.export_images_var.get():
            import os
            import cv2
            if not os.path.exists(self.export_folder):
                os.makedirs(self.export_folder)
            path = os.path.join(self.export_folder, f"{name}.png")
            cv2.imwrite(path, image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            return True
        return False
            
    def load_targets(self):
        if getattr(self.app, 'package_data', None) and self.app.package_data.get('targets'):
            return self.app.package_data['targets']
        return self.app.dm.load_targets()
        
    def write_log(self, msg):
        pass


@dataclass
class FrameContext:
    frame_number: int
    shots: List[Dict[str, Any]]
    orig_img: np.ndarray
    ref_img: np.ndarray
    live_img: np.ndarray
    clean_live_img: np.ndarray
    history_mask: np.ndarray
    diff_image: np.ndarray
    diff_gesamt_image: np.ndarray
    abrisskante: Optional[np.ndarray] = None
    raw_diff: Optional[np.ndarray] = None
    thresh_raw: Optional[np.ndarray] = None
    color_dist: Optional[np.ndarray] = None
    color_multiplier: Optional[np.ndarray] = None
    shift_vector: tuple = (0, 0)
    log_text: str = ""
    is_cached_run: bool = False

    def get_safe_history_mask(self):
        if self.history_mask is not None:
            return self.history_mask.copy()
        return np.zeros(self.orig_img.shape[:2], dtype=np.uint8)

class LaborContext:
    def __init__(self, config, datei_manager):
        self.config = config
        self.dm = datei_manager
        self.frame_cache: Dict[str, Dict[int, FrameContext]] = {'left': {}, 'right': {}}
        self.current_side: str = 'left'
        self.current_frame_idx: int = 0
        self.orig_files: List[str] = []
        self.original_match_data: Optional[Dict] = None

    def reset(self):
        self.frame_cache = {'left': {}, 'right': {}}
        
    def get_current_context(self) -> Optional[FrameContext]:
        return self.frame_cache.get(self.current_side, {}).get(self.current_frame_idx)
        
    def _safe_copy(self, img_obj):
        return img_obj.copy() if img_obj is not None else None
        
    def process_frames(self, app, target_idx, side, side_origs, all_files, get_img_func):
        """
        Der Motor des Labors! Kapselt die gesamte Bildverarbeitung.
        - Nimmt rohe Bildpfade und Settings entgegen.
        - Baut sich eine lautlose Dummy-Umgebung (d_dm), um die Festplatte zu schonen.
        - Zieht die Bilder durch die Detection-Engine.
        - Liefert am Ende ein hermetisch abgeriegeltes FrameContext-Paket (das Seiden-Muster).
        """
        d_dm = DummyDateiManager(app) # <--- Dummy wird jetzt hier intern gebaut!
        d_sm = StateManager(self.config, d_dm)
        detector = TargetDetector(self.config, d_dm, d_sm, app.print_log)
        
        ref_name = next((f for f in all_files if f"referenz_{side}" in f), None)
        if not ref_name: 
            return None
        ref_img = get_img_func(ref_name)
        detector.set_reference_image(ref_img, side)
        
        if self.original_match_data:
            meta = self.original_match_data.get('metadata', {})
            center_key = 'center_l' if side == 'left' else 'center_r'
            if meta.get(center_key):
                # ELA-SCHUTZ: Wenn wir historische ZIPs analysieren, MÜSSEN wir 
                # das damals manuell kalibrierte Zentrum aufzwingen, damit die Engine 
                # es nicht durch eine automatische Neu-Erkennung überschreibt.
                cx, cy = meta[center_key][0], meta[center_key][1]
                d_sm.set_nullpunkt(side, cx, cy)
                app.print_log("SYSTEM", f"🎯 Aktiver Nullpunkt {side.upper()} (aus Match-Daten): X:{cx:.2f} Y:{cy:.2f}")
        
        startmask_name = next((f for f in all_files if f"cumulative_startmask_{side}" in f), None)
        startmask_gray = None
        if startmask_name:
            startmask_bgr = get_img_func(startmask_name)
            startmask_gray = cv2.cvtColor(startmask_bgr, cv2.COLOR_BGR2GRAY)
            state = d_sm.state_left if side == 'left' else d_sm.state_right
            state.cumulative_mask = startmask_gray
            app.print_log(None, f"[SYSTEM] Fortsetzung erkannt! Start-Maske für {side} geladen.")
            
        # =========================================================================
        # ---> DIE ZEITMASCHINE (LAZY CACHE SEARCH) <---
        # Wir suchen rückwärts nach dem nächsten bekannten Bild im Cache.
        # Finden wir Bild 45 (und wollen zu 50), sparen wir uns die Berechnung der 
        # Bilder 1 bis 44 und setzen die Engine nahtlos bei Bild 46 fort.
        # HINWEIS: Wenn der Detail-Export an ist, stoppen wir absichtlich ein Bild früher 
        # (target_idx - 1), um das Zielbild zwingend FRISCH mit allen Subpixeln zu rendern!
        # =========================================================================
        detail_export = self.config.getboolean('Erkennung', 'detail_export_aktiv', fallback=False)
        start_search_idx = target_idx - 1 if detail_export else target_idx
        
        best_cached_idx = -1
        for i in range(start_search_idx, -1, -1):
            if i in self.frame_cache[side]:
                best_cached_idx = i
                break
                
        start_idx = 0
        if best_cached_idx >= 0:
            cached_ctx = self.frame_cache[side][best_cached_idx]
            
            d_sm.shots = copy.deepcopy(cached_ctx.shots)
            temp_state = d_sm.state_left if side == 'left' else d_sm.state_right
            temp_state.cumulative_mask = self._safe_copy(cached_ctx.diff_gesamt_image)
            
            d_dm.debug_images[f"diff_letzter_treffer_{side}"] = self._safe_copy(cached_ctx.diff_image)
            d_dm.debug_images[f"letzte_abrisskante_{side}"] = self._safe_copy(cached_ctx.abrisskante)
            
            start_idx = best_cached_idx + 1
            if start_idx <= target_idx:
                app.print_log("SYSTEM", f"⚡ Lazy-Cache: Überspringe die ersten {start_idx} Bilder, setze Zeitreise bei Bild #{start_idx + 1} fort...")

        frames_zu_rechnen = (target_idx + 1) - start_idx
        if frames_zu_rechnen >= 10:
            app.update_frame_title(f"⏳ [Zeitreise] Berechne größere Distanz ({frames_zu_rechnen} Frames)... Bitte warten.")
        app.root.update()
        
        for i in range(start_idx, target_idx + 1):
            img = get_img_func(side_origs[i])
            
            d_dm.debug_images.pop(f"diff_letzter_treffer_{side}", None)
            d_dm.debug_images.pop(f"diff_letzte_verworfene_auswertung_{side}", None)
            d_dm.debug_images.pop(f"letzte_abrisskante_{side}", None)
            
            # =========================================================================
            # ---> DER ZEITMASCHINEN-FIX (DAS MASKEN-PARADOXON) <---
            # Die 'history_mask' (das Bild VOR dem neuen Schuss) muss ZWINGEND hier oben
            # kopiert werden, BEVOR detect_new_shot() aufgerufen wird! 
            # Macht man das danach, ist das neue Loch schon in der Maske, und der Renderer 
            # würde den gerade gemachten Schuss in Ansicht 4 aus Versehen wegradieren.
            # =========================================================================
            temp_state = d_sm.state_left if side == 'left' else d_sm.state_right
            if temp_state.cumulative_mask is not None:
                history_mask = temp_state.cumulative_mask.copy()
            else:
                history_mask = np.zeros(img.shape[:2], dtype=np.uint8)

            if i == target_idx:
                app.print_log(None, "\n" + "▼"*70)
                app.print_log(None, f"███  START DER LIVE-ANALYSE FÜR BILD-AUFNAHME ({i+1})  ███")
                app.print_log(None, "▼"*70)
                detector.detail_export_aktiv = detail_export
            else:
                app.print_log(None, f"\n--- BILD #{i+1} ".ljust(61, "-"))
                detector.detail_export_aktiv = False
                    
            shots_before = len(d_sm.shots)
            detector.detect_new_shot(img, side)
            shots_after = len(d_sm.shots)
            
            for j in range(shots_before, shots_after):
                d_sm.shots[j]['labor_frame_num'] = i + 1
                
            dx, dy = detector.last_shift.get(side, (0, 0))
            live_img = img.copy()
            clean_live_img = img.copy()
            if dx != 0 or dy != 0:
                live_img = detector._shift_image_exact(live_img, dx, dy)
                clean_live_img = detector._shift_image_exact(clean_live_img, dx, dy)
                
            # =========================================================================
            # ---> DIE RAM-DIÄT (SMART CACHING) <---
            # Subpixel-Daten (für den Battle-Royale Röntgenblick) fressen extrem viel Arbeitsspeicher.
            # Bei Frames, über die wir beim Fast-Forward nur unsichtbar drüberspulen (i != target_idx), 
            # schneiden wir diesen Daten-Ballast rigoros ab.
            # NUR das aktuell sichtbare Ziel-Bild behält seine VIP-Detaildaten.
            # =========================================================================
            cache_shots = copy.deepcopy(d_sm.shots)
            if i != target_idx:
                for s in cache_shots:
                    s.pop('score_export_details', None)
            
            raw_diff = None
            thresh_raw = None
            color_dist = None
            color_multiplier = None
            
            # =========================================================================
            # ---> LAZY EVALUATION (MODUS 4 / RAW-DIFF) <---
            # Wir nutzen die offizielle Engine-Methode (keine Redundanz!), fordern aber 
            # mit return_details=True die internen Matrizen (raw_diff, color) an!
            # =========================================================================
            if i == target_idx and len(ref_img.shape) == 3:
                k = app.blur_kernel_size_var.get()
                if k > 0 and k % 2 == 1:
                    live_blur = cv2.GaussianBlur(clean_live_img, (k, k), 0)
                    ref_blur = cv2.GaussianBlur(ref_img, (k, k), 0)
                else:
                    live_blur = clean_live_img.copy()
                    ref_blur = ref_img.copy()                                           
                
                norm_live = detector.normalize_brightness(ref_blur, live_blur)
                
                # ---> DELEGATION AN DIE ENGINE <---
                thresh_raw, raw_diff, color_dist, color_multiplier = detector.calculate_raw_diff_mask(
                    ref_blur, norm_live, side, return_details=True
                )

            ctx = FrameContext(
                frame_number=i,
                shots=cache_shots,
                orig_img=img.copy(),
                ref_img=ref_img.copy() if ref_img is not None else np.zeros_like(img),
                live_img=live_img,
                clean_live_img=clean_live_img,
                history_mask=self._safe_copy(history_mask), 
                diff_image=self._safe_copy(d_dm.debug_images.get(f"diff_letzter_treffer_{side}")),
                diff_gesamt_image=self._safe_copy(temp_state.cumulative_mask), 
                abrisskante=self._safe_copy(d_dm.debug_images.get(f"letzte_abrisskante_{side}")),
                raw_diff=self._safe_copy(raw_diff),
                thresh_raw=self._safe_copy(thresh_raw),
                color_dist=self._safe_copy(color_dist),
                color_multiplier=self._safe_copy(color_multiplier),
                shift_vector=detector.last_shift.get(side, (0, 0)),
                log_text=app.log_text.get("1.0", tk.END),
                is_cached_run=False
            )
            self.frame_cache[side][i] = ctx

        # =========================================================================
        # ---> DER FALLBACK REPARATUR-TRUPP (0-ms CACHE RESTORE) <---
        # Dieser Block greift, wenn wir in der Historie RÜCKWÄRTS springen und das Bild 
        # bereits fix und fertig im Cache liegt.
        # WICHTIG: Da wir die schweren 'raw_diff'-Daten oben beim schnellen Vorwärtsspulen 
        # aus Performance-Gründen übersprungen hatten (sie sind None), müssen wir sie 
        # jetzt in Millisekunden NACHBERECHNEN, weil der User genau dieses Bild ansteuert!
        # =========================================================================
        if start_idx > target_idx:
            ctx = self.frame_cache[side][target_idx]
            
            if ctx.raw_diff is None and len(ctx.ref_img.shape) == 3:
                k = app.blur_kernel_size_var.get()
                if k > 0 and k % 2 == 1:
                    live_blur = cv2.GaussianBlur(ctx.clean_live_img, (k, k), 0)
                    ref_blur = cv2.GaussianBlur(ctx.ref_img, (k, k), 0)
                else:
                    live_blur = ctx.clean_live_img.copy()
                    ref_blur = ctx.ref_img.copy()                                           
                
                norm_live = detector.normalize_brightness(ref_blur, live_blur)
                
                # ---> DELEGATION AN DIE ENGINE (DRY-PRINZIP) <---
                lazy_thresh, lazy_raw, lazy_cdist, lazy_cmult = detector.calculate_raw_diff_mask(
                    ref_blur, norm_live, side, return_details=True
                )
                
                ctx.raw_diff = lazy_raw
                ctx.thresh_raw = lazy_thresh
                ctx.color_dist = lazy_cdist
                ctx.color_multiplier = lazy_cmult
            
            cached_log = ctx.log_text
            if cached_log:
                app.log_text.insert(tk.END, cached_log.rstrip('\n') + '\n')
            
            app.print_log(None, "\n" + "▼"*70)
            app.print_log(None, f"███  BILD #{target_idx+1} DIREKT AUS DEM CACHE GELADEN (0 ms)  ███")
            app.print_log(None, "▼"*70)
            
        return self.frame_cache[side][target_idx]

    # =========================================================================
    # ---> DIE AUSGELAGERTEN GIGANTEN <---
    # =========================================================================
    def align_shots(self, orig_shots, curr_shots, threshold):
        aligned = []
        used_curr = set()
        
        for i, orig in enumerate(orig_shots):
            ox, oy = orig['x'], orig['y']
            best_j = None
            best_dist = float('inf')
            
            start_j = max(0, i - 15)
            end_j = min(len(curr_shots), i + 15)
            
            for j in range(start_j, end_j):
                if j in used_curr: continue
                cx, cy = int(curr_shots[j]['pos'][0]), int(curr_shots[j]['pos'][1])
                dist = np.hypot(cx - ox, cy - oy)
                if dist < threshold and dist < best_dist:
                    best_dist = dist
                    best_j = j
                    
            if best_j is not None:
                used_curr.add(best_j)
                aligned.append((i, best_j, best_dist))
            else:
                aligned.append((i, None, None))
                
        for j in range(len(curr_shots)):
            if j not in used_curr:
                aligned.append((None, j, None))
                
        def sort_key(item):
            o_idx, c_idx, d = item
            if o_idx is not None: return o_idx * 1000
            if c_idx is not None: return (c_idx * 1000) + 500
            return 999999
            
        aligned.sort(key=sort_key)
        return aligned

    def show_comparison(self, app):
        if not app.current_zip_path or not getattr(app, 'original_match_data', None) or not app.orig_files:
            return

        comp_win = tk.Toplevel(app.root)
        comp_win.title("📊 Integrations-Check: Live-Parameter vs. Original-Match")
        
        sf = app.root.winfo_fpixels('1i') / 96.0
        w, h = int(1600 * sf), int(750 * sf) 
        comp_win.geometry(f"{w}x{h}")
        comp_win.lift()
        comp_win.focus_force()

        btn_frame = tk.Frame(comp_win)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        def copy_to_clipboard():
            full_log = txt.get("1.0", tk.END)
            app.root.clipboard_clear()
            app.root.clipboard_append(full_log)
            messagebox.showinfo("Kopiert", "Das komplette Protokoll wurde in die Zwischenablage kopiert!", parent=comp_win)
            
        tk.Button(btn_frame, text="📋 In Zwischenablage kopieren", command=copy_to_clipboard, bg="#3498db", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT)

        txt_frame = tk.Frame(comp_win)
        txt_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        scrollbar = tk.Scrollbar(txt_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        txt = tk.Text(txt_frame, font=("Consolas", 12), bg="#1e1e1e", fg="#00ff00", padx=10, pady=10, yscrollcommand=scrollbar.set)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=txt.yview)

        txt.insert(tk.END, "Führe komplette Neuberechnung aller Schüsse durch... Bitte warten...\n")
        comp_win.update()

        d_config = app.package_data['config']
        d_dm = DummyDateiManager(app)
        d_sm = StateManager(d_config, d_dm)
        detector = TargetDetector(d_config, d_dm, d_sm, lambda side, text, show_gui=False: None) 

        for s in ['left', 'right']:
            ref_name = next((f for f in app.all_files if f"referenz_{s}" in f), None)
            if ref_name:
                ref_img = app.get_img(ref_name)
                detector.set_reference_image(ref_img, s)
                
                if getattr(app, 'original_match_data', None):
                    meta = app.original_match_data.get('metadata', {})
                    center_key = 'center_l' if s == 'left' else 'center_r'
                    if meta.get(center_key):
                        d_sm.set_nullpunkt(s, meta[center_key][0], meta[center_key][1])
            
            startmask_name = next((f for f in app.all_files if f"cumulative_startmask_{s}" in f), None)
            if startmask_name:
                startmask_bgr = app.get_img(startmask_name)
                startmask_gray = cv2.cvtColor(startmask_bgr, cv2.COLOR_BGR2GRAY)
                state = d_sm.state_left if s == 'left' else d_sm.state_right
                state.cumulative_mask = startmask_gray

        frame_counts = {'left': 0, 'right': 0}
        for orig_name in app.orig_files:
            img = app.get_img(orig_name)
            s = 'left' if 'left' in orig_name else 'right'
            frame_counts[s] += 1
            curr_frame_num = frame_counts[s]
            
            shots_before = len(d_sm.shots)
            detector.detect_new_shot(img, s)
            shots_after = len(d_sm.shots)
            
            for idx in range(shots_before, shots_after):
                d_sm.shots[idx]['frame_num'] = curr_frame_num

        txt.delete(1.0, tk.END)
        txt.insert(tk.END, f"VERGLEICH: KOMPLETTES MATCH (Aktuelle Slider-Werte vs. Original-JSON)\n")
        txt.insert(tk.END, "="*85 + "\n")

        decimals = d_config.getint('Zielscheibe', 'ringwertung_nachkommastellen', fallback=1)

        def build_side_comparison(side_name, side_char):
            cal_r = detector.get_caliber_radius(side_name) 
            orig_shots = [s for s in app.original_match_data.get("timeline", []) if s.get('s') == side_char]
            curr_shots = [s for s in d_sm.shots if s['side'] == side_name]
            
            if not orig_shots and not curr_shots: return 
            
            txt.insert(tk.END, f"\n--- KAMERA {side_name.upper()} ---\n")
            txt.insert(tk.END, f"Original Treffer: {len(orig_shots)} | Neu berechnet: {len(curr_shots)}\n")
            txt.insert(tk.END, "Legende: 'E' = Manuell editiert | '*' = Methode hat sich zum Original geändert\n")
            
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
                    
                    o_score_str = f"{orig_score:.4f}".rstrip('0')
                    if o_score_str.endswith('.'): o_score_str += "0" 
                    
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
                    
                    o_score_str = f"{orig_score:.4f}".rstrip('0')
                    if o_score_str.endswith('.'): o_score_str += "0"
                        
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

    def export_test_case(self, app):
        if not getattr(app, 'current_zip_path', None) or not getattr(app, 'original_match_data', None) or not app.orig_files:
            messagebox.showwarning("Fehler", "Es ist kein Match geladen, das exportiert werden könnte!")
            return
    
        export_dir = os.path.join(os.getcwd(), "testcases")
        os.makedirs(export_dir, exist_ok=True)
        
        base_name = os.path.basename(app.current_zip_path)
        default_name = base_name.replace(".zip", "_verbessert.zip")
        
        save_path = filedialog.asksaveasfilename(
            initialdir=export_dir,
            initialfile=default_name,
            title="Golden Master Test-Case speichern",
            defaultextension=".zip",
            filetypes=[("ZIP Archive", "*.zip")]
        )
        
        if not save_path:
            return 
            
        d_config = app.package_data['config']
        if d_config.getboolean('Erkennung', 'detail_export_aktiv', fallback=False):
            disable_export = messagebox.askyesno(
                "Performance Warnung",
                "⚠️ Der Parameter 'detail_export_aktiv' ist aktuell EINGESCHALTET.\n\n"
                "Dies verlangsamt die Live-Engine und bläht den Testcase unnötig auf. "
                "Für einen regulären Golden Master sollte dieser Wert 'no' sein.\n\n"
                "Möchtest du den Parameter für diesen Export automatisch deaktivieren?"
            )
            if disable_export:
                d_config.set('Erkennung', 'detail_export_aktiv', 'no')
                try:
                    for key, tk_var in app.registered_sliders.items():
                        if key == 'detail_export_aktiv':
                            tk_var.set(False)
                except Exception:
                    pass
                app.print_log("SYSTEM", "ℹ️ 'detail_export_aktiv' wurde für den Export deaktiviert.")
            
        try:
            d_config = app.package_data['config']
            d_dm = DummyDateiManager(app)
            d_sm = StateManager(d_config, d_dm)
            detector = TargetDetector(d_config, d_dm, d_sm, lambda side, text, show_gui=False: None) 

            for s in ['left', 'right']:
                state = d_sm.state_left if s == 'left' else d_sm.state_right
                if not state:
                    continue 
                    
                ref_name = next((f for f in app.all_files if f"referenz_{s}" in f), None)
                if ref_name:
                    detector.set_reference_image(app.get_img(ref_name), s)
                    if getattr(app, 'original_match_data', None):
                        meta = app.original_match_data.get('metadata', {})
                        center_key = 'center_l' if s == 'left' else 'center_r'
                        if meta.get(center_key):
                            d_sm.set_nullpunkt(s, meta[center_key][0], meta[center_key][1])
                
                startmask_name = next((f for f in app.all_files if f"cumulative_startmask_{s}" in f), None)
                if startmask_name:
                    startmask_gray = cv2.cvtColor(app.get_img(startmask_name), cv2.COLOR_BGR2GRAY)
                    state.cumulative_mask = startmask_gray

            for orig_name in app.orig_files:
                img = app.get_img(orig_name)
                s = 'left' if 'left' in orig_name else 'right'
                detector.detect_new_shot(img, s)
            
            player_l = app.original_match_data.get("metadata", {}).get("spieler", "Schütze 1").split(" / ")[0].strip()
            player_r = app.original_match_data.get("metadata", {}).get("spieler", "Schütze 2").split(" / ")[-1].strip()
            
            new_match_data = d_sm.get_match_data(player_l, player_r)
            
            for i, s in enumerate(new_match_data["timeline"]):
                s["t"] = float(i + 1.0)
                s["edited"] = False

            config_ram = app.package_data.get('config')
            if config_ram:
                string_io = io.StringIO()
                config_ram.write(string_io)
                new_ini_str = string_io.getvalue()
            else:
                new_ini_str = None
                
            is_overwrite = (os.path.abspath(save_path) == os.path.abspath(app.current_zip_path))
                
            success = self.dm.export_match_package(
                filepath=save_path,
                match_data=new_match_data,
                config_string=new_ini_str,
                source_zip=app.current_zip_path,
                apply_diet_filter=True
            )
            
            if success:
                if is_overwrite:
                    app.original_match_data = copy.deepcopy(new_match_data)
                messagebox.showinfo("Erfolg", f"Test-Case erfolgreich gespeichert:\n{os.path.basename(save_path)}")
            else:
                messagebox.showerror("Fehler", "Beim Exportieren ist ein Fehler aufgetreten.")
            
        except Exception as e:
            messagebox.showerror("Fehler", f"Beim Exportieren ist ein Fehler aufgetreten:\n{str(e)}")

    def apply_to_live(self, app):
        if not getattr(app, 'package_data', None):
            messagebox.showwarning("Fehler", "Es ist keine Konfiguration geladen!")
            return

        current_path = getattr(app, 'current_zip_path', '')

        changed_items = [] 
        changed_keys = []
        print("\n" + "="*60)
        print("🔍 [SMART-SAVE DIAGNOSE] Starte Parameter-Abgleich...")
        print("="*60)

        if app.package_data and 'config' in app.package_data:
            config_ram = app.package_data['config']
            
            for section in config_ram.sections():
                for key, curr_val_raw in config_ram.items(section):
                    curr_val = str(curr_val_raw).strip()
                    orig_val = app.get_orig_config_value(section, key, fallback=None)
                    
                    if orig_val is not None:
                        if app.is_config_value_changed(section, key, curr_val):
                            print(f"  🔴 [GEÄNDERT] [{section}] {key} -> Alt: '{orig_val}' | Neu: '{curr_val}'")
                            changed_items.append((section, key, orig_val, curr_val))
                            changed_keys.append(f"[{section}] {key}" if key in ('rgb_r', 'rgb_g', 'rgb_b', 'tolerance', 'min_area_percent', 'cut_top', 'cut_bottom', 'cut_left', 'cut_right') else key)
                        else:
                            print(f"  🟢 [Gleich]   [{section}] {key}")
                    else:
                        print(f"  ⚠️ [Kein Originalwert im Snapshot] [{section}] {key} (Neu angelegt: '{curr_val}')")
                        changed_items.append((section, key, None, curr_val))
                        changed_keys.append(key)

        print("="*60)
        print(f"📋 Endergebnis: {len(changed_items)} geänderte Parameter erkannt -> {changed_keys}")
        print("="*60 + "\n")

        apply_mode = "ALL"
        
        if not current_path:
            titel = "Globale Einstellungen speichern"
            text = "Möchtest du diese Werte direkt in die System-Konfiguration schreiben?\n\n▶ Sie gelten ab sofort als Standard für alle NEUEN Matches.\n\nDas Labor wird danach geschlossen."
            if not messagebox.askyesno(titel, text): return
            
        elif os.path.basename(current_path) == "Live_Tuning_Bridge.zip":
            titel = "Live-System aktualisieren"
            text = "Möchtest du diese Einstellungen an das laufende System am Schießstand senden?\n\n▶ Das aktuelle Match wird sofort damit fortgesetzt.\n▶ Das Labor wird danach geschlossen."
            if not messagebox.askyesno(titel, text): return
            
        else:
            if changed_items:
                titel = "Intelligentes Speichern (Smart-Save)"
                max_len = 99
                changes_text = "\n".join([f"• [{sec}] {k}: {o_v} ➔ {c_v}" if o_v is not None else f"• [{sec}] {k}: {c_v}" for sec, k, o_v, c_v in changed_items[:max_len]])
                if len(changed_items) > max_len:
                    changes_text += f"\n... und {len(changed_items) - max_len} weitere."
                    
                msg = (
                    f"Du betrachtest gerade ein historisches Match-Paket.\n"
                    f"Folgende {len(changed_items)} Parameter hast du im Labor verändert:\n\n"
                    f"{changes_text}\n\n"
                    "Wie möchtest du speichern?\n\n"
                    "[ NUR GEÄNDERTE ] = Überträgt nur die rot markierten Werte in dein Live-System.\n"
                    "[ ALLES ÜBERSCHREIBEN ] = Macht diese historische Config zum neuen globalen Standard."
                )
                
                def custom_prompt():
                    result = tk.StringVar(value="")
                    dlg = tk.Toplevel(app.root)
                    dlg.title(titel)
                    sf = app.root.winfo_fpixels('1i') / 96.0
                    w, h = int(560 * sf), int(420 * sf)
                    dlg.geometry(f"{w}x{h}")
                    dlg.attributes('-topmost', True)
                    dlg.focus_force()
                    
                    btn_frame = tk.Frame(dlg, pady=12, bg="#f0f0f0")
                    btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
                    
                    def set_res(val):
                        result.set(val)
                        dlg.destroy()
                        
                    tk.Button(btn_frame, text="Nur Geänderte", bg="#27ae60", fg="white", font=("Arial", 10, "bold"), command=lambda: set_res("CHANGED")).pack(side=tk.LEFT, padx=15)
                    tk.Button(btn_frame, text="Alles Überschreiben", bg="#e74c3c", fg="white", font=("Arial", 10, "bold"), command=lambda: set_res("ALL")).pack(side=tk.LEFT, padx=15)
                    tk.Button(btn_frame, text="Abbrechen", font=("Arial", 10), command=lambda: set_res("CANCEL")).pack(side=tk.RIGHT, padx=15)
                    
                    text_frame = tk.Frame(dlg)
                    text_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=15, pady=15)
                    
                    scrollbar = ttk.Scrollbar(text_frame, orient="vertical")
                    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                    
                    txt_widget = tk.Text(text_frame, wrap=tk.WORD, font=("Arial", 10), yscrollcommand=scrollbar.set, bg="#fafafa", padx=10, pady=10)
                    txt_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                    scrollbar.config(command=txt_widget.yview)
                    
                    txt_widget.insert(tk.END, msg)
                    txt_widget.config(state=tk.DISABLED) 
                    
                    app.root.wait_window(dlg)
                    return result.get()
                
                choice = custom_prompt()
                if choice == "CANCEL" or choice == "":
                    return
                apply_mode = choice
                
            else:
                titel = "Keine Änderungen erkannt"
                text = (
                    "Du hast im Labor keine Parameter verändert (keine roten Markierungen).\n\n"
                    "Möchtest du die historische Config dieses ZIP-Paketes trotzdem zum neuen globalen Standard machen (Alles überschreiben)?"
                )
                if not messagebox.askyesno(titel, text): return
                apply_mode = "ALL"

        d_config = app.package_data['config']
        if d_config.getboolean('Erkennung', 'detail_export_aktiv', fallback=False):
            disable_export = messagebox.askyesno(
                "Performance Warnung",
                "⚠️ Der Parameter 'detail_export_aktiv' ist aktuell EINGESCHALTET.\n\n"
                "Dies verlangsamt die Maschine am echten Schießstand erheblich!\n\n"
                "Möchtest du den Parameter vor dem Speichern automatisch deaktivieren?"
            )
            if disable_export:
                d_config.set('Erkennung', 'detail_export_aktiv', 'no')
                try:
                    for key, tk_var in app.registered_sliders.items():
                        if key == 'detail_export_aktiv':
                            tk_var.set(False)
                except Exception:
                    pass
                app.print_log("SYSTEM", "ℹ️ 'detail_export_aktiv' wurde für das Live-System deaktiviert.")
            
        try:
            current_path = getattr(app, 'current_zip_path', '')
            export_dir = os.path.join(os.getcwd(), "labor_export")
            os.makedirs(export_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_basename = os.path.basename(current_path).replace(".zip", "") if current_path else "Backup"

            if current_path and os.path.exists(current_path):
                backup_vorher_path = os.path.join(export_dir, f"{safe_basename}_Vorher_{timestamp}.zip")
                shutil.copy2(current_path, backup_vorher_path)

            config_ram = app.package_data.get('config')
            updates = {}
            if config_ram:
                if apply_mode == "CHANGED":
                    disk_config_ram = self.dm.load_or_create_config()
                    for sec, key, _, curr_val in changed_items:
                        val_actual = config_ram.get(sec, key, fallback=curr_val)
                        if not disk_config_ram.has_section(sec):
                            disk_config_ram.add_section(sec)
                        disk_config_ram.set(sec, key, str(val_actual))
                        
                        if sec not in updates:
                            updates[sec] = {}
                        updates[sec][key] = str(val_actual)
                    
                    string_io = io.StringIO()
                    disk_config_ram.write(string_io)
                    new_ini_str = string_io.getvalue()
                    
                else:
                    string_io = io.StringIO()
                    config_ram.write(string_io)
                    new_ini_str = string_io.getvalue()
                    
                    for section in config_ram.sections():
                        updates[section] = {}
                        for key, val in config_ram.items(section):
                            updates[section][key] = str(val)
            else:
                new_ini_str = None
 
            self.dm.update_ini_file_bulk(updates)

            if current_path and os.path.basename(current_path) == "Live_Tuning_Bridge.zip":
                
                d_config = app.package_data['config']  
                d_dm = DummyDateiManager(app)
                d_sm = StateManager(d_config, d_dm)
                detector = TargetDetector(d_config, d_dm, d_sm, lambda side, text, show_gui=False: None)

                for s in ['left', 'right']:
                    state = d_sm.state_left if s == 'left' else d_sm.state_right
                    if not state: 
                        continue
                        
                    ref_name = next((f for f in app.all_files if f"referenz_{s}" in f), None)
                    if ref_name:
                        detector.set_reference_image(app.get_img(ref_name), s)
                        if getattr(app, 'original_match_data', None):
                            meta = app.original_match_data.get('metadata', {})
                            center_key = 'center_l' if s == 'left' else 'center_r'
                            if meta.get(center_key):
                                d_sm.set_nullpunkt(s, meta[center_key][0], meta[center_key][1])
                    
                    startmask_name = next((f for f in app.all_files if f"cumulative_startmask_{s}" in f), None)
                    if startmask_name:
                        startmask_gray = cv2.cvtColor(app.get_img(startmask_name), cv2.COLOR_BGR2GRAY)
                        state.cumulative_mask = startmask_gray

                for orig_name in app.orig_files:
                    s = 'left' if 'left' in orig_name else 'right'
                    temp_state = d_sm.state_left if s == 'left' else d_sm.state_right
                    if not temp_state: 
                        continue
                    detector.detect_new_shot(app.get_img(orig_name), s)

                for img_name, img_data in d_dm.debug_images.items():
                    self.dm.save_debug_image(img_name, img_data)

                if hasattr(self.dm, 'flush_image_queue'):
                    self.dm.flush_image_queue()
                    
                new_match_data = {
                    "metadata": app.original_match_data.get("metadata", {}).copy(),
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
                        "x": round(float(s['pos'][0]), 4),
                        "y": round(float(s['pos'][1]), 4),
                        "a": round(float(s['area']), 1),
                        "score": float(s.get('score', 0.0)),
                        "cv_score": round(float(s.get('cv_score', 0.0)), 1),
                        "winner_method": str(s.get('winner_method', 'Unbekannt')),
                        "edited": False
                    })
                
                backup_nachher_path = os.path.join(export_dir, f"{safe_basename}_Nachher_{timestamp}.zip")
                self.dm.export_match_package(
                    filepath=backup_nachher_path,
                    match_data=new_match_data,
                    source_folder=self.dm.DEBUG_FOLDER,
                    apply_diet_filter=False 
                )

                handover_path = os.path.join(export_dir, "Live_Tuning_Handover.zip")
                self.dm.export_match_package(
                    filepath=handover_path,
                    match_data=new_match_data,
                    source_folder=self.dm.DEBUG_FOLDER,
                    apply_diet_filter=False 
                )
                app.print_log("SYSTEM", "Handover-Paket und Backups erstellt.")

            app.print_log("SYSTEM", "Schließe Labor...")
            app.root.destroy() 

        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("Kritischer Fehler", f"Fehler beim Übernehmen:\n{str(e)}")