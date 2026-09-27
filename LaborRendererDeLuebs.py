import cv2
import numpy as np
import math
from PIL import Image, ImageTk
import time

class LaborRenderer:
    def __init__(self, app):
        self.app = app

    def update_image_display(self, full_rebuild=True, push_to_gui=True):
        """Zeichnet die Bilder. full_rebuild=False nutzt den Cache für extremes Tempo beim Blinken!"""
        if getattr(self.app, 'last_live_img', None) is None: return
        t_start = time.perf_counter() # Präzise Stoppuhr starten

        h, w = self.app.last_live_img.shape[:2]
        
        # =====================================================================
        # ---> SCHICHT 1: DER CACHE (Wird nur bei Zoom/Slider-Änderung berechnet) <---
        # =====================================================================
        if full_rebuild or not hasattr(self.app, 'cached_static_layer'):
            mode = self.app.view_mode_var.get()
            
            def to_bgr(img):
                if img is None: return np.zeros((h, w, 3), dtype=np.uint8)
                if img.shape[:2] != (h, w):
                    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_NEAREST)
                if len(img.shape) == 2: return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                return img

            diff_bgr = to_bgr(self.app.last_diff_img)
            
            if mode == 1:
                right_img = diff_bgr
            elif mode == 2:
                right_img = to_bgr(self.app.last_diff_gesamt_img)
            elif mode == 4: 
                raw = getattr(self.app, 'last_raw_diff', np.zeros((h, w), dtype=np.uint8))
                thresh_raw = getattr(self.app, 'last_thresh_raw', np.zeros((h, w), dtype=np.uint8))
                hist_mask = getattr(self.app, 'last_history_mask', np.zeros((h, w), dtype=np.uint8))
                
                raw_display = raw.copy()
                if hist_mask is not None and cv2.countNonZero(hist_mask) > 0:
                    raw_display[hist_mask > 0] = 0
                    
                optischer_boost = 3.5 
                raw_boosted = np.clip(raw_display.astype(np.float32) * optischer_boost, 0, 255).astype(np.uint8)
                base_gray = cv2.cvtColor(raw_boosted, cv2.COLOR_GRAY2BGR)
                
                if hist_mask is not None and cv2.countNonZero(hist_mask) > 0:
                    new_fragments_raw = cv2.subtract(thresh_raw, hist_mask)
                else:
                    new_fragments_raw = thresh_raw.copy()
                    
                _, new_fragments_raw = cv2.threshold(new_fragments_raw, 127, 255, cv2.THRESH_BINARY)
                
                k_size = self.app.morph_kernel_var.get()
                if k_size > 0:
                    kernel = np.ones((k_size, k_size), np.uint8)
                    new_fragments_morphed = cv2.morphologyEx(new_fragments_raw, cv2.MORPH_CLOSE, kernel)
                else:
                    new_fragments_morphed = new_fragments_raw.copy()

                added_by_morph = cv2.subtract(new_fragments_morphed, new_fragments_raw)
                
                bool_base = new_fragments_raw > 0
                bool_morph = added_by_morph > 0
                
                red_overlay = np.zeros_like(base_gray)
                red_overlay[:,:,2] = np.maximum(raw_boosted, 100) 
                
                blue_overlay = np.zeros_like(base_gray)
                blue_overlay[:,:,0] = 255 
                
                right_img = base_gray.copy()
                right_img[bool_base] = red_overlay[bool_base]
                right_img[bool_morph] = blue_overlay[bool_morph]
                
                abriss_mask = getattr(self.app, 'last_abrisskante', None)
                if abriss_mask is not None:
                    if abriss_mask.shape[:2] != (h, w):
                        abriss_mask = cv2.resize(abriss_mask, (w, h), interpolation=cv2.INTER_NEAREST)
                        
                    bool_abriss = abriss_mask > 0
                    green_overlay = np.zeros_like(base_gray)
                    green_overlay[:,:,1] = 255 
                    right_img[bool_abriss] = green_overlay[bool_abriss]
                    
            elif mode == 5:
                if hasattr(self.app, 'last_clean_live_img'):
                    right_img = self.app.last_clean_live_img.copy()
                else:
                    right_img = np.zeros((h, w, 3), dtype=np.uint8)
            else: 
                ref = to_bgr(self.app.last_ref_img)
                composite = cv2.addWeighted(ref, 0.65, diff_bgr, 0.65, 0)
                
                diff_gesamt = self.app.last_diff_gesamt_img
                if diff_gesamt is not None:
                    if diff_gesamt.shape[:2] != (h, w):
                        diff_gesamt = cv2.resize(diff_gesamt, (w, h), interpolation=cv2.INTER_NEAREST)
                    
                    mask = (cv2.cvtColor(diff_gesamt, cv2.COLOR_BGR2GRAY) < 127) if len(diff_gesamt.shape) == 3 else (diff_gesamt < 127)
                    green_overlay = np.zeros_like(composite)
                    green_overlay[:] = (0, 255, 0)
                    composite[mask] = cv2.addWeighted(composite[mask], 0.5, green_overlay[mask], 0.5, 0)
                    
                right_img = composite

            if mode == 4:
                side = getattr(self.app, 'current_side', self.app.active_camera_var.get())
                current_frame_num = self.app.current_index

                if hasattr(self.app, 'current_engine_shots'):
                    for shot in self.app.current_engine_shots:
                        if shot.get('side') != side: continue
                        if shot.get('labor_frame_num') != current_frame_num: continue
                        winner_method = shot.get('winner_method', '')
                        if "Abriss" not in winner_method: continue

                        bx, by = shot.get('base_pos', (0, 0))
                        ex, ey = shot.get('end_pos', (0, 0))

                        start_pt = (int(round(bx)), int(round(by)))
                        end_pt = (int(round(ex)), int(round(ey)))

                        hellblau = (255, 200, 0) 
                        gruen = (0, 255, 0) 
                        
                        if start_pt != end_pt:
                            cv2.line(right_img, start_pt, end_pt, gruen, 1, cv2.LINE_8) 

                        cv2.circle(right_img, start_pt, 2, hellblau, -1)
                        cv2.circle(right_img, end_pt, 2, hellblau, -1)

            # Zoom-Faktor einrechnen
            self.app.current_scale = (550 / h) * self.app.zoom_factor
            self.app.current_img_w = int(w * self.app.current_scale)
            new_h = int(h * self.app.current_scale)
            
            resized_live = cv2.resize(self.app.last_live_img, (self.app.current_img_w, new_h), interpolation=cv2.INTER_NEAREST)
            resized_right = cv2.resize(right_img, (self.app.current_img_w, new_h), interpolation=cv2.INTER_NEAREST)
            
            combined = np.hstack((resized_live, resized_right))
            
            if getattr(self.app, 'show_target_rings_var', None) and self.app.show_target_rings_var.get():
                meta = getattr(self.app, 'original_match_data', {})
                if meta: meta = meta.get("metadata", {})
                    
                side = self.app.active_camera_var.get()
                center_key = 'center_l' if side == 'left' else 'center_r'
                center_pts = meta.get(center_key)
                
                if center_pts:
                    cx, cy = center_pts
                    d_config = self.app.package_data['config']  
                    aktive_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
                    targets = self.app.dm.load_targets()
                    
                    if aktive_scheibe in targets:
                        target_data = targets[aktive_scheibe]
                        ringe = target_data.get('ringe_durchmesser_mm', {})
                        innenzehner = target_data.get('innenzehner_mm', 0.0)
                        
                        seite_str = "links" if side == 'left' else "rechts"
                        px_x = d_config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
                        px_y = d_config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
                        korrektur = d_config.getfloat('Kameras', f'fischaugenkorrektur_{seite_str}', fallback=0.0) 
                        
                        scaled_cx = round(cx * self.app.current_scale) + self.app.current_img_w
                        scaled_cy = round(cy * self.app.current_scale)
                        ring_color = (255, 255, 0)
                        
                        def draw_dashed_ellipse(img, center, rx, ry, color):
                            for angle in range(1, 361, 6): 
                                cv2.ellipse(img, center, (rx, ry), 0, angle, angle + 2, color, 1, cv2.LINE_8)
                        
                        for ring_name, d_mm in ringe.items():
                            r_mm_base = float(d_mm) / 2.0
                            r_mm_draw = r_mm_base * (1.0 + (r_mm_base * korrektur)) 
                            rx = round((r_mm_draw * px_x) * self.app.current_scale)
                            ry = round((r_mm_draw * px_y) * self.app.current_scale)
                            draw_dashed_ellipse(combined, (scaled_cx, scaled_cy), rx, ry, ring_color)
                            
                        if innenzehner > 0:
                            r_mm_base = float(innenzehner) / 2.0
                            r_mm_draw = r_mm_base * (1.0 + (r_mm_base * korrektur)) 
                            rx = round((r_mm_draw * px_x) * self.app.current_scale)
                            ry = round((r_mm_draw * px_y) * self.app.current_scale)
                            draw_dashed_ellipse(combined, (scaled_cx, scaled_cy), rx, ry, ring_color)
            
                        if '10' in ringe:
                            def draw_orange_ellipse(img, center, rx, ry, color):
                                if rx <= 0 or ry <= 0: return
                                for angle in range(0, 360, 12):
                                    cv2.ellipse(img, center, (rx, ry), 0, angle, angle + 4, color, 1, cv2.LINE_8)
                                    
                            def draw_purple_ellipse(img, center, rx, ry, color):
                                if rx <= 0 or ry <= 0: return
                                for angle in range(6, 360, 12):
                                    cv2.ellipse(img, center, (rx, ry), 0, angle, angle + 4, color, 1, cv2.LINE_8)
                                    
                            color_outer = (0, 165, 255) 
                            color_inner = (82, 4, 87)   
                            
                            sorted_ring_items = sorted(ringe.items(), key=lambda x: int(x[0]))
                            radii_list = [(int(r_name), float(d_val) / 2.0) for r_name, d_val in sorted_ring_items]
                            radii_list.sort(key=lambda x: x[0])
                            
                            for idx in range(len(radii_list) - 1):
                                r_outer_num, r_outer_mm = radii_list[idx]     
                                r_inner_num, r_inner_mm = radii_list[idx+1]   
                                
                                for step in range(1, 10):
                                    fraction = step / 10.0
                                    r_mm_base = r_outer_mm + (r_inner_mm - r_outer_mm) * fraction
                                    r_mm_draw = r_mm_base * (1.0 + (r_mm_base * korrektur)) 
                                    rx = round((r_mm_draw * px_x) * self.app.current_scale)
                                    ry = round((r_mm_draw * px_y) * self.app.current_scale)
                                    draw_orange_ellipse(combined, (scaled_cx, scaled_cy), rx, ry, color_outer)
                            
                            d_10 = float(ringe['10'])
                            kaliber_mm = float(target_data.get('kaliber_mm', 4.5))
                            radius_10_score = (d_10 + kaliber_mm) / 2.0
                            
                            for target_score in [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9]:
                                prozent = (target_score - 10.0) / 0.99
                                r_mm_base = radius_10_score * (1.0 - prozent)
                                if r_mm_base > 0:
                                    r_mm_draw = r_mm_base * (1.0 + (r_mm_base * korrektur)) 
                                    rx = round((r_mm_draw * px_x) * self.app.current_scale)
                                    ry = round((r_mm_draw * px_y) * self.app.current_scale)
                                    draw_purple_ellipse(combined, (scaled_cx, scaled_cy), rx, ry, color_inner)
            
            if getattr(self.app, 'show_orig_hits_var', None) and self.app.show_orig_hits_var.get():
                orig_shots = getattr(self.app, 'last_orig_shots_to_draw', [])
                if orig_shots:
                    base_r = getattr(self.app, 'official_radius_px', 15)
                    scaled_r = round(base_r * self.app.current_scale)
                    
                    for s in orig_shots:
                        hx, hy = s['x'], s['y']
                        scaled_x = round(hx * self.app.current_scale) + self.app.current_img_w
                        scaled_y = round(hy * self.app.current_scale)
                        cv2.circle(combined, (scaled_x, scaled_y), scaled_r, (0, 255, 255), 1, cv2.LINE_8) 
                        cv2.circle(combined, (scaled_x, scaled_y), 1, (0, 255, 255), -1, cv2.LINE_8) 
            
            # ---> DEN FERTIGEN BACKGROUND-CACHE SICHERN <---
            self.app.cached_static_layer = combined.copy()


        # =====================================================================
        # ---> SCHICHT 2: LIVE-OVERLAYS (Wird auf die Kopie des Caches gemalt) <---
        # =====================================================================
        combined = self.app.cached_static_layer.copy()

        if getattr(self.app, 'blink_state', True) and hasattr(self.app, 'current_engine_shots'):
            side = getattr(self.app, 'current_side', self.app.active_camera_var.get())
            current_frame_num = self.app.current_index
            
            d_config = self.app.package_data['config']
            seite_str = "links" if side == 'left' else "rechts"
            px_x = d_config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
            px_y = d_config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
            korrektur = d_config.getfloat('Kameras', f'fischaugenkorrektur_{seite_str}', fallback=0.0)
            
            aktive_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
            ringwertung_aktiv = d_config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
            targets = self.app.dm.load_targets()
            
            if aktive_scheibe in targets and ringwertung_aktiv:
                offizielles_kaliber_mm = float(targets[aktive_scheibe].get('kaliber_mm', 4.5))
            else:
                offizielles_kaliber_mm = d_config.getfloat('Erkennung', 'caliber_durchmesser', fallback=4.5)
            r_shot_mm = offizielles_kaliber_mm / 2.0
            
            meta = getattr(self.app, 'original_match_data', {})
            if meta and "metadata" in meta: meta_dict = meta.get("metadata", {})
            else: meta_dict = meta if isinstance(meta, dict) else {}
            
            center_key = 'center_l' if side == 'left' else 'center_r'
            center_pts = meta_dict.get(center_key)
            
            avg_px = (px_x + px_y) / 2.0
            fallback_r = int(r_shot_mm * avg_px * self.app.current_scale)
            
            for shot in self.app.current_engine_shots:
                if shot.get('side') == side and shot.get('labor_frame_num') == current_frame_num and shot.get('is_new', False):
                    hx, hy = shot['pos']
                    scaled_x1 = round(hx * self.app.current_scale)
                    scaled_y = round(hy * self.app.current_scale)
                    scaled_x2 = scaled_x1 + self.app.current_img_w 
                    
                    if center_pts:
                        cx, cy = center_pts
                        dx_mm = (hx - cx) / px_x
                        dy_mm = (hy - cy) / px_y
                        r_mm = math.hypot(dx_mm, dy_mm)
                        
                        if r_mm > 0.05:
                            angle_deg = math.degrees(math.atan2(dy_mm, dx_mm))
                            scale_radial = 1.0 + (2.0 * r_mm * korrektur)
                            scale_tangential = 1.0 + (r_mm * korrektur)
                            
                            rx = round((r_shot_mm * scale_radial * px_x) * self.app.current_scale)
                            ry = round((r_shot_mm * scale_tangential * px_y) * self.app.current_scale)
                            
                            cv2.ellipse(combined, (scaled_x2, scaled_y), (int(rx), int(ry)), angle_deg, 0, 360, (0, 165, 255), 1, cv2.LINE_8) 
                        else:
                            cv2.circle(combined, (scaled_x2, scaled_y), fallback_r, (0, 165, 255), 1, cv2.LINE_8) 
                    else:
                        cv2.circle(combined, (scaled_x2, scaled_y), fallback_r, (0, 165, 255), 1, cv2.LINE_8) 
                        
                    cv2.circle(combined, (scaled_x2, scaled_y), 1, (0, 0, 0), -1)

        hl = getattr(self.app, 'highlighted_shot', None)
        if hl is not None:
            if time.time() - hl['time'] < 5.0:
                hx, hy = hl['pos']
                f_num = hl['frame']
                
                scaled_x1 = round(hx * self.app.current_scale)
                scaled_y = round(hy * self.app.current_scale)
                
                base_r = getattr(self.app, 'official_radius_px', 15)
                scaled_r = round(base_r * self.app.current_scale)
                scaled_x2 = scaled_x1 + self.app.current_img_w 
                
                color = (255, 50, 200) 
                
                cv2.circle(combined, (scaled_x1, scaled_y), scaled_r, color, 1)
                cv2.circle(combined, (scaled_x1, scaled_y), 4, (0, 0, 0), -1)    
                cv2.circle(combined, (scaled_x1, scaled_y), 2, color, -1)        
                cv2.putText(combined, f"#{f_num}", (scaled_x1 - 25, scaled_y - scaled_r - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 2, cv2.LINE_8) 
                
                cv2.circle(combined, (scaled_x2, scaled_y), scaled_r, color, 1)
                cv2.circle(combined, (scaled_x2, scaled_y), 4, (0, 0, 0), -1)    
                cv2.circle(combined, (scaled_x2, scaled_y), 2, color, -1)        
                cv2.putText(combined, f"#{f_num}", (scaled_x2 - 30, scaled_y - scaled_r - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.5, color, 3, cv2.LINE_8) 
        
        if getattr(self.app, 'calib_mode_active', False) and hasattr(self.app, 'calib_points'):
            for pt in self.app.calib_points:
                scaled_x = round(pt[0] * self.app.current_scale)
                scaled_y = round(pt[1] * self.app.current_scale)
                
                final_x = scaled_x + getattr(self.app, 'pad_x', 0)
                final_y = scaled_y + getattr(self.app, 'pad_y', 0)
                
                cv2.circle(combined, (final_x, final_y), 4, (0, 0, 0), -1)
                cv2.circle(combined, (final_x, final_y), 3, (0, 0, 255), -1)
        
        # Sichert das Bild für das Fadenkreuz
        self.app.base_combined_img = combined.copy()
        
        # Wir konvertieren und cachen das RGB-Bild EINZIGES MAL hier!
        self.app.base_combined_img_rgb = cv2.cvtColor(combined, cv2.COLOR_BGR2RGB)
        
        # ---> DER FIX: Nur an die GUI schicken, wenn es nicht sofort vom Fadenkreuz überschrieben wird! <---
        if push_to_gui:
            img_pil = Image.fromarray(self.app.base_combined_img_rgb)
            self.app.tk_image = ImageTk.PhotoImage(img_pil)
            self.app.lbl_image.config(image=self.app.tk_image, text="")

        ## ---> DIAGNOSE: Stoppuhr auswerten <---
        #t_end = time.perf_counter()
        #dauer_ms = (t_end - t_start) * 1000
        #
        ## Zeige nur an, wenn der Renderer spürbar arbeiten muss (> 50ms)
        #if dauer_ms > 50:
        #    modus = "FULL-REBUILD" if full_rebuild else "QUICK-UPDATE"
        #    # ---> DER FIX: Erst definieren, dann drucken! <---
        #    gui_upload = "+ GUI" if push_to_gui else "(RAM ONLY)"
        #    print(f"🐌 Render-Zyklus [{modus} {gui_upload}]: {dauer_ms:.1f} ms")

    def draw_crosshair(self, x, y):
        # Wir nutzen jetzt den RGB-Cache!
        if getattr(self.app, 'base_combined_img_rgb', None) is None or not hasattr(self.app, 'current_scale'):
            return
            
        temp_img = self.app.base_combined_img_rgb.copy()
        kreis_radius = int(getattr(self.app, 'current_radius_px', 15) * self.app.current_scale) 
        
        # Da das Bild schon RGB ist, ist Cyan = (0, 255, 255) statt (255, 255, 0)!
        neon_cyan_rgb = (0, 255, 255) 
        
        is_left = (x < self.app.current_img_w)
        mirror_x = (x + self.app.current_img_w) if is_left else (x - self.app.current_img_w)
        
        cv2.circle(temp_img, (mirror_x, y), kreis_radius, neon_cyan_rgb, 2)
        cv2.circle(temp_img, (mirror_x, y), 2, neon_cyan_rgb, -1) 

        # ---> NEU: Direkt umwandeln, da schon RGB! <---
        img_pil = Image.fromarray(temp_img)
        self.app.tk_image = ImageTk.PhotoImage(img_pil)
        self.app.lbl_image.config(image=self.app.tk_image)
        
    def draw_zoom_box(self, x1, y1, x2, y2):
        t_start = time.perf_counter() 
        if getattr(self.app, 'base_combined_img_rgb', None) is None: 
            return
            
        temp_img = self.app.base_combined_img_rgb.copy()
        cv2.rectangle(temp_img, (x1, y1), (x2, y2), (255, 255, 0), 1)
        
        img_pil = Image.fromarray(temp_img)
        self.app.tk_image = ImageTk.PhotoImage(img_pil)
        self.app.lbl_image.config(image=self.app.tk_image)
        
        # ---> DER FIX: Wir zwingen Tkinter, das Bild SOFORT auf den Monitor 
        # zu schicken, bevor das nächste Mausevent verarbeitet werden darf! <---
        self.app.root.update_idletasks()
        
        t_end = time.perf_counter()
        dauer_ms = (t_end - t_start) * 1000
        #print("draw_zoom_box time: ", dauer_ms)