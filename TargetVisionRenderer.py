import cv2
import numpy as np
import time
import math
import os

class TargetVisionRenderer:
    def __init__(self, tracker):
        self.tracker = tracker
        
        # --- GUI State & Koordinaten ---
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.pad_x = 0
        self.pad_y = 0
        self.w_left_displayed = 0
        
        self.fps = 0.0
        self.prev_frame_time = time.time()
        
        self.msg_left = "System gestartet. Warte..."
        self.msg_right = "System gestartet. Warte..."
        
        # Button Koordinaten
        self.btn_left_coords = None
        self.btn_right_coords = None
        self.btn_edit_left_coords = None
        self.btn_edit_right_coords = None
        self.btn_center_left_coords = None
        self.btn_center_right_coords = None        
        self.btn_exit_coords = None
        self.btn_hilfe_coords = None
        self.btn_zip_coords = None
        self.btn_highscore_coords = None
        self.btn_save_coords = None
        self.btn_labor_coords = None
        self.btn_rings_coords = None
        
        self.show_all_rings = False
        self.zoom_animation = {'left': None, 'right': None}
        
        # Logo-Daten
        self.logo_rgb_pre = None
        self.logo_alpha = None
        self.logo_inv_alpha = None
        self.logo_h = 0
        self.logo_w = 0
        
        self.refresh_settings()
        self._init_logo()

    def refresh_settings(self):
        """Holt sich frische Anzeige-Parameter aus der Config"""
        config = self.tracker.config
        self.darstellung_ohne_weissabgleich = config.getboolean('Anzeige', 'darstellung_ohne_weissabgleich', fallback=True)
        self.ringwertung_aktiv = config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
        self.serien_gruppierung = config.getint('Anzeige', 'serien_gruppierung', fallback=0)
        self.fischaugenkorrektur_links = config.getfloat('Kameras', 'fischaugenkorrektur_links', fallback=0.0)
        self.fischaugenkorrektur_rechts = config.getfloat('Kameras', 'fischaugenkorrektur_rechts', fallback=0.0)
        self.treffer_zoom = config.getfloat('Anzeige', 'treffer_zoom', fallback=3.0)
        self.treffer_anzeigedauer = config.getfloat('Anzeige', 'treffer_anzeigedauer', fallback=4.0)
        self.nachkommastellen = config.getint('Zielscheibe', 'ringwertung_nachkommastellen', fallback=1)

    def _init_logo(self):
        """Lädt und skaliert das Logo einmalig beim Start"""
        logo_pfad = "logo.png"
        logo_skalierung = 0.65 
        if os.path.exists(logo_pfad):
            logo_img = cv2.imread(logo_pfad, cv2.IMREAD_UNCHANGED)
            if logo_img is not None and logo_img.shape[2] == 4:
                if logo_skalierung != 1.0:
                    new_w = int(logo_img.shape[1] * logo_skalierung)
                    new_h = int(logo_img.shape[0] * logo_skalierung)
                    logo_img = cv2.resize(logo_img, (new_w, new_h), interpolation=cv2.INTER_AREA)

                self.logo_h, self.logo_w = logo_img.shape[:2]
                alpha_kanal = (logo_img[:, :, 3] / 255.0).astype(np.float32)
                self.logo_alpha = np.dstack([alpha_kanal]*3)
                self.logo_inv_alpha = 1.0 - self.logo_alpha
                self.logo_rgb_pre = (logo_img[:, :, :3].astype(np.float32) * self.logo_alpha)
                self.tracker.log("SYSTEM", f"Logo ({self.logo_w}x{self.logo_h}) erfolgreich als Overlay geladen.")

    def trigger_zoom(self, side, frame):
        self.tracker.log("SYSTEM", f"🎬 ZOOM TRIGGER empfangen für {side.upper()}! (Config: {self.treffer_zoom}x)")
        if self.treffer_zoom <= 1.0:
            return
            
        side_shots = self.tracker.sm.get_shots_for_side(side)
        if side_shots:
            latest = side_shots[-1]
            self.zoom_animation[side] = {
                'start_time': time.time(),
                'target_x': latest['pos'][0],
                'target_y': latest['pos'][1],
                'duration': self.treffer_anzeigedauer,
                'max_zoom': self.treffer_zoom,
                'frozen_frame': frame.copy() 
            }

    def set_message(self, side, text):
        if side == 'left' or side == 'SYSTEM':
            self.msg_left = text
        if side == 'right' or side == 'SYSTEM':
            self.msg_right = text

    def enhance_color_for_display(self, frame):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.5, 0, 255) 
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.1, 0, 255) 
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    def draw_camera_overlay(self, view, side, start_x, frame_w, total_h):
        cv2.rectangle(view, (start_x, total_h - 40), (start_x + frame_w, total_h), (30, 30, 30), -1)
        msg = self.msg_left if side == 'left' else self.msg_right
        cv2.putText(view, msg, (start_x + 10, total_h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA)
        
        bx1, by1 = start_x + frame_w - 110, total_h - 35
        bx2, by2 = start_x + frame_w - 10, total_h - 5
        cv2.rectangle(view, (bx1, by1), (bx2, by2), (70, 70, 180), -1)
        cv2.rectangle(view, (bx1, by1), (bx2, by2), (255, 255, 255), 1)
        cv2.putText(view, "Reset", (bx1 + 25, by1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        
        ex1, ey1 = start_x + frame_w - 220, total_h - 35
        ex2, ey2 = start_x + frame_w - 120, total_h - 5
        cv2.rectangle(view, (ex1, ey1), (ex2, ey2), (70, 150, 70), -1)
        cv2.rectangle(view, (ex1, ey1), (ex2, ey2), (255, 255, 255), 1)
        cv2.putText(view, "Edit", (ex1 + 35, ey1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        
        cx1, cy1 = start_x + frame_w - 330, total_h - 35
        cx2, cy2 = start_x + frame_w - 230, total_h - 5
        cv2.rectangle(view, (cx1, cy1), (cx2, cy2), (180, 130, 70), -1) 
        cv2.rectangle(view, (cx1, cy1), (cx2, cy2), (255, 255, 255), 1)
        cv2.putText(view, "Zentrum", (cx1 + 15, cy1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        
        if side == 'left':
            self.btn_left_coords = (bx1, by1, bx2, by2)
            self.btn_edit_left_coords = (ex1, ey1, ex2, ey2)
            self.btn_center_left_coords = (cx1, cy1, cx2, cy2)
        else:
            self.btn_right_coords = (bx1, by1, bx2, by2)
            self.btn_edit_right_coords = (ex1, ey1, ex2, ey2) 
            self.btn_center_right_coords = (cx1, cy1, cx2, cy2)

    # =========================================================================
    # ---> DAS SCHWEIZER TASCHENMESSER: Die universelle Ellipsen-Funktion <---
    # =========================================================================
    def draw_smart_ellipse(self, roi, side, center_x, center_y, radius_mm, color, thickness=1, dashed=False, text=None, text_color=(0,0,0), is_hit=False, zoom_params=(1.0, 0.0, 0.0)):
        """
        Regelt vollautomatisch:
        - Fischaugen-Verzerrung in Bezug auf das Kamerazentrum
        - Cinematic Zoom Matrix (z, ox, oy)
        - Fenster-Skalierung (scale_x, scale_y)
        - Intelligentes Stroke-Alignment (Linienstärke nach innen bei Treffern)
        """
        z, ox, oy = zoom_params
        
        # 1. Den echten Mittelpunkt blitzschnell auf das Monitor-ROI mappen
        draw_cx = int(round((center_x * z + ox) * self.scale_x))
        draw_cy = int(round((center_y * z + oy) * self.scale_y))
        
        # 2. Kalibrierungsdaten holen
        seite_str = "links" if side == 'left' else "rechts"
        px_x = self.tracker.config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
        px_y = self.tracker.config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
        korrektur = self.fischaugenkorrektur_links if side == 'left' else self.fischaugenkorrektur_rechts
        feedback = self.tracker.calib_feedback_left if side == 'left' else self.tracker.calib_feedback_right
        
        # 3. Stroke Alignment (Soll die Linie nur nach innen wachsen?)
        thickness_komp = (thickness / 2.0) if is_hit else 0.0
        
        rx, ry, angle_deg = 0, 0, 0
        
        # 4. Verzerrung berechnen (falls Zentrum kalibriert ist)
        if feedback and 'cx' in feedback and 'cy' in feedback:
            dx_mm = (center_x - feedback['cx']) / px_x
            dy_mm = (center_y - feedback['cy']) / px_y
            r_mm_center = math.hypot(dx_mm, dy_mm)
            
            if r_mm_center > 0.05:
                # ---> Fall A: Das ist ein Treffer (oder Ring), der NICHT im Zentrum liegt <---
                angle_deg = math.degrees(math.atan2(dy_mm, dx_mm))
                scale_radial = 1.0 + (2.0 * r_mm_center * korrektur)
                scale_tangential = 1.0 + (r_mm_center * korrektur)
                
                rx_raw = (radius_mm * scale_radial * px_x) * z * self.scale_x
                ry_raw = (radius_mm * scale_tangential * px_y) * z * self.scale_y
            else:
                # ---> DER FIX (Fall B): Objekt liegt EXAKT im optischen Zentrum! <---
                # Sein Radius muss trotzdem nach außen hin wachsen/verzerrt werden.
                angle_deg = 0
                r_mm_draw = radius_mm * (1.0 + (radius_mm * korrektur))
                
                rx_raw = (r_mm_draw * px_x) * z * self.scale_x
                ry_raw = (r_mm_draw * px_y) * z * self.scale_y

            rx = int(round(rx_raw - thickness_komp))
            ry = int(round(ry_raw - thickness_komp))
        else:
            # Fallback (Keine Kalibrierung)
            avg_px = (px_x + px_y) / 2.0
            r_raw = (radius_mm * avg_px) * z * self.scale_x
            rx = ry = int(round(r_raw - thickness_komp))
            
        # Sicherheitssperre, damit es nicht crasht, wenn der Radius winzig wird
        rx, ry = max(2, rx), max(2, ry)
        
        # 5. Zeichnen!
        if dashed:
            for angle in range(0, 360, 6):
                cv2.ellipse(roi, (draw_cx, draw_cy), (rx, ry), angle_deg, angle, angle + 2, color, thickness, cv2.LINE_AA)
        else:
            if rx == ry and angle_deg == 0:
                cv2.circle(roi, (draw_cx, draw_cy), rx, color, thickness, cv2.LINE_AA)
            else:
                cv2.ellipse(roi, (draw_cx, draw_cy), (rx, ry), angle_deg, 0, 360, color, thickness, cv2.LINE_AA)
                
        # 6. Text zentrieren (Falls übergeben)
        if text:
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            text_thick = 1
            
            (text_w, text_h), _ = cv2.getTextSize(text, font, font_scale, text_thick)
            text_x = draw_cx - (text_w // 2)
            text_y = draw_cy + (text_h // 2)
            
            cv2.putText(roi, text, (text_x, text_y), font, font_scale, (0, 0, 0), text_thick + 2, cv2.LINE_AA)
            cv2.putText(roi, text, (text_x, text_y), font, font_scale, text_color, text_thick, cv2.LINE_AA)
            
    # =========================================================================

    def update_gui(self, frame_l, frame_r, blink_state):
        def prepare_disp(f, use_cam):
            if not use_cam or f is None: return f
            if self.darstellung_ohne_weissabgleich:
                return self.enhance_color_for_display(f)
            return f

        disp_l_live = prepare_disp(frame_l, self.tracker.nutze_kamera_links)
        disp_r_live = prepare_disp(frame_r, self.tracker.nutze_kamera_rechts)
        
        anim_l = self.zoom_animation.get('left')
        disp_l_frozen = prepare_disp(anim_l['frozen_frame'], self.tracker.nutze_kamera_links) if (anim_l and anim_l.get('frozen_frame') is not None) else disp_l_live
            
        anim_r = self.zoom_animation.get('right')
        disp_r_frozen = prepare_disp(anim_r['frozen_frame'], self.tracker.nutze_kamera_rechts) if (anim_r and anim_r.get('frozen_frame') is not None) else disp_r_live
            
        frames_to_stack = []
        
        ref_h, ref_w = 480, 640
        if disp_l_live is not None: ref_h, ref_w = disp_l_live.shape[:2]
        elif disp_r_live is not None: ref_h, ref_w = disp_r_live.shape[:2]

        def create_dummy_frame(side_name):
            dummy = np.zeros((ref_h, ref_w, 3), dtype=np.uint8)
            text = f"KAMERA GETRENNT ({side_name})"
            cv2.putText(dummy, text, (30, ref_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)
            return dummy

        zoom_params = {'left': (1.0, 0.0, 0.0), 'right': (1.0, 0.0, 0.0)}
        
        def apply_cinematic_zoom(side_str, disp_frozen, disp_live):
            anim = self.zoom_animation.get(side_str)
            if not anim or disp_frozen is None: return disp_live, 1.0, 0.0, 0.0
            
            elapsed = time.time() - anim['start_time']
            dur = anim['duration']
            
            if elapsed >= dur:
                self.zoom_animation[side_str] = None
                return disp_live, 1.0, 0.0, 0.0
                
            t_pre_pause = 1.0 if dur >= 2.0 else dur * 0.05
            t_in = 1.5 if dur >= 2.0 else dur * 0.15
            t_out = 1.2 if dur >= 2.0 else dur * 0.15
            t_pause = 0.75 if dur >= 2.0 else dur * 0.1
            t_fade = 0.75 if dur >= 2.0 else dur * 0.1
            
            t_in_end = t_pre_pause + t_in
            t_hold_end = dur - t_out - t_pause - t_fade
            t_out_end = dur - t_pause - t_fade
            t_pause_end = dur - t_fade
            
            z = 1.0
            ease = 0.0
            alpha_frozen = 1.0 
            
            if elapsed <= t_pre_pause:
                ease = 0.0
            elif elapsed <= t_in_end:
                progress = (elapsed - t_pre_pause) / t_in
                ease = progress * progress * (3 - 2 * progress)
            elif elapsed <= t_hold_end:
                ease = 1.0
            elif elapsed <= t_out_end:
                progress = 1.0 - ((elapsed - t_hold_end) / t_out)
                ease = progress * progress * (3 - 2 * progress)
            elif elapsed <= t_pause_end:
                ease = 0.0
            else:
                ease = 0.0
                fade_progress = (elapsed - t_pause_end) / t_fade
                alpha_frozen = max(0.0, 1.0 - fade_progress)
                
            z = 1.0 + (anim['max_zoom'] - 1.0) * ease
            
            if z <= 1.001 and alpha_frozen == 1.0:
                return disp_frozen, 1.0, 0.0, 0.0
            elif alpha_frozen < 1.0:
                if disp_live is not None and disp_frozen.shape == disp_live.shape:
                    blended = cv2.addWeighted(disp_frozen, alpha_frozen, disp_live, 1.0 - alpha_frozen, 0)
                    return blended, 1.0, 0.0, 0.0
                return disp_live, 1.0, 0.0, 0.0
                
            h, w = disp_frozen.shape[:2]
            scx, scy = w / 2.0, h / 2.0
            ccx = scx + (anim['target_x'] - scx) * ease
            ccy = scy + (anim['target_y'] - scy) * ease
            ox = w / 2.0 - z * ccx
            oy = h / 2.0 - z * ccy
            
            M = np.float32([[z, 0, ox], [0, z, oy]])
            disp_img = cv2.warpAffine(disp_frozen, M, (w, h), flags=cv2.INTER_LINEAR)
                
            return disp_img, z, ox, oy

        if self.tracker.nutze_kamera_links:
            disp_l, zl, oxl, oyl = apply_cinematic_zoom('left', disp_l_frozen, disp_l_live)
            zoom_params['left'] = (zl, oxl, oyl)
            frames_to_stack.append(disp_l if disp_l is not None else create_dummy_frame("LINKS"))
        
        if self.tracker.nutze_kamera_rechts:
            disp_r, zr, oxr, oyr = apply_cinematic_zoom('right', disp_r_frozen, disp_r_live)
            zoom_params['right'] = (zr, oxr, oyr)
            frames_to_stack.append(disp_r if disp_r is not None else create_dummy_frame("RECHTS"))

        if not frames_to_stack: return

        max_h = max([f.shape[0] for f in frames_to_stack])
        padded_frames = []
        for f in frames_to_stack:
            h, w = f.shape[:2]
            if h < max_h:
                pad = np.zeros((max_h, w, 3), dtype=np.uint8)
                pad[0:h, 0:w] = f
                padded_frames.append(pad)
            else:
                padded_frames.append(f)
                
        combined_view = np.hstack(padded_frames)
        orig_h, orig_w = combined_view.shape[:2]
        
        self.w_left_displayed = frames_to_stack[0].shape[1] if self.tracker.nutze_kamera_links else 0
        
        self.scale_x, self.scale_y = 1.0, 1.0
        try:
            rect = cv2.getWindowImageRect(self.tracker.window_name)
            if rect[2] > 0 and rect[3] > 0:
                win_w, win_h = rect[2], rect[3]
                scale = min(win_w / orig_w, win_h / orig_h)
                
                new_w = int(orig_w * scale)
                new_h = int(orig_h * scale)
                
                resized_view = cv2.resize(combined_view, (new_w, new_h))
                canvas = np.full((win_h, win_w, 3), (35, 35, 35), dtype=np.uint8)
                
                x_offset = (win_w - new_w) // 2
                y_offset = (win_h - new_h) // 2
                
                canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized_view
                
                combined_view = canvas
                self.scale_x = scale
                self.scale_y = scale
                self.pad_x = x_offset 
                self.pad_y = y_offset
            else:
                win_w, win_h = orig_w, orig_h
                self.pad_x = 0
                self.pad_y = 0
        except Exception:
            win_w, win_h = orig_w, orig_h
            self.pad_x = 0
            self.pad_y = 0
            
        scaled_w_left = int(self.w_left_displayed * self.scale_x)
        new_h = int(orig_h * self.scale_y)
        
        camera_rois = {}
        
        if self.tracker.nutze_kamera_links:
            rx = self.pad_x
            rw = scaled_w_left
            camera_rois['left'] = combined_view[self.pad_y : self.pad_y + new_h, rx : rx + rw]
            
        if self.tracker.nutze_kamera_rechts:
            rx = self.pad_x + scaled_w_left if self.tracker.nutze_kamera_links else self.pad_x
            rw = int((orig_w - self.w_left_displayed) * self.scale_x)
            camera_rois['right'] = combined_view[self.pad_y : self.pad_y + new_h, rx : rx + rw]

        # =========================================================================
        # ---> AB HIER WIRD AUFGERÄUMT GEZEICHNET! <---
        # =========================================================================
        for side in ['left', 'right']:
            if side not in camera_rois: continue 
            roi = camera_rois[side]
            
            aktive_scheibe = self.tracker.config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
            targets = self.tracker.dm.load_targets() 
            
            if self.ringwertung_aktiv and aktive_scheibe in targets:
                kaliber_mm = float(targets[aktive_scheibe].get('kaliber_mm', 4.5))
            else:
                kaliber_mm = self.tracker.config.getfloat('Erkennung', 'caliber_durchmesser', fallback=4.5)
            
            # 1. SHOTS (TREFFER) ZEICHNEN
            side_shots = self.tracker.sm.get_shots_for_side(side)
            for idx, shot in enumerate(side_shots):
                x, y = shot['pos']
                color = (0, 0, 255) if (shot.get('is_new', False) and blink_state) else (255, 100, 0)
                
                id_str = None
                text_color = (0, 0, 0)
                if self.ringwertung_aktiv:
                    id_str = str(idx + 1)
                    text_color = (255, 255, 255) if not shot.get('is_new', False) else (200, 200, 255)
                    
                self.draw_smart_ellipse(
                    roi=roi, side=side, center_x=x, center_y=y, 
                    radius_mm=kaliber_mm / 2.0, color=color, thickness=2, 
                    dashed=False, text=id_str, text_color=text_color, 
                    is_hit=True, zoom_params=zoom_params[side]
                )

        # 2. CALIBRATION FEEDBACK (15s Ansicht)
        current_time = time.time()
        for s, feedback in [('left', self.tracker.calib_feedback_left), ('right', self.tracker.calib_feedback_right)]:
            if feedback and (current_time - feedback['time'] < 15.0) and s in camera_rois:
                roi = camera_rois[s]
                z, ox, oy = zoom_params[s]
                
                # Der optische Mittelpunkt
                draw_cx = int(round((feedback['cx'] * z + ox) * self.scale_x))
                draw_cy = int(round((feedback['cy'] * z + oy) * self.scale_y))
                
                # Der DEBUG-Kreis (Rot) - Pixelbasiert!
                if feedback.get('show_red', False) or feedback.get('show_red') == True:
                    draw_red_cx = int(round((feedback['red_cx'] * z + ox) * self.scale_x))
                    draw_red_cy = int(round((feedback['red_cy'] * z + oy) * self.scale_y))
                    fb_red_rx = int(round(feedback['red_rx'] * z * self.scale_x))
                    fb_red_ry = int(round(feedback['red_ry'] * z * self.scale_y))
                    
                    if fb_red_rx > 0 and fb_red_ry > 0:
                        for angle in range(0, 360, 6):
                            cv2.ellipse(roi, (draw_red_cx, draw_red_cy), (fb_red_rx, fb_red_ry), 0, angle, angle + 2, (0, 0, 255), 1, cv2.LINE_AA)
                
                # Zwei äußerste Ringe zur Kontrolle einblenden
                aktive_scheibe = self.tracker.config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
                targets = self.tracker.dm.load_targets()
                
                if aktive_scheibe in targets:
                    target_data = targets[aktive_scheibe]
                    
                    # ---> DER FIX: Den Spiegel wieder zeichnen! <---
                    spiegel_mm = float(target_data.get('spiegel_durchmesser_mm', 30.5))
                    self.draw_smart_ellipse(roi, s, feedback['cx'], feedback['cy'], spiegel_mm / 2.0, (0, 255, 0), thickness=1, dashed=True, is_hit=False, zoom_params=zoom_params[s])
                    
                    ringe = target_data.get('ringe_durchmesser_mm', {})
                    if ringe:
                        alle_durchmesser = sorted([float(d) for d in ringe.values()], reverse=True)
                        for d_mm in alle_durchmesser[:2]: # Die zwei größten
                            self.draw_smart_ellipse(roi, s, feedback['cx'], feedback['cy'], d_mm / 2.0, (0, 255, 0), thickness=1, dashed=True, is_hit=False, zoom_params=zoom_params[s])
                else:
                    # Fallback (Ideal-Ringe aus Pixeln, falls keine JSON geladen ist)
                    fb_ideal_rx = int(round(feedback['ideal_rx'] * z * self.scale_x))
                    fb_ideal_ry = int(round(feedback['ideal_ry'] * z * self.scale_y))
                    if fb_ideal_rx > 0 and fb_ideal_ry > 0:
                        for angle in range(0, 360, 6):
                            cv2.ellipse(roi, (draw_cx, draw_cy), (fb_ideal_rx, fb_ideal_ry), 0, angle, angle + 2, (0, 255, 0), 1, cv2.LINE_AA)

                # Zentrum-Kreuzchen (Manuell, da es keine Ellipse ist)
                cross_size = 6
                cv2.line(roi, (draw_cx - cross_size, draw_cy), (draw_cx + cross_size, draw_cy), (0, 255, 0), 1, cv2.LINE_AA)
                cv2.line(roi, (draw_cx, draw_cy - cross_size), (draw_cx, draw_cy + cross_size), (0, 255, 0), 1, cv2.LINE_AA)
        
        # 3. DAUERHAFTE ZIELSCHEIBEN-RINGE
        if self.show_all_rings:
            for s, fb in [('left', self.tracker.calib_feedback_left), ('right', self.tracker.calib_feedback_right)]:
                if s in camera_rois and fb:
                    roi = camera_rois[s]
                    aktive_scheibe = self.tracker.config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
                    targets = self.tracker.dm.load_targets()
                    if aktive_scheibe in targets:
                        target_data = targets[aktive_scheibe]
                        ringe = target_data.get('ringe_durchmesser_mm', {})
                        innenzehner = target_data.get('innenzehner_mm', 0.0)
                        
                        for ring_name, d_mm in ringe.items():
                            self.draw_smart_ellipse(roi, s, fb['cx'], fb['cy'], float(d_mm) / 2.0, (0, 255, 0), thickness=1, dashed=True, is_hit=False, zoom_params=zoom_params[s])
                            
                        if innenzehner > 0:
                            self.draw_smart_ellipse(roi, s, fb['cx'], fb['cy'], float(innenzehner) / 2.0, (0, 255, 0), thickness=1, dashed=True, is_hit=False, zoom_params=zoom_params[s])
                            
        # =========================================================================
                            
        # ---> CAMERA OVERLAY ZEICHNEN <---
        if self.tracker.nutze_kamera_links:
            self.draw_camera_overlay(combined_view, 'left', self.pad_x, scaled_w_left, self.pad_y + new_h)
        if self.tracker.nutze_kamera_rechts:
            self.draw_camera_overlay(combined_view, 'right', self.pad_x + scaled_w_left, int((orig_w - self.w_left_displayed) * self.scale_x), self.pad_y + new_h)

        # --- BUTTON-LEISTE OBEN RECHTS ---
        gap = 10     
        start_y = 10
        
        def draw_button(view, text, right_x, bg_color):
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            thickness = 1
            (text_w, text_h), _ = cv2.getTextSize(text, font, font_scale, thickness)
            btn_w = text_w + 20
            btn_h = 30
            x1 = right_x - btn_w
            y1 = start_y
            x2 = right_x
            y2 = start_y + btn_h
            cv2.rectangle(view, (x1, y1), (x2, y2), bg_color, -1)
            cv2.rectangle(view, (x1, y1), (x2, y2), (255, 255, 255), 1)
            text_x = x1 + (btn_w - text_w) // 2
            text_y = y1 + (btn_h + text_h) // 2
            cv2.putText(view, text, (text_x, text_y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
            return (x1, y1, x2, y2), x1 - gap

        x_cursor = win_w - 10
        self.btn_exit_coords, x_cursor = draw_button(combined_view, "Beenden", x_cursor, (60, 60, 60))
        self.btn_hilfe_coords, x_cursor = draw_button(combined_view, "Handbuch", x_cursor, (30, 140, 255))
        self.btn_zip_coords, x_cursor = draw_button(combined_view, "Bug ZIP", x_cursor, (40, 120, 40))
        self.btn_highscore_coords, x_cursor = draw_button(combined_view, "Highscore", x_cursor, (50, 150, 200))
        self.btn_save_coords, x_cursor = draw_button(combined_view, "Match Speichern", x_cursor, (180, 70, 70))
        self.btn_labor_coords, x_cursor = draw_button(combined_view, "Labor & Einstellungen", x_cursor, (150, 50, 150))
        
        rings_text = "Scheibe: An" if self.show_all_rings else "Scheibe: Aus"
        rings_color = (40, 160, 40) if self.show_all_rings else (80, 80, 80)
        self.btn_rings_coords, x_cursor = draw_button(combined_view, rings_text, x_cursor, rings_color)
        
        # ---> HUD / Trefferliste <---
        if self.ringwertung_aktiv:
            start_y_hud = 80  
            line_h = 25   
            max_items = max(5, (win_h - start_y_hud - 80) // line_h)
            box_w = 95 + (self.nachkommastellen * 15)  

            for side in ['left', 'right']:
                side_shots = self.tracker.sm.get_shots_for_side(side)
                if not side_shots: 
                    continue 
                    
                if side == 'left' and not self.tracker.nutze_kamera_links: continue
                if side == 'right' and not self.tracker.nutze_kamera_rechts: continue

                total_shots = len(side_shots)
                display_shots = side_shots[-max_items:] if total_shots > max_items else side_shots
                display_shots_rev = list(reversed(display_shots)) 
                
                if side == 'left':
                    if not self.tracker.nutze_kamera_rechts:
                        box_x = win_w - box_w - 10
                    else:
                        box_x = max(10, scaled_w_left - box_w - 10)
                else:
                    box_x = win_w - box_w - 10
                    
                box_h = (len(display_shots_rev) + 2) * line_h
                
                hud_overlay = combined_view.copy()
                cv2.rectangle(hud_overlay, (box_x - 10, start_y_hud - 25), (box_x + box_w, start_y_hud + box_h), (20, 20, 20), -1)
                cv2.addWeighted(hud_overlay, 0.4, combined_view, 0.6, 0, combined_view)
                
                titel = "Treffer (L)" if side == 'left' else "Treffer (R)"
                cv2.putText(combined_view, titel, (box_x - 5, start_y_hud - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.line(combined_view, (box_x - 5, start_y_hud - 2), (box_x + box_w - 5, start_y_hud - 2), (100, 100, 100), 1)
                
                for i, shot in enumerate(display_shots_rev):
                    shot_num = total_shots - i  
                    score_val = shot.get('score', 0.0)
                    text_color = (0, 255, 255) if score_val < 10.0 else (0, 255, 0)
                    text = f" {shot_num}:"
                    
                    score_str = f"{score_val:.{self.nachkommastellen}f}"
                    y_pos = start_y_hud + 20 + (i * line_h)
                    
                    if i == 0:
                        f_scale_num = 0.55
                        f_scale_score = 0.65
                        thick = 2
                        color_num = (255, 255, 255)
                    else:
                        f_scale_num = 0.5
                        f_scale_score = 0.55
                        thick = 1
                        color_num = (200, 200, 200)

                    cv2.putText(combined_view, text, (box_x - 5, y_pos), cv2.FONT_HERSHEY_SIMPLEX, f_scale_num, color_num, thick, cv2.LINE_AA)
                    cv2.putText(combined_view, score_str, (box_x + 50, y_pos), cv2.FONT_HERSHEY_SIMPLEX, f_scale_score, text_color, thick, cv2.LINE_AA)
                    
                    if i == 0 and len(display_shots_rev) > 1:
                        cv2.line(combined_view, (box_x - 5, y_pos + 8), (box_x + box_w - 5, y_pos + 8), (70, 70, 70), 1)

                y_sum = start_y_hud + 8 + len(display_shots_rev) * line_h
                cv2.line(combined_view, (box_x - 5, y_sum), (box_x + box_w - 5, y_sum), (100, 100, 100), 1)
                
                gesamt = sum(s.get('score', 0.0) for s in side_shots)
                gesamt_val = f"{gesamt:.{self.nachkommastellen}f}"
                y_total = y_sum + 20
                
                cv2.putText(combined_view, "Ges.:", (box_x - 5, y_total), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(combined_view, gesamt_val, (box_x + 45, y_total), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (50, 200, 255), 2, cv2.LINE_AA)

        # ---> Serien-Balken (Footer) <---
        if self.ringwertung_aktiv and self.serien_gruppierung > 0:
            scaled_h = int(orig_h * self.scale_y)
            footer_y = getattr(self, 'pad_y', 0) + scaled_h - 65
            
            overlay = combined_view.copy()
            
            for side in ['left', 'right']:
                if side == 'left' and not self.tracker.nutze_kamera_links: continue
                if side == 'right' and not self.tracker.nutze_kamera_rechts: continue
                
                side_shots = self.tracker.sm.get_shots_for_side(side)
                if not side_shots: continue
                
                if side == 'left':
                    start_x = getattr(self, 'pad_x', 0)
                    available_w = int(self.w_left_displayed * self.scale_x)
                else:
                    start_x = getattr(self, 'pad_x', 0) + int(self.w_left_displayed * self.scale_x)
                    available_w = int((orig_w - self.w_left_displayed) * self.scale_x)

                serien = [side_shots[i:i + self.serien_gruppierung] for i in range(0, len(side_shots), self.serien_gruppierung)]
                anzeige_serien = serien[-5:]
                
                block_w = 95 + (self.nachkommastellen * 15)
                total_blocks_w = len(anzeige_serien) * block_w
                cursor_x = start_x + (available_w - total_blocks_w) // 2
                
                padding = 15
                box_x1 = cursor_x - padding
                box_x2 = cursor_x + total_blocks_w - 20 + padding
                box_y1 = footer_y - 25
                box_y2 = footer_y + 10
                
                cv2.rectangle(overlay, (box_x1, box_y1), (box_x2, box_y2), (20, 20, 20), -1)
                
            cv2.addWeighted(overlay, 0.4, combined_view, 0.6, 0, combined_view)

            for side in ['left', 'right']:
                if side == 'left' and not self.tracker.nutze_kamera_links: continue
                if side == 'right' and not self.tracker.nutze_kamera_rechts: continue
                
                side_shots = self.tracker.sm.get_shots_for_side(side)
                if not side_shots: continue
                
                if side == 'left':
                    start_x = getattr(self, 'pad_x', 0)
                    available_w = int(self.w_left_displayed * self.scale_x)
                else:
                    start_x = getattr(self, 'pad_x', 0) + int(self.w_left_displayed * self.scale_x)
                    available_w = int((orig_w - self.w_left_displayed) * self.scale_x)

                serien = [side_shots[i:i + self.serien_gruppierung] for i in range(0, len(side_shots), self.serien_gruppierung)]
                anzeige_serien = serien[-6:]
                
                block_w = 95 + (self.nachkommastellen * 15)
                total_blocks_w = len(anzeige_serien) * block_w
                cursor_x = start_x + (available_w - total_blocks_w) // 2
                
                for i, serie in enumerate(anzeige_serien):
                    serien_index = len(serien) - len(anzeige_serien) + i + 1
                    summe = sum(s.get('score', 0.0) for s in serie)
                    
                    is_active = (i == len(anzeige_serien) - 1) and (len(serie) < self.serien_gruppierung or len(side_shots) % self.serien_gruppierung == 0)
                    
                    color_label = (255, 255, 255) if is_active else (180, 180, 180)
                    color_val = (50, 220, 255) if is_active else (220, 220, 220)
                    
                    cv2.putText(combined_view, f"S{serien_index}:", (cursor_x, footer_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_label, 1, cv2.LINE_AA)
                    cv2.putText(combined_view, f"{summe:.{self.nachkommastellen}f}", (cursor_x + 35, footer_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color_val, 2, cv2.LINE_AA)
                    
                    cursor_x += block_w
                    
        # ---> Logo-Overlay <---
        if getattr(self, 'logo_rgb_pre', None) is not None:
            c_h, c_w = combined_view.shape[:2]
            lh, lw = self.logo_h, self.logo_w
            
            margin_x = 20
            margin_y = 20
            
            start_x = getattr(self, 'pad_x', 0) + margin_x
            start_y = getattr(self, 'pad_y', 0) + margin_y
            
            end_x = start_x + lw
            end_y = start_y + lh
            
            if end_y <= c_h and end_x <= c_w and start_x >= 0 and start_y >= 0:
                roi = combined_view[start_y:end_y, start_x:end_x].astype(np.float32)
                blended = (roi * self.logo_inv_alpha) + self.logo_rgb_pre
                combined_view[start_y:end_y, start_x:end_x] = blended.astype(np.uint8)

        # ---> FPS-Counter <---
        current_time_fps = time.time()
        delta_t = current_time_fps - getattr(self, 'prev_frame_time', current_time_fps)
        self.prev_frame_time = current_time_fps
        
        if delta_t > 0:
            current_fps = 1.0 / delta_t
            self.fps = (self.fps * 0.9) + (current_fps * 0.1) 
            
        cv2.putText(combined_view, f"FPS: {int(self.fps)}", (15, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)

        cv2.imshow(self.tracker.window_name, combined_view)