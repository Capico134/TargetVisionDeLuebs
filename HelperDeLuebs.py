import cv2
import math

class Helfer:
    
    @staticmethod
    def draw_smart_ellipse(img, center_x, center_y, radius_mm, color, 
                           px_x, px_y, korrektur, 
                           feedback_cx=None, feedback_cy=None,
                           thickness=1, dashed=False, dash_offset=0, 
                           dash_step=6, dash_length=2, 
                           text=None, text_color=(0,0,0), 
                           is_hit=False, zoom_params=(1.0, 0.0, 0.0), 
                           scale_x=1.0, scale_y=1.0, draw_center_dot=False):
        """
        Universelle Render-Funktion für TargetVision & Labor.
        Regelt vollautomatisch:
        - Fischaugen-Verzerrung in Bezug auf das Kamerazentrum
        - Cinematic Zoom Matrix (z, ox, oy)
        - Fenster-Skalierung (scale_x, scale_y)
        - Intelligentes Stroke-Alignment (Linienstärke nach innen bei Treffern)
        - Flexible Strichelung (dash_step, dash_length)
        """
        z, ox, oy = zoom_params
        
        # 1. Den echten Mittelpunkt blitzschnell auf das Monitor-ROI mappen
        draw_cx = int(round((center_x * z + ox) * scale_x))
        draw_cy = int(round((center_y * z + oy) * scale_y))
        
        # 2. Stroke Alignment (Soll die Linie nur nach innen wachsen?)
        thickness_komp = (thickness / 2.0) if is_hit else 0.0
        
        rx, ry, angle_deg = 0, 0, 0
        
        # 3. Verzerrung berechnen (falls Zentrum kalibriert ist)
        if feedback_cx is not None and feedback_cy is not None:
            dx_mm = (center_x - feedback_cx) / px_x
            dy_mm = (center_y - feedback_cy) / px_y
            r_mm_center = math.hypot(dx_mm, dy_mm)
            
            if r_mm_center > 0.05:
                # Fall A: Das Objekt liegt NICHT im optischen Zentrum
                angle_deg = math.degrees(math.atan2(dy_mm, dx_mm))
                scale_radial = 1.0 + (2.0 * r_mm_center * korrektur)
                scale_tangential = 1.0 + (r_mm_center * korrektur)
                
                rx_raw = (radius_mm * scale_radial * px_x) * z * scale_x
                ry_raw = (radius_mm * scale_tangential * px_y) * z * scale_y
            else:
                # Fall B: Objekt liegt EXAKT im optischen Zentrum
                angle_deg = 0
                r_mm_draw = radius_mm * (1.0 + (radius_mm * korrektur))
                
                rx_raw = (r_mm_draw * px_x) * z * scale_x
                ry_raw = (r_mm_draw * px_y) * z * scale_y

            rx = int(round(rx_raw - thickness_komp))
            ry = int(round(ry_raw - thickness_komp))
        else:
            # Fallback (Keine Kalibrierung)
            avg_px = (px_x + px_y) / 2.0
            r_raw = (radius_mm * avg_px) * z * scale_x
            rx = ry = int(round(r_raw - thickness_komp))
            
        # 4. Sicherheitssperre, damit es nicht crasht, wenn der Radius winzig wird
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
                
        # ---> Der sichtbare Bullseye-Mittelpunkt <---
        if draw_center_dot:
            # Ein 4px schwarzer Kreis mit einem 2px farbigen Kern in der übergebenen Farbe
            cv2.circle(img, (draw_cx, draw_cy), 4, (0, 0, 0), -1, cv2.LINE_AA)
            cv2.circle(img, (draw_cx, draw_cy), 2, color, -1, cv2.LINE_AA)
                
        # 6. Text zentrieren (Falls übergeben)
        if text:
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            text_thick = 1
            
            (text_w, text_h), _ = cv2.getTextSize(text, font, font_scale, text_thick)
            text_x = draw_cx - (text_w // 2)
            text_y = draw_cy + (text_h // 2)
            
            cv2.putText(img, text, (text_x, text_y), font, font_scale, (0, 0, 0), text_thick + 2, cv2.LINE_AA)
            cv2.putText(img, text, (text_x, text_y), font, font_scale, text_color, text_thick, cv2.LINE_AA)