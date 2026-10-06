import cv2
import numpy as np
import math
from PIL import Image, ImageTk
import time
from HelperDeLuebs import Helfer

class LaborRenderer:
    def __init__(self, app):
        self.app = app

    def update_image_display(self, full_rebuild=True, push_to_gui=True):
        """Zeichnet die Bilder. full_rebuild=False nutzt den Cache für extremes Tempo beim Blinken!"""
        if getattr(self.app, 'last_live_img', None) is None: return
        t_start = time.perf_counter()

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
            #
            #if mode == 4:
            #    side = getattr(self.app, 'current_side', self.app.active_camera_var.get())
            #    current_frame_num = self.app.current_index
            #
            #    if hasattr(self.app, 'current_engine_shots'):
            #        for shot in self.app.current_engine_shots:
            #            if shot.get('side') != side: continue
            #            if shot.get('labor_frame_num') != current_frame_num: continue
            #            winner_method = shot.get('winner_method', '')
            #            if "Abriss" not in winner_method: continue
            #
            #            bx, by = shot.get('base_pos', (0, 0))
            #            ex, ey = shot.get('end_pos', (0, 0))
            #
            #            start_pt = (int(round(bx)), int(round(by)))
            #            end_pt = (int(round(ex)), int(round(ey)))
            #
            #            hellblau = (255, 200, 0) 
            #            gruen = (0, 255, 0) 
            #            
            #            if start_pt != end_pt:
            #                cv2.line(right_img, start_pt, end_pt, gruen, 1, cv2.LINE_8) 
            #
            #            cv2.circle(right_img, start_pt, 2, hellblau, -1)
            #            cv2.circle(right_img, end_pt, 2, hellblau, -1)
            # Zoom-Faktor einrechnen
            self.app.current_scale = (550 / h) * self.app.zoom_factor
            self.app.current_img_w = int(w * self.app.current_scale)
            new_h = int(h * self.app.current_scale)
            
            resized_live = cv2.resize(self.app.last_live_img, (self.app.current_img_w, new_h), interpolation=cv2.INTER_NEAREST)
            resized_right = cv2.resize(right_img, (self.app.current_img_w, new_h), interpolation=cv2.INTER_NEAREST)
            
            combined = np.hstack((resized_live, resized_right))
            
            # =========================================================================
            # High-Res Abrisskanten-Linien (Knackig scharf auf Monitor-Auflösung) <---
            # =========================================================================
            if mode == 4 and hasattr(self.app, 'current_engine_shots'):
                side = getattr(self.app, 'current_side', self.app.active_camera_var.get())
                current_frame_num = self.app.current_index

                for shot in self.app.current_engine_shots:
                    if shot.get('side') != side: continue
                    if shot.get('labor_frame_num') != current_frame_num: continue
                    winner_method = shot.get('winner_method', '')
                    if "Abriss" not in winner_method: continue

                    # ---> DER FIX: Aufruf der neuen ausgelagerten Funktion (Rechte Bildhälfte -> offset_x) <---
                    self._draw_candidate_vector(combined, shot.get('base_pos'), shot.get('end_pos'), shot['pos'], offset_x=self.app.current_img_w)
            
            # =========================================================================
            # ---> NEU: High-Res Subpixel-Röntgenblick für Modus 2 <---
            # =========================================================================
            if mode == 2 and hasattr(self.app, 'current_engine_shots'):
                side = getattr(self.app, 'current_side', self.app.active_camera_var.get())
                current_frame_num = self.app.current_index

                for shot in self.app.current_engine_shots:
                    if shot.get('side') == side and shot.get('labor_frame_num') == current_frame_num and shot.get('is_new', False):
                        details = shot.get('score_export_details')
                        if details:
                            scale = details.get('scale', 4)
                            off_x = details.get('offset_x', 0)
                            off_y = details.get('offset_y', 0)
                            
                            sub_new = details.get('subpixels_new', [])
                            sub_raw = details.get('subpixels_raw', [])
                            
                            # 1. Raw-Hintergrund zeichnen (Die alten, grauen Schlieren in Dunkelrot)
                            color_raw = (0, 0, 150) # BGR
                            for sx, sy in sub_raw:
                                # Wir rechnen exakt aus, auf welchem Monitor-Pixel das Subpixel beginnt und endet
                                ui_x1 = int(round((off_x + (sx / scale)) * self.app.current_scale)) + self.app.current_img_w
                                ui_y1 = int(round((off_y + (sy / scale)) * self.app.current_scale))
                                ui_x2 = int(round((off_x + ((sx + 1) / scale)) * self.app.current_scale)) + self.app.current_img_w
                                ui_y2 = int(round((off_y + ((sy + 1) / scale)) * self.app.current_scale))
                                cv2.rectangle(combined, (ui_x1, ui_y1), (ui_x2, ui_y2), color_raw, -1)

                            # 2. Neue Riss-Pixel zeichnen (Leuchtend Orange)
                            color_new = (0, 165, 255) # BGR
                            for sx, sy in sub_new:
                                ui_x1 = int(round((off_x + (sx / scale)) * self.app.current_scale)) + self.app.current_img_w
                                ui_y1 = int(round((off_y + (sy / scale)) * self.app.current_scale))
                                ui_x2 = int(round((off_x + ((sx + 1) / scale)) * self.app.current_scale)) + self.app.current_img_w
                                ui_y2 = int(round((off_y + ((sy + 1) / scale)) * self.app.current_scale))
                                cv2.rectangle(combined, (ui_x1, ui_y1), (ui_x2, ui_y2), color_new, -1)
            
            # =========================================================================
            # ---> RENDER-HELFER: Daten sammeln <---
            # =========================================================================
            side = getattr(self.app, 'current_side', self.app.active_camera_var.get())
            seite_str = "links" if side == 'left' else "rechts"
            d_config = self.app.package_data['config']
            px_x = d_config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
            px_y = d_config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
            korrektur = d_config.getfloat('Kameras', f'fischaugenkorrektur_{seite_str}', fallback=0.0)
            
            meta = getattr(self.app, 'original_match_data', {})
            meta_dict = meta.get("metadata", {}) if isinstance(meta, dict) else {}
            center_key = 'center_l' if side == 'left' else 'center_r'
            center_pts = meta_dict.get(center_key)
            fb_cx = center_pts[0] if center_pts else None
            fb_cy = center_pts[1] if center_pts else None
            
            aktive_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
            ringwertung_aktiv = d_config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
            targets = self.app.dm.load_targets()
            
            if aktive_scheibe in targets and ringwertung_aktiv:
                kaliber_mm = float(targets[aktive_scheibe].get('kaliber_mm', 4.5))
            else:
                kaliber_mm = d_config.getfloat('Erkennung', 'caliber_durchmesser', fallback=4.5)
                
            zoom_p = (1.0, self.app.current_img_w / self.app.current_scale, 0.0)

            # ---> RENDER-HELFER: Ringe zeichnen <---
            if getattr(self.app, 'show_target_rings_var', None) and self.app.show_target_rings_var.get():
                if fb_cx is not None and fb_cy is not None:
                    if aktive_scheibe in targets:
                        target_data = targets[aktive_scheibe]
                        ringe = target_data.get('ringe_durchmesser_mm', {})
                        innenzehner = target_data.get('innenzehner_mm', 0.0)
                        
                        ring_color = (255, 255, 0) # Cyan (BGR)
                        
                        # 1. Standard-Ringe (gestrichelt)
                        for ring_name, d_mm in ringe.items():
                            Helfer.draw_smart_ellipse(
                                img=combined, center_x=fb_cx, center_y=fb_cy, radius_mm=float(d_mm)/2.0,
                                color=ring_color, px_x=px_x, px_y=px_y, korrektur=korrektur,
                                feedback_cx=fb_cx, feedback_cy=fb_cy, thickness=1, dashed=True, is_hit=False,
                                zoom_params=zoom_p, scale_x=self.app.current_scale, scale_y=self.app.current_scale
                            )
                        if innenzehner > 0:
                            Helfer.draw_smart_ellipse(
                                img=combined, center_x=fb_cx, center_y=fb_cy, radius_mm=float(innenzehner)/2.0,
                                color=ring_color, px_x=px_x, px_y=px_y, korrektur=korrektur,
                                feedback_cx=fb_cx, feedback_cy=fb_cy, thickness=1, dashed=True, is_hit=False,
                                zoom_params=zoom_p, scale_x=self.app.current_scale, scale_y=self.app.current_scale
                            )
                            
                        # 2. Die dezenten gestrichelten 10tel-Ringe
                        if '10' in ringe:
                            color_outer = (0, 165, 255) # Orange
                            color_inner = (82, 4, 87)   # Purple
                            
                            sorted_ring_items = sorted(ringe.items(), key=lambda x: int(x[0]))
                            radii_list = [(int(r_name), float(d_val) / 2.0) for r_name, d_val in sorted_ring_items]
                            radii_list.sort(key=lambda x: x[0])
                            
                            for idx in range(len(radii_list) - 1):
                                r_outer_num, r_outer_mm = radii_list[idx]     
                                r_inner_num, r_inner_mm = radii_list[idx+1]   
                                
                                for step in range(1, 10):
                                    fraction = step / 10.0
                                    r_mm_base = r_outer_mm + (r_inner_mm - r_outer_mm) * fraction
                                    Helfer.draw_smart_ellipse(
                                        img=combined, center_x=fb_cx, center_y=fb_cy, radius_mm=r_mm_base,
                                        color=color_outer, px_x=px_x, px_y=px_y, korrektur=korrektur,
                                        feedback_cx=fb_cx, feedback_cy=fb_cy, thickness=1, dashed=True, dash_step=12, dash_length=2, is_hit=False,
                                        zoom_params=zoom_p, scale_x=self.app.current_scale, scale_y=self.app.current_scale
                                    )
                            
                            d_10 = float(ringe['10'])
                            kaliber_mm = float(target_data.get('kaliber_mm', 4.5))
                            radius_10_score = (d_10 + kaliber_mm) / 2.0
                            
                            for target_score in [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9]:
                                prozent = (target_score - 10.0) / 0.99
                                r_mm_base = radius_10_score * (1.0 - prozent)
                                if r_mm_base > 0:
                                    Helfer.draw_smart_ellipse(
                                        img=combined, center_x=fb_cx, center_y=fb_cy, radius_mm=r_mm_base,
                                        color=color_inner, px_x=px_x, px_y=px_y, korrektur=korrektur,
                                        feedback_cx=fb_cx, feedback_cy=fb_cy, thickness=1, dashed=True, dash_offset=6, dash_step=12, dash_length=2, is_hit=False,
                                        zoom_params=zoom_p, scale_x=self.app.current_scale, scale_y=self.app.current_scale
                                    )
                            
                        # 3. Bracket-Highlighting (durchgezogene 10tel-Ringe für den neuesten Schuss)
                        current_frame_num = self.app.current_index
                        new_score = None
                        if hasattr(self.app, 'current_engine_shots'):
                            for shot in self.app.current_engine_shots:
                                if shot.get('side') == side and shot.get('labor_frame_num') == current_frame_num and shot.get('is_new', False):
                                    new_score = shot.get('score', 0.0)
                                    break
                                    
                        if new_score is not None and new_score >= 1.0:
                            highlight_color = (255, 110, 255) # Etwas weniger Knalliges Magenta
                            
                            # ---> DER FIX: Die Mathematik spaltet sich bei 10.0 <---
                            if new_score >= 10.0:
                                if '10' in ringe:
                                    d_10 = float(ringe['10'])
                                    radius_10_score = (d_10 + kaliber_mm) / 2.0
                                    
                                    #for step in range(0, 10):
                                    for step in range(1, 10):
                                        target_score = 10.0 + (step / 10.0)
                                        prozent = (target_score - 10.0) / 0.99
                                        r_mm_base = radius_10_score * (1.0 - prozent)
                                        if r_mm_base >= 0:
                                            Helfer.draw_smart_ellipse(
                                                img=combined, center_x=fb_cx, center_y=fb_cy, radius_mm=r_mm_base,
                                                color=highlight_color, px_x=px_x, px_y=px_y, korrektur=korrektur,
                                                feedback_cx=fb_cx, feedback_cy=fb_cy, thickness=1, dashed=False, is_hit=False,
                                                zoom_params=zoom_p, scale_x=self.app.current_scale, scale_y=self.app.current_scale
                                            )
                            else:
                                base_ring = int(math.floor(new_score))
                                str_base = str(base_ring)
                                str_next = str(base_ring + 1)
                                
                                if str_base in ringe:
                                    r_outer = float(ringe[str_base]) / 2.0
                                    if str_next in ringe:
                                        r_inner = float(ringe[str_next]) / 2.0
                                    else:
                                        if str(base_ring - 1) in ringe:
                                            step = (float(ringe[str(base_ring - 1)]) / 2.0) - r_outer
                                            r_inner = max(0.0, r_outer - step)
                                        else:
                                            r_inner = 0.0
                                    
                                    #for i in range(11):
                                    for i in range(1,10):
                                        fraction = i / 10.0
                                        r_draw = r_outer + (r_inner - r_outer) * fraction
                                        Helfer.draw_smart_ellipse(
                                            img=combined, center_x=fb_cx, center_y=fb_cy, radius_mm=r_draw,
                                            color=highlight_color, px_x=px_x, px_y=px_y, korrektur=korrektur,
                                            feedback_cx=fb_cx, feedback_cy=fb_cy, thickness=1, dashed=False, is_hit=False,
                                            zoom_params=zoom_p, scale_x=self.app.current_scale, scale_y=self.app.current_scale
                                        )
            
            # ---> RENDER-HELFER: Gelbe Original-Treffer <---
            if getattr(self.app, 'show_orig_hits_var', None) and self.app.show_orig_hits_var.get():
                orig_shots = getattr(self.app, 'last_orig_shots_to_draw', [])
                if orig_shots:
                    for s in orig_shots:
                        Helfer.draw_smart_ellipse(
                            img=combined, center_x=s['x'], center_y=s['y'], radius_mm=kaliber_mm/2.0,
                            color=(0, 255, 255), px_x=px_x, px_y=px_y, korrektur=korrektur,
                            feedback_cx=fb_cx, feedback_cy=fb_cy, thickness=1, dashed=False, is_hit=True,
                            zoom_params=zoom_p, scale_x=self.app.current_scale, scale_y=self.app.current_scale, draw_center_dot=True
                        )
            
            self.app.cached_static_layer = combined.copy()

        # =====================================================================
        # ---> SCHICHT 2: LIVE-OVERLAYS (Wird auf die Kopie des Caches gemalt) <---
        # =====================================================================
        combined = self.app.cached_static_layer.copy()
        
        # Helfer-Daten auch hier laden (für Overlays)
        side = getattr(self.app, 'current_side', self.app.active_camera_var.get())
        seite_str = "links" if side == 'left' else "rechts"
        d_config = self.app.package_data['config']
        px_x = d_config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
        px_y = d_config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
        korrektur = d_config.getfloat('Kameras', f'fischaugenkorrektur_{seite_str}', fallback=0.0)
        
        meta = getattr(self.app, 'original_match_data', {})
        meta_dict = meta.get("metadata", {}) if isinstance(meta, dict) else {}
        center_key = 'center_l' if side == 'left' else 'center_r'
        center_pts = meta_dict.get(center_key)
        fb_cx = center_pts[0] if center_pts else None
        fb_cy = center_pts[1] if center_pts else None
        
        aktive_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
        ringwertung_aktiv = d_config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
        targets = self.app.dm.load_targets()
        
        if aktive_scheibe in targets and ringwertung_aktiv:
            kaliber_mm = float(targets[aktive_scheibe].get('kaliber_mm', 4.5))
        else:
            kaliber_mm = d_config.getfloat('Erkennung', 'caliber_durchmesser', fallback=4.5)
            
        zoom_p = (1.0, self.app.current_img_w / self.app.current_scale, 0.0)
        current_frame_num = self.app.current_index

        # ---> RENDER-HELFER: Blinkender Live-Treffer <---
        if getattr(self.app, 'blink_state', True) and hasattr(self.app, 'current_engine_shots'):
            for shot in self.app.current_engine_shots:
                if shot.get('side') == side and shot.get('labor_frame_num') == current_frame_num and shot.get('is_new', False):
                    hx, hy = shot['pos']
                    Helfer.draw_smart_ellipse(
                        img=combined, center_x=hx, center_y=hy, radius_mm=kaliber_mm/2.0,
                        #color=(0, 165, 255), px_x=px_x, px_y=px_y, korrektur=korrektur,
                        color=(133, 83, 255), px_x=px_x, px_y=px_y, korrektur=korrektur,  #Neon-Koralle
                        feedback_cx=fb_cx, feedback_cy=fb_cy, thickness=1, dashed=False, is_hit=True,
                        zoom_params=zoom_p, scale_x=self.app.current_scale, scale_y=self.app.current_scale, draw_center_dot=True
                    )

        # Linker Kreis: Der Erkennungs-Durchmesser (config.ini), der auch fürs Fadenkreuz gilt
        base_r = getattr(self.app, 'current_radius_px', 15)

        # ---> RENDER-HELFER: Angeklickter / Hervorgehobener Treffer <---
        hl = getattr(self.app, 'highlighted_shot', None)
        if hl is not None:
            if time.time() - hl['time'] < 5.0:
                hx, hy = hl['pos']
                f_num = hl['frame']
                
                color = (255, 50, 200) # Lila
                
                # Der Subpixel-Multiplikator für perfekte OpenCV Fließkomma-Kreise
                shift = 4
                mult = 2 ** shift
                
                # 1. Linke Seite (Röntgenblick - bleibt als reiner OpenCV-Kreis ohne Linsenverzerrung!)
                base_r = getattr(self.app, 'official_radius_px', 15)
                
                # Exakte Subpixel-Koordinaten für den linken Kreis berechnen
                scaled_x1_sub = int(round(hx * self.app.current_scale * mult))
                scaled_y_sub  = int(round(hy * self.app.current_scale * mult))
                scaled_r1_sub = int(round(base_r * self.app.current_scale * mult))
                
                cv2.circle(combined, (scaled_x1_sub, scaled_y_sub), scaled_r1_sub, color, 1, cv2.LINE_AA, shift=shift)
                cv2.circle(combined, (scaled_x1_sub, scaled_y_sub), 4 * mult, (0, 0, 0), -1, cv2.LINE_AA, shift=shift)    
                cv2.circle(combined, (scaled_x1_sub, scaled_y_sub), 2 * mult, color, -1, cv2.LINE_AA, shift=shift)        
                
                # Text für die linke Seite (braucht keine Subpixel)
                txt_x1 = int(round(hx * self.app.current_scale))
                txt_y  = int(round(hy * self.app.current_scale))
                r1_px  = int(round(base_r * self.app.current_scale))
                cv2.putText(combined, f"#{f_num}", (txt_x1 - 25, txt_y - r1_px - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 2, cv2.LINE_8) 

                # 2. Rechte Seite (Die ungeschönte Wahrheit der Score-Berechnung!)
                echter_score_radius_px = getattr(self.app, 'current_radius_px', 15)
                
                # Exakte Subpixel-Koordinaten für den rechten Kreis berechnen
                scaled_x2_sub = int(round((hx * self.app.current_scale + self.app.current_img_w) * mult))
                scaled_r2_sub = int(round(echter_score_radius_px * self.app.current_scale * mult))
                
                # Der perfekte mathematische OpenCV-Kreis!
                cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), scaled_r2_sub, color, 2, cv2.LINE_AA, shift=shift)
                cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), 4 * mult, (0, 0, 0), -1, cv2.LINE_AA, shift=shift)
                cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), 2 * mult, color, -1, cv2.LINE_AA, shift=shift)
                
                # Text für die rechte Seite
                txt_x2 = int(round(hx * self.app.current_scale)) + self.app.current_img_w
                r2_px  = int(round(echter_score_radius_px * self.app.current_scale))
                cv2.putText(combined, f"#{f_num}", (txt_x2 - 30, txt_y - r2_px - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.5, color, 3, cv2.LINE_8)
        
        # =====================================================================
        # ---> NEU: BATTLE ROYALE VAR - ALLE SCHÜSSE IM FRAME <---
        # =====================================================================
        if getattr(self.app, 'candidate_view_active', False) and hasattr(self.app, 'var_shots'):
            shift = 4
            mult = 2 ** shift
            
            # Linke Seite (Config/Erkennung), Rechte Seite (Config/Erkennung)
            base_r = getattr(self.app, 'current_radius_px', 15)
            echter_score_radius_px = getattr(self.app, 'current_radius_px', 15)
            
            idx = getattr(self.app, 'candidate_idx', 0)
            
            for shot_idx, shot in enumerate(self.app.var_shots):
                candidates = shot['score_export_details']['all_candidates']
                #print(f"candidates: {candidates}")
                # Falls ein Schuss weniger Kandidaten hat, nehmen wir den letzten (Fallback)
                safe_idx = min(idx, len(candidates) - 1)
                cand = candidates[safe_idx]
                
                hx, hy = cand['cx'], cand['cy']
                is_valid = cand['valid']
                
                # Farbe und detaillierten Status festlegen
                if not is_valid:
                    color = (150, 150, 150) # Grau für verworfen
                    status_text = f"VERWORFEN (Riss: {cand.get('cov_new', 0.0):.1f}%)"
                else:
                    # ---> NEU: Prüfen, ob dieser Kandidat der finale Gewinner des Schusses war <---
                    # Wir sichern ab, dass der Name exakt mit der im Schuss gespeicherten winner_method übereinstimmt
                    if cand['name'] == shot.get('winner_method', ''):
                        color = (0, 255, 0) # Leuchtend Grün für den Sieger
                        status_text = "GEWINNER"
                    else:
                        color = (255, 50, 200) # Lila für andere gültige Kandidaten
                        status_text = "OK"
                    
                
                scaled_x1_sub = int(round(hx * self.app.current_scale * mult))
                scaled_y_sub  = int(round(hy * self.app.current_scale * mult))
                scaled_r1_sub = int(round(base_r * self.app.current_scale * mult))
                ## 1. Linke Seite (Röntgenblick - reiner OpenCV Kreis)
                #cv2.circle(combined, (scaled_x1_sub, scaled_y_sub), scaled_r1_sub, color, 1, cv2.LINE_AA, shift=shift)
                #cv2.circle(combined, (scaled_x1_sub, scaled_y_sub), 4 * mult, (0, 0, 0), -1, cv2.LINE_AA, shift=shift)    
                #cv2.circle(combined, (scaled_x1_sub, scaled_y_sub), 2 * mult, color, -1, cv2.LINE_AA, shift=shift)        

                # =====================================================================
                # ---> NEU: Vektordarstellung auf der rechten Seite (nur für Abrisskanten) <---
                # =====================================================================
                if "Abriss" in cand['name']:
                    self._draw_candidate_vector(combined, cand.get('base_pos'), cand.get('end_pos'), (hx, hy), offset_x=self.app.current_img_w)

                # 2. Rechte Seite (Score-Kreis))
                scaled_x2_sub = int(round((hx * self.app.current_scale + self.app.current_img_w) * mult))
                scaled_r2_sub = int(round(echter_score_radius_px * self.app.current_scale * mult))
                
                # =====================================================================
                # ---> NEU: MEC-Kreis für den MinCircle-Kandidaten (RECHTE SEITE) <---
                # =====================================================================
                cand_mec = cand.get('mec_radius')
                if cand_mec is not None and cand_mec > 0:
                    scaled_mec_r = int(round(cand_mec * self.app.current_scale * mult))
                    #mec_color = (0, 0, 150) # Dunkelrot
                    #mec_color = (0, 200, 200) # Gelb
                    mec_color = (255, 100, 100) # Hellblau
                    cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), scaled_mec_r, mec_color, 1, cv2.LINE_AA, shift=shift)
                
                # Linienstärke auf 1px reduziert
                cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), scaled_r2_sub, color, 1, cv2.LINE_AA, shift=shift)
                cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), 4 * mult, (0, 0, 0), -1, cv2.LINE_AA, shift=shift)
                cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), 2 * mult, color, -1, cv2.LINE_AA, shift=shift)
                
                # Text direkt an den Kreis heften
                txt_x2 = int(round(hx * self.app.current_scale)) + self.app.current_img_w   
                txt_y = int(round(hy * self.app.current_scale))                             
                r2_px  = int(round(echter_score_radius_px * self.app.current_scale))
                
                # =====================================================================
                # ---> DER FIX: Text dynamisch über den GRÖSSTEN Kreis schieben! <---
                # =====================================================================
                text_offset_r = r2_px
                if cand_mec is not None and cand_mec > 0:
                    mec_r_px = int(round(cand_mec * self.app.current_scale))
                    text_offset_r = max(r2_px, mec_r_px) # Nimmt automatisch den größeren Radius
                
                # Drei Textzeilen bauen
                line1 = f"S{shot_idx+1}: {cand['score']:.1f} [{safe_idx+1}/{len(candidates)}]"
                line2 = f"{cand['name']}"
                line3 = f"Status: {status_text}"
                
                # Startposition (knapp über dem größten Kreis)
                start_y = txt_y - text_offset_r - 10
                font = cv2.FONT_HERSHEY_SIMPLEX
                
                # =====================================================================
                # ---> DER FIX: Gleiche Linienstärke (thickness=1) verhindert das Auseinanderdriften! <---
                # =====================================================================
                for i, text_line in enumerate([line1, line2, line3]):
                    y_pos = start_y + (i * 15) - 15
                    
                    background = (65, 0, 10)
                    if cand_mec is not None and cand_mec > 0:
                        background = (255, 150, 150) # Hellblaue Outline für den MEC
                        
                    # 1. Der perfekte 1px-Umriss (4x in alle Himmelsrichtungen, IMMER Dicke 1)
                    cv2.putText(combined, text_line, (txt_x2+55 - 49, y_pos-10 ), font,     0.65,     background, 1, cv2.LINE_AA) # Rechts
                    cv2.putText(combined, text_line, (txt_x2+55 - 51, y_pos-10 ), font,     0.65,     background, 1, cv2.LINE_AA) # Links
                    cv2.putText(combined, text_line, (txt_x2+55 - 50, y_pos-10  + 1), font, 0.65,     background, 1, cv2.LINE_AA) # Unten
                    cv2.putText(combined, text_line, (txt_x2+55 - 50, y_pos-10  - 1), font, 0.65,     background, 1, cv2.LINE_AA) # Oben
                    
                    # 2. Der farbige Innentext exakt in der Mitte
                    cv2.putText(combined, text_line, (txt_x2+55 - 50, y_pos-10), font, 0.65, color, 1, cv2.LINE_AA)
        
        ##WAS MACHT DAS HIER???
        if getattr(self.app, 'calib_mode_active', False) and hasattr(self.app, 'calib_points'):
            for pt in self.app.calib_points:
                scaled_x = round(pt[0] * self.app.current_scale)
                scaled_y = round(pt[1] * self.app.current_scale)
                
                final_x = scaled_x + getattr(self.app, 'pad_x', 0)
                final_y = scaled_y + getattr(self.app, 'pad_y', 0)
                
                cv2.circle(combined, (final_x, final_y), 4, (0, 0, 0), -1)
                cv2.circle(combined, (final_x, final_y), 3, (0, 0, 255), -1)
        
        self.app.base_combined_img = combined.copy()
        self.app.base_combined_img_rgb = cv2.cvtColor(combined, cv2.COLOR_BGR2RGB)
        
        if push_to_gui:
            img_pil = Image.fromarray(self.app.base_combined_img_rgb)
            self.app.tk_image = ImageTk.PhotoImage(img_pil)
            self.app.lbl_image.config(image=self.app.tk_image, text="")

        # # ---> DIAGNOSE: Stoppuhr auswerten <---
        # t_end = time.perf_counter()
        # dauer_ms = (t_end - t_start) * 1000
        
        # # Zeige nur an, wenn der Renderer spürbar arbeiten muss (> 50ms)
        # #if dauer_ms > 50:
        # if dauer_ms >   5:
        #     modus = "FULL-REBUILD" if full_rebuild else "QUICK-UPDATE"
        #     # ---> DER FIX: Erst definieren, dann drucken! <---
        #     gui_upload = "+ GUI" if push_to_gui else "(RAM ONLY)"
        #     print(f"🐌 Render-Zyklus [{modus} {gui_upload}]: {dauer_ms:.1f} ms  -  t_end: {t_end}")		

    def draw_crosshair(self, x, y):
        if getattr(self.app, 'base_combined_img_rgb', None) is None or not hasattr(self.app, 'current_scale'):
            return
            
        temp_img = self.app.base_combined_img_rgb.copy()
        kreis_radius = int(getattr(self.app, 'current_radius_px', 15) * self.app.current_scale) 
        
        neon_cyan_rgb = (0, 255, 255) 
        
        is_left = (x < self.app.current_img_w)
        mirror_x = (x + self.app.current_img_w) if is_left else (x - self.app.current_img_w)
        
        cv2.circle(temp_img, (mirror_x, y), kreis_radius, neon_cyan_rgb, 2)
        cv2.circle(temp_img, (mirror_x, y), 2, neon_cyan_rgb, -1) 

        img_pil = Image.fromarray(temp_img)
        self.app.tk_image = ImageTk.PhotoImage(img_pil)
        self.app.lbl_image.config(image=self.app.tk_image)
        
    def _draw_candidate_vector(self, combined_img, base_pos, end_pos, target_pos, offset_x=0):
        """Zeichnet den Vektor (Kante -> Rumpf -> Ziel) für Abrisskanten."""
        if not base_pos or not end_pos or not target_pos: return
        
        bx, by = base_pos
        ex, ey = end_pos
        zx, zy = target_pos

        # Skalieren und den horizontalen Offset für die gewünschte Bildhälfte addieren
        scaled_bx = int(round(bx * self.app.current_scale)) + offset_x
        scaled_by = int(round(by * self.app.current_scale))
        
        scaled_ex = int(round(ex * self.app.current_scale)) + offset_x
        scaled_ey = int(round(ey * self.app.current_scale))
        
        scaled_zx = int(round(zx * self.app.current_scale)) + offset_x
        scaled_zy = int(round(zy * self.app.current_scale))

        kante_pt = (scaled_bx, scaled_by)
        rumpf_pt = (scaled_ex, scaled_ey)
        ziel_pt  = (scaled_zx, scaled_zy)

        hellblau = (255, 200, 0) # BGR (Cyan)
        gruen = (0, 255, 0)      # BGR (Grün)
        
        # Linie zeichnen
        if kante_pt != ziel_pt:
            cv2.line(combined_img, kante_pt, ziel_pt, gruen, 1, cv2.LINE_8) 

        # Die 3 Markierungs-Punkte
        cv2.circle(combined_img, kante_pt, 3, hellblau, -1, cv2.LINE_8) # Startpunkt
        cv2.circle(combined_img, rumpf_pt, 3, hellblau, -1, cv2.LINE_8) # Rumpf 
        cv2.circle(combined_img, ziel_pt, 3, hellblau, -1, cv2.LINE_8)  # Endpunkt

        
    #!!!!!!!!!!!!! EI-KORREKTUR !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    """
        # =========================================================================
        # 🔬 EXPERIMENTELL: 100% physikalisch korrekte Polygon-Verzerrung (Ei-Form)
        # =========================================================================
        # Dieser Code berechnet den optischen Weg für 360 Einzelpunkte.
        # Er ist mathematisch perfekt, aber bei >50 Schüssen zu langsam für flüssiges Panning.
        # Nur bei extremen Verzerrungen oder riesigen Kalibern aktivieren!
        #
        # cx, cy = center_pts
        # dx_mm_obs = (hx - cx) / px_x
        # ... [Hier deinen Raytracing-Code als Backup reinkopieren] ...
        """
    #def _draw_distorted_shot_ellipse(self, img, hx, hy, color, thickness=1):
    #    """Zeichnet einen Schuss 100% physikalisch perfekt linsenkorrigiert als Polygon (Ei-Form)."""
    #    side = self.app.active_camera_var.get()
    #    d_config = self.app.package_data['config']
    #    seite_str = "links" if side == 'left' else "rechts"
    #    
    #    px_x = d_config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
    #    px_y = d_config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
    #    korrektur = d_config.getfloat('Kameras', f'fischaugenkorrektur_{seite_str}', fallback=0.0)
    #    
    #    aktive_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
    #    ringwertung_aktiv = d_config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
    #    targets = self.app.dm.load_targets()
    #    
    #    if aktive_scheibe in targets and ringwertung_aktiv:
    #        offizielles_kaliber_mm = float(targets[aktive_scheibe].get('kaliber_mm', 4.5))
    #    else:
    #        offizielles_kaliber_mm = d_config.getfloat('Erkennung', 'caliber_durchmesser', fallback=4.5)
    #    r_shot_mm = offizielles_kaliber_mm / 2.0
    #    
    #    meta = getattr(self.app, 'original_match_data', {})
    #    if meta and "metadata" in meta: meta_dict = meta.get("metadata", {})
    #    else: meta_dict = meta if isinstance(meta, dict) else {}
    #    
    #    center_key = 'center_l' if side == 'left' else 'center_r'
    #    center_pts = meta_dict.get(center_key)
    #    
    #    # --- Fallback, falls kein Nullpunkt kalibriert wurde ---
    #    if not center_pts:
    #        avg_px = (px_x + px_y) / 2.0
    #        fallback_r = int(r_shot_mm * avg_px * self.app.current_scale)
    #        scaled_x = round(hx * self.app.current_scale) + self.app.current_img_w 
    #        scaled_y = round(hy * self.app.current_scale)
    #        cv2.circle(img, (scaled_x, scaled_y), fallback_r, color, thickness, cv2.LINE_8)
    #        cv2.circle(img, (scaled_x, scaled_y), 1, (0, 0, 0) if color != (0,0,0) else (255,255,255), -1, cv2.LINE_8)
    #        return
    #
    #    cx, cy = center_pts
    #    
    #    # 1. Pixel-Distanz des optischen Zentrums zum Nullpunkt in mm umrechnen
    #    dx_mm_obs = (hx - cx) / px_x
    #    dy_mm_obs = (hy - cy) / px_y
    #    dist_mm_obs = math.hypot(dx_mm_obs, dy_mm_obs)
    #    
    #    # 2. Den WAHREN (physikalischen) Mittelpunkt des Diabolos auf der Pappe ermitteln (P-Q Formel)
    #    if korrektur != 0.0 and dist_mm_obs > 0:
    #        a = korrektur
    #        b = 1.0
    #        c = -dist_mm_obs
    #        diskriminante = b**2 - 4*a*c
    #        if diskriminante >= 0:
    #            dist_mm_true = (-b + math.sqrt(diskriminante)) / (2*a)
    #        else:
    #            dist_mm_true = dist_mm_obs
    #        
    #        # Wahren Vektor skalieren
    #        scale_back = dist_mm_true / dist_mm_obs
    #        real_cx_mm = dx_mm_obs * scale_back
    #        real_cy_mm = dy_mm_obs * scale_back
    #    else:
    #        real_cx_mm = dx_mm_obs
    #        real_cy_mm = dy_mm_obs
    #
    #    # 3. Den physikalisch perfekten Kreis (360 Punkte) erzeugen und JEDEN Punkt verzerren
    #    polygon_points = []
    #    for angle in range(360):
    #        rad = math.radians(angle)
    #        
    #        # Wahrer Rand-Punkt in Millimetern (auf der physikalischen Pappe)
    #        pt_x_mm = real_cx_mm + math.cos(rad) * r_shot_mm
    #        pt_y_mm = real_cy_mm + math.sin(rad) * r_shot_mm
    #        
    #        # Einfallswinkel des Lichts durch die Linse verzerren
    #        r_pt_mm = math.hypot(pt_x_mm, pt_y_mm)
    #        distorted_r = r_pt_mm * (1.0 + r_pt_mm * korrektur)
    #        
    #        scale_fwd = distorted_r / r_pt_mm if r_pt_mm > 0 else 1.0
    #        distorted_x_mm = pt_x_mm * scale_fwd
    #        distorted_y_mm = pt_y_mm * scale_fwd
    #        
    #        # Zurück in Pixel auf dem Sensor
    #        pt_px_x = (distorted_x_mm * px_x) + cx
    #        pt_px_y = (distorted_y_mm * px_y) + cy
    #        
    #        # Für die GUI skalieren und rechts anheften
    #        scaled_x = round(pt_px_x * self.app.current_scale) + self.app.current_img_w
    #        scaled_y = round(pt_px_y * self.app.current_scale)
    #        polygon_points.append([scaled_x, scaled_y])
    #
    #    # 4. Polygon auf den Bildschirm malen
    #    pts_array = np.array(polygon_points, np.int32).reshape((-1, 1, 2))
    #    cv2.polylines(img, [pts_array], isClosed=True, color=color, thickness=thickness, lineType=cv2.LINE_8)
    #    
    #    # Zentrumspunkt (auf dem Kamerasensor)
    #    scaled_hx = round(hx * self.app.current_scale) + self.app.current_img_w
    #    scaled_hy = round(hy * self.app.current_scale)
    #    cv2.circle(img, (scaled_hx, scaled_hy), 1, (0, 0, 0) if color != (0,0,0) else (255,255,255), -1, cv2.LINE_8)