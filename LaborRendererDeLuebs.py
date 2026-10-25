# =========================================================================
# ⚠️ NAMENSKONVENTION FÜR DIESE DATEI (Bitte strikt einhalten!)
# =========================================================================
# Hardware-Referenzen (Welche Linse?): 'cam_left' vs 'cam_right'
# GUI-Referenzen (Wo auf dem Monitor?): 
#   -> 'panel_overview'   (= Linke Monitorhälfte, zeigt das Rohbild)
#   -> 'panel_render'     (= Rechte Monitorhälfte, zeigt Analyse/Diff/Röntgen)
# Verbotene Begriffe: "left_img" oder "right_img" (Verwechslungsgefahr!)
# =========================================================================

import cv2
import numpy as np
import math
from PIL import Image, ImageTk
import time
import tkinter as tk
from HelperDeLuebs import Helfer

class LaborRenderer:
    def __init__(self, app):
        self.app = app

    def update_image_display(self, full_rebuild=True, push_to_gui=True):
        if getattr(self.app, 'last_live_img', None) is None: return
        t_start = time.perf_counter()

        h, w = self.app.last_live_img.shape[:2]
        
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
                panel_render_img = diff_bgr
            elif mode == 2:
                panel_render_img = to_bgr(self.app.last_diff_gesamt_img)
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
                
                panel_render_img = base_gray.copy()
                panel_render_img[bool_base] = red_overlay[bool_base]
                panel_render_img[bool_morph] = blue_overlay[bool_morph]
                
                abriss_mask = getattr(self.app, 'last_abrisskante', None)
                if abriss_mask is not None:
                    if abriss_mask.shape[:2] != (h, w):
                        abriss_mask = cv2.resize(abriss_mask, (w, h), interpolation=cv2.INTER_NEAREST)
                    bool_abriss = abriss_mask > 0
                    green_overlay = np.zeros_like(base_gray)
                    green_overlay[:,:,1] = 255 
                    panel_render_img[bool_abriss] = green_overlay[bool_abriss]
                    
            elif mode == 5:
                if hasattr(self.app, 'last_clean_live_img'):
                    panel_render_img = self.app.last_clean_live_img.copy()
                else:
                    panel_render_img = np.zeros((h, w, 3), dtype=np.uint8)
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
                panel_render_img = composite

##### AB HIER BEGINNT DAS ZOOMEN SO WIE ICH DAS SEHE!!!!! ####

            overview_img = self.app.last_live_img.copy()
            side = getattr(self.app, 'current_side', self.app.active_camera_var.get())
            current_frame_num = self.app.current_index
            
            if hasattr(self.app, 'current_engine_shots') and hasattr(self.app, 'current_radius_px'):
                r_erkennung = self.app.current_radius_px
                for shot in self.app.current_engine_shots:
                    is_current_frame_shot = (shot.get('labor_frame_num') == current_frame_num)
                    if shot.get('side') == side and not is_current_frame_shot:
                        draw_pos = (int(round(shot['pos'][0])), int(round(shot['pos'][1])))
                        cv2.circle(overview_img, draw_pos, r_erkennung, (0, 255, 0), 1)
                        
            if getattr(self.app, 'show_orig_hits_var', None) and self.app.show_orig_hits_var.get():
                r_offiziell = getattr(self.app, 'official_radius_px', 15)
                orig_shots = getattr(self.app, 'last_orig_shots_to_draw', [])
                for s in orig_shots:
                    hx, hy = int(round(s['x'])), int(round(s['y']))
                    cv2.circle(overview_img, (hx, hy), int(round(r_offiziell)), (0, 255, 255), 1)
                    cv2.circle(overview_img, (hx, hy), 1, (0, 255, 255), 0)

            # Combined base layer at ORIGINAL resolution
            combined_orig = np.hstack((overview_img, panel_render_img))
            self.app.cached_static_layer = combined_orig.copy()

        # Get base image at original size
        combined_orig = self.app.cached_static_layer.copy()
        
        # Scaling variables
        self.app.current_scale = (550 / h) * self.app.zoom_factor
        self.app.current_img_w = int(w * self.app.current_scale)
        W_scaled = 2 * self.app.current_img_w
        H_scaled = int(h * self.app.current_scale)
        
        # Viewport Crop
        container_w = self.app.img_container.winfo_width() if hasattr(self.app, 'img_container') else 1200
        container_h = self.app.img_container.winfo_height() if hasattr(self.app, 'img_container') else 800
        pan_x = getattr(self.app, 'pan_x', 0)
        pan_y = getattr(self.app, 'pan_y', 0)
        
        is_hybrid_mode = self.app.zoom_factor > 4.0
        
        if is_hybrid_mode:
            crop_x1 = max(0, -pan_x)
            crop_y1 = max(0, -pan_y)
            crop_x2 = min(W_scaled, -pan_x + container_w)
            crop_y2 = min(H_scaled, -pan_y + container_h)
            
            if crop_x1 >= crop_x2 or crop_y1 >= crop_y2:
                combined = np.full((10, 10, 3), 40, dtype=np.uint8)
                vp_x, vp_y = 0, 0
                self.app.viewport_place_x = pan_x
                self.app.viewport_place_y = pan_y
            else:
                orig_x1 = int(crop_x1 / self.app.current_scale)
                orig_y1 = int(crop_y1 / self.app.current_scale)
                orig_x2 = int(math.ceil(crop_x2 / self.app.current_scale))
                orig_y2 = int(math.ceil(crop_y2 / self.app.current_scale))
                
                orig_x1 = max(0, min(orig_x1, 2 * w - 1))
                orig_y1 = max(0, min(orig_y1, h - 1))
                orig_x2 = max(0, min(orig_x2, 2 * w))
                orig_y2 = max(0, min(orig_y2, h))
                
                orig_crop = combined_orig[orig_y1:orig_y2, orig_x1:orig_x2]
                
                target_w = crop_x2 - crop_x1
                target_h = crop_y2 - crop_y1
                
                if target_w > 0 and target_h > 0:
                    combined = cv2.resize(orig_crop, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
                else:
                    combined = np.full((10, 10, 3), 40, dtype=np.uint8)
                    
                vp_x = crop_x1
                vp_y = crop_y1
                self.app.viewport_place_x = pan_x + crop_x1
                self.app.viewport_place_y = pan_y + crop_y1
        else:
            combined = cv2.resize(combined_orig, (W_scaled, H_scaled), interpolation=cv2.INTER_NEAREST)
            vp_x, vp_y = 0, 0
            self.app.viewport_place_x = pan_x
            self.app.viewport_place_y = pan_y
            
        self.app.last_vp_x = vp_x
        self.app.last_vp_y = vp_y
        vp_x_orig = vp_x / self.app.current_scale
        vp_y_orig = vp_y / self.app.current_scale
        
        # --- Overlays
        side = getattr(self.app, 'current_side', self.app.active_camera_var.get())
        seite_str = "links" if side == 'left' else "rechts"
        d_config = self.app.package_data['config']
        px_x = d_config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
        px_y = d_config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
        korrektur = d_config.getfloat('Kameras', f'linsen_verzerrung_{seite_str}', fallback=0.0)
        korr_r4 = d_config.getfloat('Kameras', f'linsen_verzerrung_{seite_str}_r4', fallback=0.0)
        
        crop_sec = "Crop_Links" if side == 'left' else "Crop_Rechts"
        cam_w = d_config.getint('Kameras', f'cam_width_{seite_str}', fallback=1280)
        cam_h = d_config.getint('Kameras', f'cam_height_{seite_str}', fallback=720)
        cut_l = d_config.getint(crop_sec, 'cut_left', fallback=0)
        cut_t = d_config.getint(crop_sec, 'cut_top', fallback=0)
        off_x = d_config.getint('Kameras', f'lens_offset_x_{seite_str}', fallback=0)
        off_y = d_config.getint('Kameras', f'lens_offset_y_{seite_str}', fallback=0)
        lens_cx = (cam_w / 2.0) - cut_l + off_x
        lens_cy = (cam_h / 2.0) - cut_t + off_y
        
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
            
        config_limit = d_config.getfloat('Kameras', f'linsen_verzerrung_limit_{seite_str}', fallback=0.0)
        r_limit_mm = Helfer.get_r_limit(targets, aktive_scheibe, config_limit_mm=config_limit)
            
        zoom_p_render = (1.0, (self.app.current_img_w / self.app.current_scale) - vp_x_orig, -vp_y_orig)
        zoom_p_overview = (1.0, -vp_x_orig, -vp_y_orig)
        
        
        # ---> RENDER-HELFER: Ringe zeichnen <---
        if getattr(self.app, 'show_target_rings_var', None) and self.app.show_target_rings_var.get() and fb_cx is not None and fb_cy is not None:
            if aktive_scheibe in targets:
                target_data = targets[aktive_scheibe]
                ringe = target_data.get('ringe_durchmesser_mm', {})
                innenzehner = target_data.get('innenzehner_mm', 0.0)
                ring_color = (0, 255, 0)
                
                for ring_name, d_mm in ringe.items():
                    #print(f"🟢 [RENDERER] Zielscheibe Grüner-Ring '{ring_name}': Zentrum=({fb_cx:.2f}, {fb_cy:.2f}), Radius={r_mm:.2f} mm, r_limit_mm={r_limit_mm}mm")
                    Helfer.draw_smart_ellipse(
                        img=combined, center_x=fb_cx, center_y=fb_cy, radius_mm=float(d_mm)/2.0,
                        color=ring_color, px_x=px_x, px_y=px_y, korrektur=korrektur, korr_r4=korr_r4,
                        lens_cx=lens_cx, lens_cy=lens_cy, is_ring=True, thickness=1, dashed=True, is_hit=False,
                        zoom_params=zoom_p_render, scale_x=self.app.current_scale, scale_y=self.app.current_scale, r_limit=r_limit_mm
                    )
                if innenzehner > 0:
                    Helfer.draw_smart_ellipse(
                        img=combined, center_x=fb_cx, center_y=fb_cy, radius_mm=float(innenzehner)/2.0,
                        color=ring_color, px_x=px_x, px_y=px_y, korrektur=korrektur, korr_r4=korr_r4,
                        lens_cx=lens_cx, lens_cy=lens_cy, is_ring=True, thickness=1, dashed=True, is_hit=False,
                        zoom_params=zoom_p_render, scale_x=self.app.current_scale, scale_y=self.app.current_scale, r_limit=r_limit_mm
                    )
                if '10' in ringe:
                    color_outer, color_inner = (0, 165, 255), (82, 4, 87)
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
                                color=color_outer, px_x=px_x, px_y=px_y, korrektur=korrektur, korr_r4=korr_r4,
                                lens_cx=lens_cx, lens_cy=lens_cy, is_ring=True, thickness=1, dashed=True, dash_step=12, dash_length=2, is_hit=False,
                                zoom_params=zoom_p_render, scale_x=self.app.current_scale, scale_y=self.app.current_scale, r_limit=r_limit_mm
                            )
                    
                    d_10 = float(ringe['10'])
                    radius_10_score = (d_10 + kaliber_mm) / 2.0
                    for target_score in [10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9]:
                        prozent = (target_score - 10.0) / 0.99
                        r_mm_base = radius_10_score * (1.0 - prozent)
                        if r_mm_base > 0:
                            Helfer.draw_smart_ellipse(
                                img=combined, center_x=fb_cx, center_y=fb_cy, radius_mm=r_mm_base,
                                color=color_inner, px_x=px_x, px_y=px_y, korrektur=korrektur, korr_r4=korr_r4,
                                lens_cx=lens_cx, lens_cy=lens_cy, is_ring=True, thickness=1, dashed=True, dash_offset=6, dash_step=12, dash_length=2, is_hit=False,
                                zoom_params=zoom_p_render, scale_x=self.app.current_scale, scale_y=self.app.current_scale, r_limit=r_limit_mm
                            )
                        # 3. Bracket-Highlighting (durchgezogene 10tel-Ringe für den neuesten Schuss)                            
                current_frame_num = self.app.current_index
                new_score = None
                if hasattr(self.app, 'current_engine_shots'):
                    for shot in self.app.current_engine_shots:
                        if shot.get('side') == side and shot.get('labor_frame_num') == current_frame_num:
                            new_score = shot.get('score', 0.0)
                            break
                if new_score is not None and new_score >= 1.0:
                    highlight_color = (255, 110, 255)
                    if new_score >= 10.0:
                        if '10' in ringe:
                            radius_10_score = (float(ringe['10']) + kaliber_mm) / 2.0
                            for step in range(1, 10):
                                prozent = (10.0 + (step / 10.0) - 10.0) / 0.99
                                r_mm_base = radius_10_score * (1.0 - prozent)
                                if r_mm_base >= 0:
                                    Helfer.draw_smart_ellipse(
                                        img=combined, center_x=fb_cx, center_y=fb_cy, radius_mm=r_mm_base,
                                        color=highlight_color, px_x=px_x, px_y=px_y, korrektur=korrektur, korr_r4=korr_r4,
                                        lens_cx=lens_cx, lens_cy=lens_cy, is_ring=True, thickness=1, dashed=False, is_hit=False,
                                        zoom_params=zoom_p_render, scale_x=self.app.current_scale, scale_y=self.app.current_scale, r_limit=r_limit_mm
                                    )
                    else:
                        base_ring = int(math.floor(new_score))
                        str_base, str_next = str(base_ring), str(base_ring + 1)
                        if str_base in ringe:
                            r_outer = float(ringe[str_base]) / 2.0
                            if str_next in ringe:
                                r_inner = float(ringe[str_next]) / 2.0
                            else:
                                if str(base_ring - 1) in ringe:
                                    r_inner = max(0.0, r_outer - ((float(ringe[str(base_ring - 1)]) / 2.0) - r_outer))
                                else:
                                    r_inner = 0.0
                            for i in range(1,10):
                                r_draw = r_outer + (r_inner - r_outer) * (i / 10.0)
                                Helfer.draw_smart_ellipse(
                                    img=combined, center_x=fb_cx, center_y=fb_cy, radius_mm=r_draw,
                                    color=highlight_color, px_x=px_x, px_y=px_y, korrektur=korrektur, korr_r4=korr_r4,
                                    lens_cx=lens_cx, lens_cy=lens_cy, is_ring=True, thickness=1, dashed=False, is_hit=False,
                                    zoom_params=zoom_p_render, scale_x=self.app.current_scale, scale_y=self.app.current_scale, r_limit=r_limit_mm
                                )

        current_frame_num = self.app.current_index
        base_r = getattr(self.app, 'current_radius_px', 15)

        if hasattr(self.app, 'current_engine_shots'):
            blink_on = getattr(self.app, 'blink_state', True)
            color_panel_overview = (0, 0, 255) if blink_on else (255, 0, 0)
            color_panel_render = (133, 83, 255)
            for shot in self.app.current_engine_shots:
                if shot.get('side') == side and shot.get('labor_frame_num') == current_frame_num:
                    hx, hy = shot['pos']
                    shift = 4
                    mult = 2 ** shift
                    scaled_hx_live = int(round(hx * self.app.current_scale * mult)) - int(vp_x * mult)
                    scaled_hy_live = int(round(hy * self.app.current_scale * mult)) - int(vp_y * mult)
                    scaled_r_live  = int(round(base_r * self.app.current_scale * mult))
                    cv2.circle(combined, (scaled_hx_live, scaled_hy_live), scaled_r_live, color_panel_overview, 2, cv2.LINE_AA, shift=shift)
                    if blink_on:
                        Helfer.draw_smart_ellipse(
                            img=combined, center_x=hx, center_y=hy, radius_mm=kaliber_mm/2.0,
                            color=color_panel_render, px_x=px_x, px_y=px_y, korrektur=korrektur, korr_r4=korr_r4,
                            lens_cx=lens_cx, lens_cy=lens_cy, thickness=1, dashed=False, is_hit=True,
                            zoom_params=zoom_p_render, scale_x=self.app.current_scale, scale_y=self.app.current_scale, draw_center_dot=True, r_limit=r_limit_mm
                        )
# GELBE KREISE?
        if getattr(self.app, 'show_orig_hits_var', None) and self.app.show_orig_hits_var.get():
            for s in getattr(self.app, 'last_orig_shots_to_draw', []):
                Helfer.draw_smart_ellipse(
                    img=combined, center_x=s['x'], center_y=s['y'], radius_mm=kaliber_mm/2.0,
                    color=(0, 255, 255), px_x=px_x, px_y=px_y, korrektur=korrektur, korr_r4=korr_r4,
                    lens_cx=lens_cx, lens_cy=lens_cy, thickness=1, dashed=False, is_hit=True,
                    zoom_params=zoom_p_render, scale_x=self.app.current_scale, scale_y=self.app.current_scale, draw_center_dot=True, r_limit=r_limit_mm
                )
        # ---> RENDER-HELFER: Angeklickter / Hervorgehobener Treffer <---
        hl = getattr(self.app, 'highlighted_shot', None)
        if hl is not None and time.time() - hl['time'] < 5.0:
            hx, hy = hl['pos']
            f_num = hl['frame']
                # Der Subpixel-Multiplikator für perfekte OpenCV Fließkomma-Kreise
            color = (255, 50, 200)
            shift, mult = 4, 16

                # 1. Linke Seite (Röntgenblick - bleibt als reiner OpenCV-Kreis ohne Linsenverzerrung!)
            base_r = getattr(self.app, 'official_radius_px', 15)
            scaled_x1_sub = int(round(hx * self.app.current_scale * mult)) - int(vp_x * mult)
            scaled_y_sub  = int(round(hy * self.app.current_scale * mult)) - int(vp_y * mult)
            scaled_r1_sub = int(round(base_r * self.app.current_scale * mult))
            
            cv2.circle(combined, (scaled_x1_sub, scaled_y_sub), scaled_r1_sub, color, 1, cv2.LINE_AA, shift=shift)
            cv2.circle(combined, (scaled_x1_sub, scaled_y_sub), 4 * mult, (0, 0, 0), -1, cv2.LINE_AA, shift=shift)    
            cv2.circle(combined, (scaled_x1_sub, scaled_y_sub), 2 * mult, color, -1, cv2.LINE_AA, shift=shift)        
            
            txt_x1 = int(round(hx * self.app.current_scale)) - vp_x
            txt_y  = int(round(hy * self.app.current_scale)) - vp_y
            r1_px  = int(round(base_r * self.app.current_scale))
            cv2.putText(combined, f"#{f_num}", (txt_x1 - 25, txt_y - r1_px - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 2, cv2.LINE_8) 
                # 2. Rechte Seite (Die ungeschönte Wahrheit der Score-Berechnung!)
            echter_score_radius_px = getattr(self.app, 'current_radius_px', 15)
            scaled_x2_sub = int(round((hx * self.app.current_scale + self.app.current_img_w) * mult)) - int(vp_x * mult)
            scaled_r2_sub = int(round(echter_score_radius_px * self.app.current_scale * mult))
            
            cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), scaled_r2_sub, color, 2, cv2.LINE_AA, shift=shift)
            cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), 4 * mult, (0, 0, 0), -1, cv2.LINE_AA, shift=shift)
            cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), 2 * mult, color, -1, cv2.LINE_AA, shift=shift)
            
            txt_x2 = int(round(hx * self.app.current_scale)) + self.app.current_img_w - vp_x
            r2_px  = int(round(echter_score_radius_px * self.app.current_scale))
            cv2.putText(combined, f"#{f_num}", (txt_x2 - 30, txt_y - r2_px - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.5, color, 3, cv2.LINE_8)

        mode = self.app.view_mode_var.get()
        if mode == 4 and hasattr(self.app, 'current_engine_shots'):
            for shot in self.app.current_engine_shots:
                if shot.get('side') != side or shot.get('labor_frame_num') != current_frame_num: continue
                if "Abriss" in shot.get('winner_method', ''):
                    self._draw_candidate_vector(combined, shot.get('base_pos'), shot.get('end_pos'), shot['pos'], offset_x=self.app.current_img_w, vp_x=vp_x, vp_y=vp_y)

        if (mode == 1 or mode == 2) and hasattr(self.app, 'current_engine_shots'):
            for shot in self.app.current_engine_shots:
                if shot.get('side') == side and shot.get('labor_frame_num') == current_frame_num:    
                    details = shot.get('score_export_details')
                    if details:
                        scale = details.get('scale', 4)
                        off_x = details.get('offset_x', 0)
                        off_y = details.get('offset_y', 0)
                        
                        for sx, sy in details.get('subpixels_raw', []):
                            ui_x1 = int(round((off_x + (sx / scale)) * self.app.current_scale)) + self.app.current_img_w - vp_x
                            ui_y1 = int(round((off_y + (sy / scale)) * self.app.current_scale)) - vp_y
                            ui_x2 = int(round((off_x + ((sx + 1) / scale)) * self.app.current_scale)) + self.app.current_img_w - vp_x
                            ui_y2 = int(round((off_y + ((sy + 1) / scale)) * self.app.current_scale)) - vp_y
                            cv2.rectangle(combined, (ui_x1, ui_y1), (ui_x2, ui_y2), (0, 0, 150), -1)

                        for sx, sy in details.get('subpixels_new', []):
                            ui_x1 = int(round((off_x + (sx / scale)) * self.app.current_scale)) + self.app.current_img_w - vp_x
                            ui_y1 = int(round((off_y + (sy / scale)) * self.app.current_scale)) - vp_y
                            ui_x2 = int(round((off_x + ((sx + 1) / scale)) * self.app.current_scale)) + self.app.current_img_w - vp_x
                            ui_y2 = int(round((off_y + ((sy + 1) / scale)) * self.app.current_scale)) - vp_y
                            cv2.rectangle(combined, (ui_x1, ui_y1), (ui_x2, ui_y2), (0, 165, 255), -1)

        if getattr(self.app, 'candidate_view_active', False) and hasattr(self.app, 'var_shots'):
            shift, mult = 4, 16
            echter_score_radius_px = getattr(self.app, 'current_radius_px', 15)
            idx = getattr(self.app, 'candidate_idx', 0)
            
            for shot_idx, shot in enumerate(self.app.var_shots):
                candidates = shot['score_export_details']['all_candidates']
                safe_idx = min(idx, len(candidates) - 1)
                cand = candidates[safe_idx]
                hx, hy = cand['cx'], cand['cy']
                
                if not cand['valid']:
                    color, status_text = (150, 150, 150), f"VERWORFEN (Riss: {cand.get('cov_new', 0.0):.1f}%)"
                else:
                    if cand['name'] == shot.get('winner_method', ''):
                        color, status_text = (0, 255, 0), "GEWINNER"
                    else:
                        color, status_text = (255, 50, 200), "OK"
                    
                if "Abriss" in cand['name']:
                    self._draw_candidate_vector(combined, cand.get('base_pos'), cand.get('end_pos'), (hx, hy), offset_x=self.app.current_img_w, vp_x=vp_x, vp_y=vp_y)

                scaled_x2_sub = int(round((hx * self.app.current_scale + self.app.current_img_w) * mult)) - int(vp_x * mult)
                scaled_y_sub  = int(round(hy * self.app.current_scale * mult)) - int(vp_y * mult)
                scaled_r2_sub = int(round(echter_score_radius_px * self.app.current_scale * mult))
                
                cand_mec = cand.get('mec_radius')
                if cand_mec is not None and cand_mec > 0:
                    cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), int(round(cand_mec * self.app.current_scale * mult)), (255, 100, 100), 1, cv2.LINE_AA, shift=shift)
                
                cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), scaled_r2_sub, color, 1, cv2.LINE_AA, shift=shift)
                cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), 4 * mult, (0, 0, 0), -1, cv2.LINE_AA, shift=shift)
                cv2.circle(combined, (scaled_x2_sub, scaled_y_sub), 2 * mult, color, -1, cv2.LINE_AA, shift=shift)
                
                txt_x2 = int(round(hx * self.app.current_scale)) + self.app.current_img_w - vp_x
                txt_y = int(round(hy * self.app.current_scale)) - vp_y
                r2_px = int(round(echter_score_radius_px * self.app.current_scale))
                
                text_offset_r = max(r2_px, int(round(cand_mec * self.app.current_scale))) if cand_mec else r2_px
                
                start_y = txt_y - text_offset_r - 10
                for i, text_line in enumerate([f"S{shot_idx+1}: {cand['score']:.1f} [{safe_idx+1}/{len(candidates)}]", cand['name'], f"Status: {status_text}"]):
                    y_pos = start_y + (i * 15) - 15
                    background = (255, 150, 150) if cand_mec else (65, 0, 10)
                    cv2.putText(combined, text_line, (txt_x2+55 - 49, y_pos-10 ), cv2.FONT_HERSHEY_SIMPLEX, 0.65, background, 1, cv2.LINE_AA) 
                    cv2.putText(combined, text_line, (txt_x2+55 - 51, y_pos-10 ), cv2.FONT_HERSHEY_SIMPLEX, 0.65, background, 1, cv2.LINE_AA) 
                    cv2.putText(combined, text_line, (txt_x2+55 - 50, y_pos-10 + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.65, background, 1, cv2.LINE_AA) 
                    cv2.putText(combined, text_line, (txt_x2+55 - 50, y_pos-10 - 1), cv2.FONT_HERSHEY_SIMPLEX, 0.65, background, 1, cv2.LINE_AA) 
                    cv2.putText(combined, text_line, (txt_x2+55 - 50, y_pos-10), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 1, cv2.LINE_AA)
        
        if getattr(self.app, 'calib_mode_active', False) and hasattr(self.app, 'calib_points'):
            for pt in self.app.calib_points:
                scaled_x = round(pt[0] * self.app.current_scale)
                scaled_y = round(pt[1] * self.app.current_scale)
                final_x = scaled_x + getattr(self.app, 'pad_x', 0) - vp_x
                final_y = scaled_y + getattr(self.app, 'pad_y', 0) - vp_y
                cv2.circle(combined, (final_x, final_y), 4, (0, 0, 0), -1)
                cv2.circle(combined, (final_x, final_y), 3, (0, 0, 255), -1)
        
        if hasattr(self.app, 'calib_points') and self.app.calib_points:
            linienstaerke_mm, spiegel_mm, neun_mm, sechs_mm, aussen_mm = 0.2, 30.5, 5.5, 20.5, 45.5
            if aktive_scheibe in targets:
                t_data = targets[aktive_scheibe]
                linienstaerke_mm = float(t_data.get('linienstaerke_mm', 0.2))
                spiegel_mm = float(t_data.get('spiegel_durchmesser_mm', 30.5))
                ringe_mm = t_data.get('ringe_durchmesser_mm', {})
                neun_mm = float(ringe_mm.get('9', spiegel_mm * 0.5))
                sechs_mm = float(ringe_mm.get('6', spiegel_mm * 1.5))
                aussen_mm = float(ringe_mm['1']) if '1' in ringe_mm else max([float(v) for v in ringe_mm.values()]) if ringe_mm else spiegel_mm * 2.0

            halbe_linie_mm = linienstaerke_mm / 2.0
            ref_cx = fb_cx if fb_cx is not None else lens_cx
            ref_cy = fb_cy if fb_cy is not None else lens_cy

            for i, pt in enumerate(self.app.calib_points):
                scaled_x = round(pt[0] * self.app.current_scale)
                scaled_y = round(pt[1] * self.app.current_scale)
                final_y = scaled_y + getattr(self.app, 'pad_y', 0) - vp_y
                final_x_left = scaled_x + getattr(self.app, 'pad_x', 0) - vp_x
                for fx in [final_x_left, final_x_left + self.app.current_img_w]:
                    cv2.circle(combined, (fx, final_y), 5, (0, 0, 0), -1)
                    cv2.circle(combined, (fx, final_y), 3, (0, 255, 255), -1)

                if hasattr(self.app, 'package_data') and self.app.package_data and 'config' in self.app.package_data:
                    try:
                        aktiver_linien_offset_mm = 0.0 if i < 8 else halbe_linie_mm
                        # 1. Beide Punkte in echte Millimeter relativ zur Linse entzerren
                        true_cx, true_cy = Helfer.undistort_point_mm(ref_cx, ref_cy, lens_cx, lens_cy, px_x, px_y, korrektur, korr_r4, r_limit_mm)
                        true_klick_x, true_klick_y = Helfer.undistort_point_mm(pt[0], pt[1], lens_cx, lens_cy, px_x, px_y, korrektur, korr_r4, r_limit_mm)
                        dist_klick_mm = math.hypot(true_klick_x - true_cx, true_klick_y - true_cy)

                        if dist_klick_mm > 0:
                            ux, uy = (true_klick_x - true_cx) / dist_klick_mm, (true_klick_y - true_cy) / dist_klick_mm
                            # 2. Wahre Rote Position auf der Papierebene berechnen (Klick + Linienstärke)
                            true_red_x = true_cx + ux * (dist_klick_mm + aktiver_linien_offset_mm)
                            true_red_y = true_cy + uy * (dist_klick_mm + aktiver_linien_offset_mm)
                            # 3. Vorwärts-Verzerrung des roten Punktes zurück auf den Sensor
                            r_true_lens = math.hypot(true_red_x, true_red_y)
                            scale_fwd = Helfer.distort_radius(r_true_lens, korrektur, korr_r4, r_limit=r_limit_mm) / r_true_lens if r_true_lens > 0 else 1.0

                            soll_px_x = lens_cx + true_red_x * scale_fwd * px_x
                            soll_px_y = lens_cy + true_red_y * scale_fwd * px_y

                            m_scaled_x = round(soll_px_x * self.app.current_scale) + getattr(self.app, 'pad_x', 0) - vp_x
                            m_scaled_y = round(soll_px_y * self.app.current_scale) + getattr(self.app, 'pad_y', 0) - vp_y
                            #ring_bez = "Spiegel" if i < 8 else ("9er-Ring" if i < 12 else ("6er-Ring" if i < 16 else "Außenring"))
                            #print(f"🔴 [RENDERER] Kalibrierung Roter-Punkt #{i} ({ring_bez}): Sensor-Pos=({soll_px_x:.2f}, {soll_px_y:.2f}) | UI-Render-Panel=(X:{m_scaled_x_right}, Y:{m_scaled_y})")
                            for mx in [m_scaled_x, m_scaled_x + self.app.current_img_w]:
                                cv2.circle(combined, (mx, m_scaled_y), 3, (0, 0, 255), -1)
                    except Exception: pass
                
        # =========================================================================
        # ---> Optische Linsen-Mitte zur Kontrolle einzeichnen <---
        # =========================================================================
        if getattr(self.app, 'show_target_rings_var', None) and self.app.show_target_rings_var.get() and 'lens_cx' in locals():
            marker_color = (0, 255, 255)
                # 1. panel_overview
            lx_panel = int(round(lens_cx * self.app.current_scale)) - vp_x
            ly_panel = int(round(lens_cy * self.app.current_scale)) - vp_y
                # 2. panel_render
            for lx in [lx_panel, lx_panel + self.app.current_img_w]:
                cv2.drawMarker(combined, (lx, ly_panel), marker_color, markerType=cv2.MARKER_CROSS, markerSize=25, thickness=2, line_type=cv2.LINE_AA)
                cv2.putText(combined, "Linsen-Mitte", (lx + 15, ly_panel - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, marker_color, 2, cv2.LINE_AA)
        
        self.app.base_combined_img = combined.copy()
        self.app.base_combined_img_rgb = cv2.cvtColor(combined, cv2.COLOR_BGR2RGB)
        
        if push_to_gui:
            self.app.tk_image = ImageTk.PhotoImage(Image.fromarray(self.app.base_combined_img_rgb))
            self.app.lbl_image.config(image=self.app.tk_image, text="")
            self.app.lbl_image.place(x=self.app.viewport_place_x, y=self.app.viewport_place_y)
            
            # ---> NEU: Flinkes UI-Vorschaukreuz wieder verstecken, sobald die Engine fertig ist! <---
            if hasattr(self.app, 'preview_cross_overview'):
                for f in self.app.preview_cross_overview + self.app.preview_cross_render:
                    f.place_forget()

         ## ---> DIAGNOSE: Stoppuhr auswerten <---
        #t_end = time.perf_counter()
        #dauer_ms = (t_end - t_start) * 1000
        #
        ## Zeige nur an, wenn der Renderer spürbar arbeiten muss (> 50ms)
        ##if dauer_ms > 50:
        #if dauer_ms >   5:
        #    modus = "FULL-REBUILD" if full_rebuild else "QUICK-UPDATE"
        #    # ---> DER FIX: Erst definieren, dann drucken! <---
        #    gui_upload = "+ GUI" if push_to_gui else "(RAM ONLY)"
        #    print(f"🐌 Render-Zyklus [{modus} {gui_upload}]: {dauer_ms:.1f} ms  -  t_end: {t_end}")	
        
    def draw_crosshair(self, x, y):
        if getattr(self.app, 'base_combined_img_rgb', None) is None or not hasattr(self.app, 'current_scale'): return
        temp_img = self.app.base_combined_img_rgb.copy()
        
        vp_x = getattr(self.app, 'last_vp_x', 0)
        vp_y = getattr(self.app, 'last_vp_y', 0)
        abs_x = x + vp_x
        abs_y = y + vp_y
        
        is_left = (abs_x < self.app.current_img_w)
        real_x = (abs_x if is_left else (abs_x - self.app.current_img_w)) / self.app.current_scale
        real_y = abs_y / self.app.current_scale
        
        side = getattr(self.app, 'current_side', self.app.active_camera_var.get())
        seite_str = "links" if side == 'left' else "rechts"
        
        if getattr(self.app, 'package_data', None) and self.app.package_data.get('config'):
            d_config = self.app.package_data['config']
            px_x = d_config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
            px_y = d_config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
            korrektur, korr_r4 = d_config.getfloat('Kameras', f'linsen_verzerrung_{seite_str}', fallback=0.0), d_config.getfloat('Kameras', f'linsen_verzerrung_{seite_str}_r4', fallback=0.0)
            lens_cx = (d_config.getint('Kameras', f'cam_width_{seite_str}', fallback=1280) / 2.0) - d_config.getint("Crop_Links" if side == 'left' else "Crop_Rechts", 'cut_left', fallback=0) + d_config.getint('Kameras', f'lens_offset_x_{seite_str}', fallback=0)
            lens_cy = (d_config.getint('Kameras', f'cam_height_{seite_str}', fallback=720) / 2.0) - d_config.getint("Crop_Links" if side == 'left' else "Crop_Rechts", 'cut_top', fallback=0) + d_config.getint('Kameras', f'lens_offset_y_{seite_str}', fallback=0)
            aktive_scheibe = d_config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
            targets = self.app.dm.load_targets()
            kaliber_mm = float(targets[aktive_scheibe].get('kaliber_mm', 4.5)) if aktive_scheibe in targets and d_config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False) else d_config.getfloat('Erkennung', 'caliber_durchmesser', fallback=4.5)
            r_limit_mm = Helfer.get_r_limit(targets, aktive_scheibe, config_limit_mm=d_config.getfloat('Kameras', f'linsen_verzerrung_limit_{seite_str}', fallback=0.0))
        else:
            px_x, px_y, korrektur, korr_r4, lens_cx, lens_cy, kaliber_mm, r_limit_mm = 5.0, 5.0, 0.0, 0.0, 640, 360, 4.5, 25.0

        #vp_x_orig = vp_x / self.app.current_scale
        #vp_y_orig = vp_y / self.app.current_scale
        #
        ## 1. Crosshair auf der LINKEN Übersicht zeichnen
        #Helfer.draw_smart_ellipse(
        #    img=temp_img, center_x=real_x, center_y=real_y, radius_mm=kaliber_mm/2.0, color=(0, 0, 255),
        #    px_x=px_x, px_y=px_y, korrektur=korrektur, korr_r4=korr_r4, lens_cx=lens_cx, lens_cy=lens_cy,
        #    thickness=2, dashed=False, is_hit=True, zoom_params=(1.0, -vp_x_orig, -vp_y_orig),
        #    scale_x=self.app.current_scale, scale_y=self.app.current_scale, draw_center_dot=True, r_limit=r_limit_mm
        #)
        #
        ## 2. Crosshair auf der RECHTEN Render-Ansicht zeichnen (Der Klon)
        #mirror_ox = self.app.current_img_w / self.app.current_scale
        #Helfer.draw_smart_ellipse(
        #    img=temp_img, center_x=real_x, center_y=real_y, radius_mm=kaliber_mm/2.0, color=(0, 0, 255),
        #    px_x=px_x, px_y=px_y, korrektur=korrektur, korr_r4=korr_r4, lens_cx=lens_cx, lens_cy=lens_cy,
        #    thickness=2, dashed=False, is_hit=True, zoom_params=(1.0, mirror_ox - vp_x_orig, -vp_y_orig),
        #    scale_x=self.app.current_scale, scale_y=self.app.current_scale, draw_center_dot=True, r_limit=r_limit_mm
        #)
        
        vp_x_orig = vp_x / self.app.current_scale
        vp_y_orig = vp_y / self.app.current_scale
        # ---> FIX: Nur exklusiv spiegeln! Ist die Maus links, zeichne rechts (und umgekehrt)
        mirror_ox = (self.app.current_img_w / self.app.current_scale) if is_left else 0.0
        Helfer.draw_smart_ellipse(
            img=temp_img, center_x=real_x, center_y=real_y, radius_mm=kaliber_mm/2.0, color=(0, 0, 255),
            px_x=px_x, px_y=px_y, korrektur=korrektur, korr_r4=korr_r4, lens_cx=lens_cx, lens_cy=lens_cy,
            thickness=2, dashed=False, is_hit=True, zoom_params=(1.0, mirror_ox - vp_x_orig, -vp_y_orig),
            scale_x=self.app.current_scale, scale_y=self.app.current_scale, draw_center_dot=True, r_limit=r_limit_mm
        )
        
        self.app.tk_image = ImageTk.PhotoImage(Image.fromarray(temp_img))
        self.app.lbl_image.config(image=self.app.tk_image)

    def draw_center_preview(self, cx, cy):
        if not hasattr(self.app, 'current_scale'): return
        if not hasattr(self.app, 'preview_cross_overview'):
            self.app.preview_cross_overview = [tk.Frame(self.app.lbl_image, bg="#FFFF00") for _ in range(2)]
            self.app.preview_cross_render   = [tk.Frame(self.app.lbl_image, bg="#FFFF00") for _ in range(2)]

        vp_x, vp_y = getattr(self.app, 'last_vp_x', 0), getattr(self.app, 'last_vp_y', 0)
        draw_x_overview = int(cx * self.app.current_scale) - vp_x
        draw_y = int(cy * self.app.current_scale) - vp_y
        draw_x_render = draw_x_overview + self.app.current_img_w
        size, thick = 24, 2

        self.app.preview_cross_overview[0].place(x=draw_x_overview - size//2, y=draw_y - thick//2, width=size, height=thick)
        self.app.preview_cross_overview[1].place(x=draw_x_overview - thick//2, y=draw_y - size//2, width=thick, height=size)
        self.app.preview_cross_render[0].place(x=draw_x_render - size//2, y=draw_y - thick//2, width=size, height=thick)
        self.app.preview_cross_render[1].place(x=draw_x_render - thick//2, y=draw_y - size//2, width=thick, height=size)
        for f in self.app.preview_cross_overview + self.app.preview_cross_render: f.lift()

    def draw_zoom_box(self, x1, y1, x2, y2, place_x, place_y):
        if not hasattr(self.app, 'zoom_borders'):
            self.app.zoom_borders = [tk.Frame(self.app.img_container, bg="yellow") for _ in range(4)]
        min_x, max_x = min(x1, x2), max(x1, x2)
        min_y, max_y = min(y1, y2), max(y1, y2)
        t = 2
        w, h = max(t * 2, max_x - min_x), max(t * 2, max_y - min_y)
        draw_x, draw_y = min_x + place_x, min_y + place_y
        
        self.app.zoom_borders[0].place(x=draw_x, y=draw_y, width=w, height=t)
        self.app.zoom_borders[1].place(x=draw_x, y=draw_y + h - t, width=w, height=t)
        self.app.zoom_borders[2].place(x=draw_x, y=draw_y + 2*t, width=t, height=h - 4*t)
        self.app.zoom_borders[3].place(x=draw_x + w - t, y=draw_y + 2*t, width=t, height=h - 4*t)
        for border in self.app.zoom_borders: border.lift()

    def hide_zoom_box(self):
        if hasattr(self.app, 'zoom_borders'):
            for border in self.app.zoom_borders: border.place_forget()
    
    def _draw_candidate_vector(self, combined_img, base_pos, end_pos, target_pos, offset_x=0, vp_x=0, vp_y=0):
        if not base_pos or not end_pos or not target_pos: return
        scaled_bx = int(round(base_pos[0] * self.app.current_scale)) + offset_x - vp_x
        scaled_by = int(round(base_pos[1] * self.app.current_scale)) - vp_y
        scaled_ex = int(round(end_pos[0] * self.app.current_scale)) + offset_x - vp_x
        scaled_ey = int(round(end_pos[1] * self.app.current_scale)) - vp_y
        scaled_zx = int(round(target_pos[0] * self.app.current_scale)) + offset_x - vp_x
        scaled_zy = int(round(target_pos[1] * self.app.current_scale)) - vp_y

        if (scaled_bx, scaled_by) != (scaled_zx, scaled_zy):
            cv2.line(combined_img, (scaled_bx, scaled_by), (scaled_zx, scaled_zy), (0, 255, 0), 1, cv2.LINE_8) 
        for pt in [(scaled_bx, scaled_by), (scaled_ex, scaled_ey), (scaled_zx, scaled_zy)]:
            cv2.circle(combined_img, pt, 3, (255, 200, 0), -1, cv2.LINE_8)



    #def _draw_distorted_shot_ellipse(self, img, hx, hy, color, thickness=1):
    #    """Zeichnet einen Schuss 100% physikalisch perfekt linsenkorrigiert als Polygon (Ei-Form)."""
    #    side = self.app.active_camera_var.get()
    #    d_config = self.app.package_data['config']
    #    seite_str = "links" if side == 'left' else "rechts"
    #    
    #    px_x = d_config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
    #    px_y = d_config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
    #    korrektur = d_config.getfloat('Kameras', f'linsen_verzerrung_{seite_str}', fallback=0.0)
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