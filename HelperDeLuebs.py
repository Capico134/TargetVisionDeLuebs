import cv2
import math

class Helfer:
    
    # =====================================================================
    # ---> SINGLE SOURCE OF TRUTH: OPTIK & LINSEN-MATHEMATIK <---
    # =====================================================================
    @staticmethod
    def get_optical_center(cam_w, cam_h, cut_l, cut_t, off_x, off_y):
        """Berechnet den physikalischen Linsenmittelpunkt im Kamerabild."""
        return (cam_w / 2.0) - cut_l + off_x, (cam_h / 2.0) - cut_t + off_y

    @staticmethod
    def distort_radius(r_mm_true, korrektur, kurve):
        """Vorwärts-Verzerrung: Berechnet, wie groß ein wahrer Radius auf dem Sensor erscheint."""
        if korrektur == 0.0:
            return r_mm_true
        return r_mm_true * (1.0 + (abs(r_mm_true)**kurve) * korrektur)

    @staticmethod
    def undistort_radius(d_obs, korrektur, kurve):
        """Newton-Raphson Rückrechnung: Entzerrt einen Radius zurück auf die wahre Papierebene."""
        if korrektur == 0.0 or d_obs <= 0:
            return d_obs
            
        d_true = d_obs
        for _ in range(4):
            d_abs = abs(d_true)
            f = d_true + korrektur * (d_abs**(kurve + 1.0)) - d_obs
            df = 1.0 + (kurve + 1.0) * korrektur * (d_abs**kurve)
            if df == 0: break
            d_true = d_true - (f / df)
        return d_true

    @staticmethod
    def undistort_point_mm(px_x, px_y, lens_cx, lens_cy, px_x_ratio, px_y_ratio, korrektur, kurve):
        """Entzerrt einen Sensor-Punkt in Millimeter-Abstände zur Linsenachse."""
        dx_mm_obs = (px_x - lens_cx) / px_x_ratio if px_x_ratio else 0
        dy_mm_obs = (px_y - lens_cy) / px_y_ratio if px_y_ratio else 0
        d_obs = math.hypot(dx_mm_obs, dy_mm_obs)
        
        d_true = Helfer.undistort_radius(d_obs, korrektur, kurve)
        scale = d_true / d_obs if d_obs > 0 else 1.0
        
        return dx_mm_obs * scale, dy_mm_obs * scale

    @staticmethod
    def get_ellipse_scales(r_mm_center, korrektur, kurve):
        """Gibt (scale_tangential, scale_radial) für die asymmetrische ovale Verzerrung zurück."""
        scale_tan = 1.0 + (abs(r_mm_center)**kurve * korrektur)
        scale_rad = 1.0 + ((kurve + 1.0) * abs(r_mm_center)**kurve * korrektur)
        return scale_tan, scale_rad

    # =====================================================================
    # ---> DER RENDERER (Nutzt nun die Single Source of Truth!) <---
    # =====================================================================

    @staticmethod
    def draw_smart_ellipse(img, center_x, center_y, radius_mm, color, 
                           px_x, px_y, korrektur, kurve=1.5,
                           lens_cx=None, lens_cy=None,
                           thickness=1, dashed=False, dash_offset=0,
                           dash_step=6, dash_length=2, 
                           text=None, text_color=(0,0,0), 
                           is_hit=False, is_ring=False,
                           zoom_params=(1.0, 0.0, 0.0), 
                           scale_x=1.0, scale_y=1.0, draw_center_dot=False):
        
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
            
            # ---> ELA: Aufruf der zentralen Rückrechnung <---
            d_true = Helfer.undistort_radius(d_obs, korrektur, kurve)
                    
            if d_true > 0.01 and abs(korrektur) > 0.000001:
                d_out_true = d_true + radius_mm
                d_in_true = d_true - radius_mm
                
                # ---> ELA: Aufruf der zentralen Vorwärts-Verzerrung <---
                obs_out = Helfer.distort_radius(d_out_true, korrektur, kurve)
                obs_in = Helfer.distort_radius(d_in_true, korrektur, kurve)
                
                new_d_obs = (obs_out + obs_in) / 2.0
                shift_mm = (new_d_obs - d_obs)
                
                shift_x_px = (dx_mm_obs / d_obs) * shift_mm * px_x
                shift_y_px = (dy_mm_obs / d_obs) * shift_mm * px_y
                
                r_mm_draw = (obs_out - obs_in) / 2.0
            else:
                shift_x_px = 0.0
                shift_y_px = 0.0
                r_mm_draw = Helfer.distort_radius(radius_mm, korrektur, kurve)
                
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
            
            if r_mm_center > 0.05 and abs(korrektur) > 0.000001:
                rad = math.atan2(dy_mm, dx_mm)
                angle_deg = math.degrees(rad)
                
                ## ---> ELA: Die Punkt-Ableitung (Der "alte" Faktor) <---
                #scale_tangential, scale_radial_approx = Helfer.get_ellipse_scales(r_mm_center, korrektur, kurve)
                #scale_radial = scale_radial_approx
                #
                ## =================================================================
                ## ---> DEIN FIX: Der perfekte Mittelwert für Treffer <---
                ## =================================================================
                #if is_hit:
                #    # 1. Makroskopische Verzerrung (Wahre Kanten des Lochs)
                #    d_out_true = r_mm_center + radius_mm
                #    d_in_true = abs(r_mm_center - radius_mm)
                #    
                #    obs_out = Helfer.distort_radius(d_out_true, korrektur, kurve)
                #    obs_in = Helfer.distort_radius(d_in_true, korrektur, kurve)
                #    
                #    # 2. Den neuen radialen Faktor aus der echten Bild-Ausdehnung berechnen
                #    scale_radial_macro = ((obs_out - obs_in) / 2.0) / radius_mm
                #    
                #    # 3. Der Mittelwert aus Punkt-Verzerrung und Kanten-Verzerrung
                #    scale_radial = (scale_radial_approx + scale_radial_macro) / 2.0
                

                # ---> ELA: Die Punkt-Ableitung (Der "alte" Faktor) <---
                scale_tangential, scale_radial = Helfer.get_ellipse_scales(r_mm_center, korrektur, kurve)
                # =================================================================
                # ---> DEIN FIX: Fokus auf die wertungsrelevante Innenkante <---
                # =================================================================
                if is_hit:
                    # Wir werten die radiale Verzerrung leicht nach innen versetzt aus
                    r_eval = abs(r_mm_center - (radius_mm / 2.0))
                    _, scale_radial = Helfer.get_ellipse_scales(r_eval, korrektur, kurve)

                
                cos_a = math.cos(rad)
                sin_a = math.sin(rad)
                px_radial = math.sqrt((px_x * cos_a)**2 + (px_y * sin_a)**2)
                px_tangential = math.sqrt((px_x * (-sin_a))**2 + (px_y * cos_a)**2)
                
                rx_raw = (radius_mm * scale_radial * px_radial) * z * scale_x
                ry_raw = (radius_mm * scale_tangential * px_tangential) * z * scale_y
            else:
                angle_deg = 0
                r_mm_draw = Helfer.distort_radius(radius_mm, korrektur, kurve)
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