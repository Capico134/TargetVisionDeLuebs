import cv2
import math

class Helfer:
    
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
        """
        Universelle Render-Funktion für TargetVision & Labor.
        Regelt vollautomatisch:
        - Fischaugen-Verzerrung in Bezug auf das Kamerazentrum
        - Cinematic Zoom Matrix (z, ox, oy)
        - Fenster-Skalierung (scale_x, scale_y)
        - Intelligentes Stroke-Alignment (Linienstärke nach innen bei Treffern)
        - Flexible Strichelung (dash_step, dash_length)

        Parameter:
        ----------
        img : ndarray
            Das OpenCV-Bild (NumPy-Array), auf das gezeichnet werden soll.
        center_x, center_y : float
            Das Zentrum des Objekts, das aktuell gezeichnet wird (in originalen Kamera-Pixeln). 
            - Beim Zeichnen der Scheiben-Ringe: Der Nullpunkt der Zielscheibe.
            - Beim Zeichnen eines Treffers: Der berechnete Mittelpunkt des Einschusslochs (z. B. der CoG).
        radius_mm : float
            Der physikalische Radius in Millimetern (z. B. für ISSF-Ringe oder das Kaliber).
        color : tuple
            Die Farbe der Linie als BGR-Tupel (z. B. (0, 255, 255) für Gelb).
        px_x, px_y : float
            Die Kamera-Kalibrierung: Pixel pro Millimeter für die X- und Y-Achse.
        korrektur : float
            Der Multiplikator für die Fischaugen-Verzerrung, um die Linsenkrümmung am Rand auszugleichen.
        kurve : float, optional
            Der Exponent (IDDQD) für die dynamische Verzerrungskurve. Standard ist 1.5.
        lens_cx, lens_cy : float, optional
            Der optische Mittelpunkt der Kameralinse. Dient als Nullpunkt, von dem aus die Verzerrung nach außen hin zunimmt.
        thickness : int, optional
            Die Linienstärke der Ellipse in Pixeln. Standard ist 1.
        dashed : bool, optional
            Aktiviert die gestrichelte Linie, wenn True. Standard ist False.
        dash_offset : int, optional
            Verschiebt den Startwinkel der Strichelung. Nützlich, um verschiedene Ringe optisch gegeneinander zu verdrehen.
        dash_step : int, optional
            Der Abstand zwischen den einzelnen Strichen in Grad. Standard ist 6.
        dash_length : int, optional
            Die Länge eines einzelnen Striches in Grad. Standard ist 2.
        text : str, optional
            Ein Text, der optisch perfekt zentriert in die Mitte der Ellipse geschrieben wird.
        text_color : tuple, optional
            Die BGR-Farbe des Textes. Standard ist Schwarz (0, 0, 0).
        is_hit : bool, optional
            Wenn True, greift das Stroke-Alignment: Die halbe Linienstärke wird vom Radius abgezogen.
        is_ring : bool, optional
            Wenn True, wird die Ellipse konzentrisch gezeichnet, aber ihr optischer Mittelpunkt verschiebt sich leicht durch die Verzerrung.
        zoom_params : tuple, optional
            Ein Tupel (z, ox, oy) mit dem Zoomfaktor und dem Versatz für die "Cinematic Camera" (Pan & Zoom Logik).
        scale_x, scale_y : float, optional
            Die Skalierungsfaktoren, falls das Bild für die GUI in der Größe verändert wurde.
        draw_center_dot : bool, optional
            Wenn True, wird ein kleiner Bullseye-Mittelpunkt (4px schwarzer Rand, 2px farbiger Kern) gezeichnet.
        """
        z, ox, oy = zoom_params
        
        thickness_komp = (thickness / 2.0) if is_hit else 0.0
        rx, ry, angle_deg = 0, 0, 0
        
        # =====================================================================
        # ---> NEU: ZIELSCHEIBEN-RINGE (Symmetrisch, aber leicht verschoben) <---
        # =====================================================================
        if is_ring and lens_cx is not None and lens_cy is not None:
            dx_px = center_x - lens_cx
            dy_px = center_y - lens_cy
            
            dx_mm_obs = dx_px / px_x
            dy_mm_obs = dy_px / px_y
            d_obs = math.hypot(dx_mm_obs, dy_mm_obs)
            
            # Newton-Raphson für die wahre Distanz auf dem Papier (wie im StateManager)
            d_true = d_obs
            if korrektur != 0.0 and d_obs > 0:
                for _ in range(4):
                    d_abs = abs(d_true)
                    f = d_true + korrektur * (d_abs**(kurve + 1.0)) - d_obs
                    df = 1.0 + (kurve + 1.0) * korrektur * (d_abs**kurve)
                    if df == 0: break
                    d_true = d_true - (f / df)
                    
            if d_true > 0.01 and abs(korrektur) > 0.000001:
                # Wahre Kanten des Rings auf der Achse zum Linsenzentrum
                d_out_true = d_true + radius_mm
                d_in_true = d_true - radius_mm
                
                # Vorwärts-Verzerrung auf beide Ringkanten anwenden
                obs_out = d_out_true * (1.0 + (abs(d_out_true)**kurve) * korrektur)
                obs_in = d_in_true * (1.0 + (abs(d_in_true)**kurve) * korrektur)
                
                # Der NEUE optische Mittelpunkt (verschiebt sich bei großen Ringen!)
                new_d_obs = (obs_out + obs_in) / 2.0
                
                # Verschiebung in Millimetern
                shift_mm = (new_d_obs - d_obs)
                
                # Auf X/Y Pixel umrechnen
                shift_x_px = (dx_mm_obs / d_obs) * shift_mm * px_x
                shift_y_px = (dy_mm_obs / d_obs) * shift_mm * px_y
                
                # ---> ELA BUGFIX: Die echte, optisch verzerrte Größe des Rings berechnen! <---
                r_mm_draw = (obs_out - obs_in) / 2.0
            else:
                shift_x_px = 0.0
                shift_y_px = 0.0
                r_mm_draw = radius_mm * (1.0 + (radius_mm**kurve * korrektur))
                
            shifted_cx = center_x + shift_x_px
            shifted_cy = center_y + shift_y_px
            
            draw_cx = int(round((shifted_cx * z + ox) * scale_x))
            draw_cy = int(round((shifted_cy * z + oy) * scale_y))
            
            # ---> WIE VORHER: Keine Eier-Form, keine Rotation! <---
            angle_deg = 0
            
            rx_raw = (r_mm_draw * px_x) * z * scale_x
            ry_raw = (r_mm_draw * px_y) * z * scale_y
            
            rx = int(round(rx_raw - thickness_komp))
            ry = int(round(ry_raw - thickness_komp))

        # =====================================================================
        # ---> SCHUSSLÖCHER (Treffer - Symmetrische Näherung) <---
        # =====================================================================
        elif lens_cx is not None and lens_cy is not None:
            # Hier bleibt alles beim Alten (Treffer werden leicht oval gestreckt und rotiert)
            dx_mm = (center_x - lens_cx) / px_x
            dy_mm = (center_y - lens_cy) / px_y
            r_mm_center = math.hypot(dx_mm, dy_mm)
            
            draw_cx = int(round((center_x * z + ox) * scale_x))
            draw_cy = int(round((center_y * z + oy) * scale_y))
            
            if r_mm_center > 0.05 and abs(korrektur) > 0.000001:
                rad = math.atan2(dy_mm, dx_mm)
                angle_deg = math.degrees(rad)
                
                scale_tangential = 1.0 + (r_mm_center**kurve * korrektur)
                scale_radial = 1.0 + ((kurve + 1.0) * r_mm_center**kurve * korrektur)
                
                cos_a = math.cos(rad)
                sin_a = math.sin(rad)
                px_radial = math.sqrt((px_x * cos_a)**2 + (px_y * sin_a)**2)
                px_tangential = math.sqrt((px_x * (-sin_a))**2 + (px_y * cos_a)**2)
                
                rx_raw = (radius_mm * scale_radial * px_radial) * z * scale_x
                ry_raw = (radius_mm * scale_tangential * px_tangential) * z * scale_y
            else:
                angle_deg = 0
                r_mm_draw = radius_mm * (1.0 + (radius_mm**kurve * korrektur))
                rx_raw = (r_mm_draw * px_x) * z * scale_x
                ry_raw = (r_mm_draw * px_y) * z * scale_y
                
            rx = int(round(rx_raw - thickness_komp))
            ry = int(round(ry_raw - thickness_komp))
        else:
            # Fallback (Keine Kalibrierung)
            draw_cx = int(round((center_x * z + ox) * scale_x))
            draw_cy = int(round((center_y * z + oy) * scale_y))
            
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