import cv2
import math

class Helfer:
    
    # =====================================================================
    # ---> SINGLE SOURCE OF TRUTH: OPTIK & LINSEN-MATHEMATIK <---
    # =====================================================================
    @staticmethod
    def get_optical_center(cam_w, cam_h, cut_l, cut_t, off_x, off_y):
        return (cam_w / 2.0) - cut_l + off_x, (cam_h / 2.0) - cut_t + off_y

    @staticmethod
    def distort_radius(r_mm_true, korrektur, korr_r4, r_limit=None):
        if korrektur == 0.0 and korr_r4 == 0.0:
            return r_mm_true
            
        r_clamp = min(r_mm_true, r_limit) if r_limit else r_mm_true
        r2 = r_clamp ** 2
        r4 = r2 ** 2
        
        factor = 1.0 + (korrektur * r2) + (korr_r4 * r4)
        return r_mm_true * factor  # Lineare Fortsetzung außerhalb des Limits

    @staticmethod
    def undistort_radius(d_obs, korrektur, korr_r4, r_limit=None):
        if (korrektur == 0.0 and korr_r4 == 0.0) or d_obs <= 0:
            return d_obs
            
        d_true = d_obs
        for _ in range(5):
            if r_limit is None or d_true <= r_limit:
                r2 = d_true ** 2
                r4 = r2 ** 2
                factor = 1.0 + korrektur * r2 + korr_r4 * r4
                df = 1.0 + 3.0 * korrektur * r2 + 5.0 * korr_r4 * r4
            else:
                r2 = r_limit ** 2
                r4 = r2 ** 2
                factor = 1.0 + korrektur * r2 + korr_r4 * r4
                df = factor
                
            f = d_true * factor - d_obs
            if df == 0: break
            d_true = d_true - (f / df)
        return d_true

    @staticmethod
    def undistort_point_mm(px_x, px_y, lens_cx, lens_cy, px_x_ratio, px_y_ratio, korrektur, korr_r4, r_limit=None):
        dx_mm_obs = (px_x - lens_cx) / px_x_ratio if px_x_ratio else 0
        dy_mm_obs = (px_y - lens_cy) / px_y_ratio if px_y_ratio else 0
        d_obs = math.hypot(dx_mm_obs, dy_mm_obs)
        
        d_true = Helfer.undistort_radius(d_obs, korrektur, korr_r4, r_limit)
        scale = d_true / d_obs if d_obs > 0 else 1.0
        return dx_mm_obs * scale, dy_mm_obs * scale

    @staticmethod
    def get_ellipse_scales(r_mm_center, korrektur, korr_r4, r_limit=None):
        r_clamp = min(r_mm_center, r_limit) if r_limit else r_mm_center
        r2 = r_clamp ** 2
        r4 = r2 ** 2
        scale_tan = 1.0 + (korrektur * r2) + (korr_r4 * r4)
        scale_rad = 1.0 + (3.0 * korrektur * r2) + (5.0 * korr_r4 * r4)
        return scale_tan, scale_rad

    @staticmethod
    def draw_smart_ellipse(img, center_x, center_y, radius_mm, color, 
                           px_x, px_y, korrektur, korr_r4=0.0,
                           lens_cx=None, lens_cy=None,
                           thickness=1, dashed=False, dash_offset=0,
                           dash_step=6, dash_length=2, 
                           text=None, text_color=(0,0,0), 
                           is_hit=False, is_ring=False,
                           zoom_params=(1.0, 0.0, 0.0), 
                           scale_x=1.0, scale_y=1.0, draw_center_dot=False, r_limit=None):
        
        z, ox, oy = zoom_params
        thickness_komp = (thickness / 2.0) if is_hit else 0.0
        rx, ry, angle_deg = 0, 0, 0
        
        # 1. ZIELSCHEIBEN-RINGE (Symmetrisch, aber leicht verschoben)
        if is_ring and lens_cx is not None and lens_cy is not None:
            dx_px = center_x - lens_cx
            dy_px = center_y - lens_cy
            
            dx_mm_obs = dx_px / px_x
            dy_mm_obs = dy_px / px_y
            d_obs = math.hypot(dx_mm_obs, dy_mm_obs)
            
            # ---> FIX: r_limit an undistort_radius übergeben! <---
            d_true = Helfer.undistort_radius(d_obs, korrektur, korr_r4, r_limit=r_limit)
                    
            if d_true > 0.01 and (abs(korrektur) > 0.000001 or abs(korr_r4) > 0.000001):
                d_out_true = d_true + radius_mm
                d_in_true = d_true - radius_mm
                
                # ---> FIX: r_limit an distort_radius übergeben! <---
                obs_out = Helfer.distort_radius(d_out_true, korrektur, korr_r4, r_limit=r_limit)
                obs_in = Helfer.distort_radius(d_in_true, korrektur, korr_r4, r_limit=r_limit)
                
                new_d_obs = (obs_out + obs_in) / 2.0
                shift_mm = (new_d_obs - d_obs)
                
                shift_x_px = (dx_mm_obs / d_obs) * shift_mm * px_x
                shift_y_px = (dy_mm_obs / d_obs) * shift_mm * px_y
                
                r_mm_draw = (obs_out - obs_in) / 2.0
            else:
                shift_x_px = 0.0
                shift_y_px = 0.0
                # ---> FIX: r_limit an distort_radius übergeben! <---
                r_mm_draw = Helfer.distort_radius(radius_mm, korrektur, korr_r4, r_limit=r_limit)
                
            shifted_cx = center_x + shift_x_px
            shifted_cy = center_y + shift_y_px
            
            draw_cx = int(round((shifted_cx * z + ox) * scale_x))
            draw_cy = int(round((shifted_cy * z + oy) * scale_y))
            
            angle_deg = 0
            rx_raw = (r_mm_draw * px_x) * z * scale_x
            ry_raw = (r_mm_draw * px_y) * z * scale_y
            
            rx = int(round(rx_raw - thickness_komp))
            ry = int(round(ry_raw - thickness_komp))

        # 2. SCHUSSLÖCHER (Treffer - Ovale Form)
        elif lens_cx is not None and lens_cy is not None:
            dx_mm = (center_x - lens_cx) / px_x
            dy_mm = (center_y - lens_cy) / px_y
            r_mm_center = math.hypot(dx_mm, dy_mm)
            
            draw_cx = int(round((center_x * z + ox) * scale_x))
            draw_cy = int(round((center_y * z + oy) * scale_y))
            
            if r_mm_center > 0.05 and (abs(korrektur) > 0.000001 or abs(korr_r4) > 0.000001):
                rad = math.atan2(dy_mm, dx_mm)
                angle_deg = math.degrees(rad)
                
                # ---> FIX: r_limit an get_ellipse_scales übergeben! <---
                scale_tangential, scale_radial = Helfer.get_ellipse_scales(r_mm_center, korrektur, korr_r4, r_limit=r_limit)
                
                if is_hit:
                    r_eval = abs(r_mm_center - (radius_mm / 2.0))
                    # ---> FIX: r_limit an get_ellipse_scales übergeben! <---
                    _, scale_radial = Helfer.get_ellipse_scales(r_eval, korrektur, korr_r4, r_limit=r_limit)
                
                cos_a = math.cos(rad)
                sin_a = math.sin(rad)
                px_radial = math.sqrt((px_x * cos_a)**2 + (px_y * sin_a)**2)
                px_tangential = math.sqrt((px_x * (-sin_a))**2 + (px_y * cos_a)**2)
                
                rx_raw = (radius_mm * scale_radial * px_radial) * z * scale_x
                ry_raw = (radius_mm * scale_tangential * px_tangential) * z * scale_y
            else:
                angle_deg = 0
                # ---> FIX: r_limit an distort_radius übergeben! <---
                r_mm_draw = Helfer.distort_radius(radius_mm, korrektur, korr_r4, r_limit=r_limit)
                rx_raw = (r_mm_draw * px_x) * z * scale_x
                ry_raw = (r_mm_draw * px_y) * z * scale_y
                
            rx = int(round(rx_raw - thickness_komp))
            ry = int(round(ry_raw - thickness_komp))
            
        # 3. Fallback (Keine Kalibrierung)
        else:
            draw_cx = int(round((center_x * z + ox) * scale_x))
            draw_cy = int(round((center_y * z + oy) * scale_y))
            avg_px = (px_x + px_y) / 2.0
            r_raw = (radius_mm * avg_px) * z * scale_x
            rx = ry = int(round(r_raw - thickness_komp))
            
        rx, ry = max(2, rx), max(2, ry)
        
        # 5. Zeichnen!
        if dashed:
            for angle in range(dash_offset, 360 + dash_offset, dash_step):
                cv2.ellipse(img, (draw_cx, draw_cy), (rx, ry), angle_deg, angle, angle + dash_length, color, thickness, cv2.LINE_AA)
        else:
            if rx == ry and angle_deg == 0:
                cv2.circle(img, (draw_cx, draw_cy), rx, color, thickness, cv2.LINE_AA)
            else:
                cv2.ellipse(img, (draw_cx, draw_cy), (rx, ry), angle_deg, 0, 360, color, thickness, cv2.LINE_AA)
                
        if draw_center_dot:
            cv2.circle(img, (draw_cx, draw_cy), 4, (0, 0, 0), -1, cv2.LINE_AA)
            cv2.circle(img, (draw_cx, draw_cy), 2, color, -1, cv2.LINE_AA)
                
        if text:
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            text_thick = 1
            
            (text_w, text_h), _ = cv2.getTextSize(text, font, font_scale, text_thick)
            text_x = draw_cx - (text_w // 2)
            text_y = draw_cy + (text_h // 2)
            
            cv2.putText(img, text, (text_x, text_y), font, font_scale, (0, 0, 0), text_thick + 2, cv2.LINE_AA)
            cv2.putText(img, text, (text_x, text_y), font, font_scale, text_color, text_thick, cv2.LINE_AA)