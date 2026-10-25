import cv2
import math

class Helfer:
    
    # =====================================================================
    # ---> SINGLE SOURCE OF TRUTH: OPTIK & LINSEN-MATHEMATIK <---
    # =====================================================================

    @staticmethod
    def get_r_limit(targets=None, aktive_scheibe=None, config_limit_mm=0.0, fallback=25.0):
        """Zentrale Definition des optischen Korsetts. 
           Nutzt primär den hardware-verankerten Config-Wert. 
           (Fallback auf 3er-Ring, falls noch nicht in Config gespeichert)."""
        if config_limit_mm > 0.0:
            return config_limit_mm
            
        if targets and aktive_scheibe and aktive_scheibe in targets:
            ringe_dict = targets[aktive_scheibe].get('ringe_durchmesser_mm', {})
            if '3' in ringe_dict:
                return float(ringe_dict['3']) / 2.0
            elif '1' in ringe_dict:
                return float(ringe_dict['1']) / 2.0
            elif ringe_dict:
                return max([float(v) for v in ringe_dict.values()]) / 2.0
        return fallback
    
    @staticmethod
    def get_optical_center(cam_w, cam_h, cut_l, cut_t, off_x, off_y):
        return (cam_w / 2.0) - cut_l + off_x, (cam_h / 2.0) - cut_t + off_y

    @staticmethod
    def get_optical_center(cam_w, cam_h, cut_l, cut_t, off_x, off_y):
        return (cam_w / 2.0) - cut_l + off_x, (cam_h / 2.0) - cut_t + off_y
    
    @staticmethod
    def distort_radius(r_mm_true, korrektur, korr_r4, r_limit=None):
        if korrektur == 0.0 and korr_r4 == 0.0:
            return r_mm_true
            
        sign = -1.0 if r_mm_true < 0 else 1.0
        r_abs = abs(r_mm_true)
        
        if r_limit is None or r_abs <= r_limit:
            r2 = r_abs ** 2
            r4 = r2 ** 2
            factor = 1.0 + (korrektur * r2) + (korr_r4 * r4)
            return sign * (r_abs * factor)
        else:
            # Tangenten-Fortsetzung: Hält den lokalen Ringabstand ab r_limit exakt konstant!
            r2_lim = r_limit ** 2
            r4_lim = r2_lim ** 2
            
            val_lim = r_limit * (1.0 + korrektur * r2_lim + korr_r4 * r4_lim)
            slope_lim = 1.0 + 3.0 * korrektur * r2_lim + 5.0 * korr_r4 * r4_lim

            if slope_lim <= 0:
                print(
                    "\n"
                    "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                    "!!! WARNUNG: distort_radius NICHT-MONOTONE LINSENFUNKTION ERKANNT !!!\n"
                    "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                    f"slope_lim = {slope_lim:.12f}\n"
                    f"r_limit   = {r_limit:.6f}\n"
                    f"korrektur = {korrektur:.12e}\n"
                    f"korr_r4   = {korr_r4:.12e}\n"
                    "Die Verzerrungsfunktion ist am r_limit nicht mehr streng steigend.\n"
                    "Distort/Undistort sind damit eventuell nicht mehr eindeutig.\n"
                    "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                )
            
            return sign * (val_lim + slope_lim * (r_abs - r_limit))

    @staticmethod
    def undistort_radius(d_obs, korrektur, korr_r4, r_limit=None):
        if (korrektur == 0.0 and korr_r4 == 0.0) or d_obs == 0:
            return d_obs
            
        sign = -1.0 if d_obs < 0 else 1.0
        d_abs = abs(d_obs)
        
        if r_limit is not None:
            r2_lim = r_limit ** 2
            r4_lim = r2_lim ** 2
            val_lim = r_limit * (1.0 + korrektur * r2_lim + korr_r4 * r4_lim)
            slope_lim = 1.0 + 3.0 * korrektur * r2_lim + 5.0 * korr_r4 * r4_lim
            
            if slope_lim <= 0:
                print(
                    "\n"
                    "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                    "!!! WARNUNG: undistort_radius NICHT-MONOTONE LINSENFUNKTION ERKANNT !!!\n"
                    "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                    f"slope_lim = {slope_lim:.12f}\n"
                    f"r_limit   = {r_limit:.6f}\n"
                    f"korrektur = {korrektur:.12e}\n"
                    f"korr_r4   = {korr_r4:.12e}\n"
                    "Die Verzerrungsfunktion ist am r_limit nicht mehr streng steigend.\n"
                    "Distort/Undistort sind damit eventuell nicht mehr eindeutig.\n"
                    "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                )            

            #############PRINT############            
            r_test = r_limit * 0.999
            r2 = r_test ** 2
            r4 = r2 ** 2
            max_poly_near_limit = r_test * (
                1.0 + korrektur * r2 + korr_r4 * r4
            )
            if max_poly_near_limit > val_lim:
                print(
                    "\n"
                    "########################################################\n"
                    "### KENNLINIE ÜBERSCHREITET val_lim BEREITS INNEN !!! ###\n"
                    "########################################################\n"
                    f"max_poly_near_limit = {max_poly_near_limit:.6f}\n"
                    f"val_lim             = {val_lim:.6f}\n"
                    "Die Annahme des Umschaltpunktes könnte verletzt sein.\n"
                    "########################################################\n"
                )            
            #############PRINT############            
            
            if d_abs > val_lim and slope_lim != 0:
                return sign * (r_limit + (d_abs - val_lim) / slope_lim)

        d_true = d_abs
        for _ in range(5):
            r2 = d_true ** 2
            r4 = r2 ** 2
            factor = 1.0 + korrektur * r2 + korr_r4 * r4
            df = 1.0 + 3.0 * korrektur * r2 + 5.0 * korr_r4 * r4
                
            f = d_true * factor - d_abs
            if df == 0: break
            d_true = d_true - (f / df)
        
        #############PRINT############                    
        test_obs = Helfer.distort_radius(
            d_true,
            korrektur,
            korr_r4,
            r_limit
        )
        err = abs(test_obs - d_abs)
        if err > 0.001:      # Schwellwert anpassen
            print(
                "\n"
                "********************************************************\n"
                "*** DISTORT/UNDISTORT NICHT MEHR INVERSE !!! ***********\n"
                "********************************************************\n"
                f"d_obs      = {d_abs:.6f}\n"
                f"d_true     = {d_true:.6f}\n"
                f"re_distort = {test_obs:.6f}\n"
                f"error      = {err:.6f}\n"
                f"r_limit    = {r_limit}\n"
                f"korrektur  = {korrektur}\n"
                f"korr_r4    = {korr_r4}\n"
                "********************************************************\n"
            )        
        #############PRINT############                    
        
        
        
        
        return sign * d_true

    @staticmethod
    def get_ellipse_scales(r_mm_center, korrektur, korr_r4, r_limit=None):
        r_abs = abs(r_mm_center)
        r_clamp = min(r_abs, r_limit) if r_limit else r_abs
        r2 = r_clamp ** 2
        r4 = r2 ** 2
        scale_tan = 1.0 + (korrektur * r2) + (korr_r4 * r4)
        scale_rad = 1.0 + (3.0 * korrektur * r2) + (5.0 * korr_r4 * r4)
        return scale_tan, scale_rad

    @staticmethod
    def undistort_point_mm(px_x, px_y, lens_cx, lens_cy, px_x_ratio, px_y_ratio, korrektur, korr_r4, r_limit=None):
        dx_mm_obs = (px_x - lens_cx) / px_x_ratio if px_x_ratio else 0
        dy_mm_obs = (px_y - lens_cy) / px_y_ratio if px_y_ratio else 0
        d_obs = math.hypot(dx_mm_obs, dy_mm_obs)
        
        d_true = Helfer.undistort_radius(d_obs, korrektur, korr_r4, r_limit)
        scale = d_true / d_obs if d_obs > 0 else 1.0
        return dx_mm_obs * scale, dy_mm_obs * scale

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
        #print(f"r_limit: {r_limit}")
        
        z, ox, oy = zoom_params
        thickness_komp = (thickness / 2.0) if is_hit else 0.0
        rx, ry, angle_deg = 0, 0, 0
        
#        # 1. ZIELSCHEIBEN-RINGE (Symmetrisch, aber leicht verschoben)
#        if is_ring and lens_cx is not None and lens_cy is not None:
#            dx_px = center_x - lens_cx
#            dy_px = center_y - lens_cy
#            
#            dx_mm_obs = dx_px / px_x
#            dy_mm_obs = dy_px / px_y
#            d_obs = math.hypot(dx_mm_obs, dy_mm_obs)
#            
#            d_true = Helfer.undistort_radius(d_obs, korrektur, korr_r4, r_limit=r_limit)
#                    
#            if d_true > 0.01 and (abs(korrektur) > 0.000001 or abs(korr_r4) > 0.000001):
#                d_out_true = d_true + radius_mm
#                d_in_true = d_true - radius_mm
#               
#                obs_out = Helfer.distort_radius(d_out_true, korrektur, korr_r4, r_limit=r_limit)
#                obs_in = Helfer.distort_radius(d_in_true, korrektur, korr_r4, r_limit=r_limit)
#                
#                new_d_obs = (obs_out + obs_in) / 2.0
#                shift_mm = (new_d_obs - d_obs)
#                r_mm_draw = (obs_out - obs_in) / 2.0
#
#                if radius_mm > 22.0:
#                    print(f"🔍 [RING-CHECK] r_soll={radius_mm:.2f}mm | r_limit={r_limit} | "
#                          f"d_true={d_true:.2f}mm | d_in={d_in_true:.2f}mm -> obs_in={obs_in:.2f}mm | "
#                          f"d_out={d_out_true:.2f}mm -> obs_out={obs_out:.2f}mm | "
#                          f"r_draw={r_mm_draw:.2f}mm (Shift={shift_mm:.2f}mm)")
#                
#                shift_x_px = (dx_mm_obs / d_obs) * shift_mm * px_x
#                shift_y_px = (dy_mm_obs / d_obs) * shift_mm * px_y
#                
#                #r_mm_draw = (obs_out - obs_in) / 2.0
#
#                ## ==========================================================
#                ## DEBUG 1: Ring überschreitet die Grenze zwischen
#                ## Polynom-Bereich und Tangenten-Fortsetzung
#                ## ==========================================================
#                #if (
#                #    r_limit is not None
#                #    and d_in_true < r_limit
#                #    and d_out_true > r_limit
#                #):
#                #    print(
#                #        "\n"
#                #        "🚨🚨🚨 RING ÜBERQUERT r_limit 🚨🚨🚨\n"
#                #        f"d_true     = {d_true:.3f}\n"
#                #        f"radius_mm  = {radius_mm:.3f}\n"
#                #        f"d_in_true  = {d_in_true:.3f}\n"
#                #        f"d_out_true = {d_out_true:.3f}\n"
#                #        f"r_limit    = {r_limit:.3f}\n"
#                #        "Innenrand im Polynomteil\n"
#                #        "Außenrand im Tangententeil\n"
#                #        "🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨\n"
#                #    )                
#                #
#                ## ==========================================================
#                ## DEBUG 2: Mittelpunkt-Drift
#                ## Prüft ob die Randkonstruktion den Ringmittelpunkt
#                ## verschiebt gegenüber distort_radius(d_true)
#                ## ==========================================================
#                #obs_center = Helfer.distort_radius(
#                #    d_true,
#                #    korrektur,
#                #    korr_r4,
#                #    r_limit=r_limit
#                #)
#                #center_error = abs(new_d_obs - obs_center)
#                #if center_error > 0.05:      # Schwellwert evtl. 0.02 .. 0.10
#                #    print(
#                #        "\n"
#                #        "🔥🔥🔥 RINGMITTELPUNKT-DRIFT 🔥🔥🔥\n"
#                #        f"d_true        = {d_true:.6f}\n"
#                #        f"obs_center    = {obs_center:.6f}\n"
#                #        f"new_d_obs     = {new_d_obs:.6f}\n"
#                #        f"delta         = {center_error:.6f} mm\n"
#                #        f"shift_mm      = {shift_mm:.6f}\n"
#                #        f"obs_in        = {obs_in:.6f}\n"
#                #        f"obs_out       = {obs_out:.6f}\n"
#                #        f"draw_radius   = {r_mm_draw:.6f}\n"
#                #        f"r_limit       = {r_limit:.6f}\n"
#                #        "🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥\n"
#                #    )
#                
#                
#            else:
#                shift_x_px = 0.0
#                shift_y_px = 0.0
#                r_mm_draw = Helfer.distort_radius(radius_mm, korrektur, korr_r4, r_limit=r_limit)
#                
#            shifted_cx = center_x + shift_x_px
#            shifted_cy = center_y + shift_y_px
#            
#            draw_cx = int(round((shifted_cx * z + ox) * scale_x))
#            draw_cy = int(round((shifted_cy * z + oy) * scale_y))
#            
#            angle_deg = 0
#            rx_raw = (r_mm_draw * px_x) * z * scale_x
#            ry_raw = (r_mm_draw * px_y) * z * scale_y
#            
#            # ---> DIAGNOSE-PRINT FÜR DEN BILDSCHIRM-DURCHMESSER <---
#            #print(f"🔍 [DRAW-ELLIPSE] Ring-Radius(Soll): {radius_mm*2:.2f} mm | Nach Verzerrung(Draw): {r_mm_draw*2:.2f} mm | Pixel-Durchmesser(X): {rx_raw*2:.1f} px (r_limit={r_limit})")
#
#            rx = int(round(rx_raw - thickness_komp))
#            ry = int(round(ry_raw - thickness_komp))
#

        # 1. ZIELSCHEIBEN-RINGE (Exakte 2D-Scheitelprojektion, 100% synchron mit Log & Roten Punkten)
        if is_ring and lens_cx is not None and lens_cy is not None:
            if abs(korrektur) > 0.000001 or abs(korr_r4) > 0.000001:
                # 1. Scheibenzentrum in wahre physikalische Millimeter (relativ zur Linse) entzerren
                true_cx, true_cy = Helfer.undistort_point_mm(
                    center_x, center_y, lens_cx, lens_cy, px_x, px_y, korrektur, korr_r4, r_limit=r_limit
                )
                
                # Hilfsfunktion: Projiziert einen wahren Punkt (mm) exakt wie die roten Punkte auf den Sensor (px)
                def project_to_sensor(tx_mm, ty_mm):
                    r_true = math.hypot(tx_mm, ty_mm)
                    if r_true > 0.0:
                        r_obs = Helfer.distort_radius(r_true, korrektur, korr_r4, r_limit=r_limit)
                        scale_fwd = r_obs / r_true
                    else:
                        scale_fwd = 1.0
                    return lens_cx + tx_mm * scale_fwd * px_x, lens_cy + ty_mm * scale_fwd * px_y

                # 2. Die 4 wahren Scheitelpunkte (Links, Rechts, Oben, Unten) auf den Sensor projizieren
                x_left, _  = project_to_sensor(true_cx - radius_mm, true_cy)
                x_right, _ = project_to_sensor(true_cx + radius_mm, true_cy)
                _, y_top   = project_to_sensor(true_cx, true_cy - radius_mm)
                _, y_bot   = project_to_sensor(true_cx, true_cy + radius_mm)

                # 3. Exaktes Zentrum und Halbachsen (X/Y separat!) auf dem Sensor bestimmen
                shifted_cx = (x_left + x_right) / 2.0
                shifted_cy = (y_top + y_bot) / 2.0
                r_px_x = abs(x_right - x_left) / 2.0
                r_px_y = abs(y_bot - y_top) / 2.0
            else:
                shifted_cx = center_x
                shifted_cy = center_y
                r_px_x = radius_mm * px_x
                r_px_y = radius_mm * px_y
                
            draw_cx = int(round((shifted_cx * z + ox) * scale_x))
            draw_cy = int(round((shifted_cy * z + oy) * scale_y))
            
            angle_deg = 0
            rx_raw = r_px_x * z * scale_x
            ry_raw = r_px_y * z * scale_y

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