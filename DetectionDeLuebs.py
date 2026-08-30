import cv2
import numpy as np
import time
from datetime import datetime

class TargetDetector:
    """
    Diese Klasse kümmert sich AUSSCHLIESSLICH um die Bilderkennung (Computer Vision).
    Sie weiß nichts von Fenstern, Buttons oder HUDs.
    """
    def __init__(self, config, datei_manager, state_manager, log_callback):
        self.config = config
        self.dm = datei_manager
        self.sm = state_manager
        
        # Das ist die magische Verbindung zur GUI, damit der Detector in dein Fenster loggen kann
        self.log = log_callback  
        
        # Alle Schwellenwerte und Einstellungen für die Erkennung
        self.min_hole_area = config.getint('Erkennung', 'min_hole_area')
        self.caliber_radius = config.getfloat('Erkennung', 'caliber_radius')
        self.hit_tolerance = config.getint('Erkennung', 'hit_tolerance', fallback=15)
        self.erkennungs_methode = config.get('Erkennung', 'erkennungs_methode', fallback='C').upper()
        self.hybrid_riss_faktor = config.getfloat('Erkennung', 'hybrid_riss_faktor', fallback=1.175)
        self.hybrid_sichel_faktor = config.getfloat('Erkennung', 'hybrid_sichel_faktor', fallback=0.95)
        self.hybrid_discard_faktor = config.getfloat('Erkennung', 'hybrid_discard_faktor', fallback=2.5)
        self.hough_min_faktor = config.getfloat('Erkennung', 'hough_min_faktor', fallback=0.85)
        self.hough_max_faktor = config.getfloat('Erkennung', 'hough_max_faktor', fallback=1.15)
        self.ausloeser_durch_erschuetterung = config.getboolean('Erkennung', 'ausloeser_durch_erschuetterung', fallback=False)
        self.max_image_change_percent = config.getfloat('Erkennung', 'max_image_change_percent', fallback=5.0)
        self.debug_alle_bilder_speichern = config.getboolean('Erkennung', 'debug_alle_bilder_speichern', fallback=False)
        self.ringwertung_aktiv = config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
        
        # Neue Parameter
        self.hough_param1 = config.getint('Erkennung', 'hough_param1', fallback=25)
        self.hough_param2 = config.getint('Erkennung', 'hough_param2', fallback=4)
        self.morph_kernel_size = config.getint('Erkennung', 'morph_kernel_size', fallback=6)
        self.max_aspect_ratio = config.getfloat('Erkennung', 'max_aspect_ratio', fallback=3.5)
        # ---> NEU: Die Gewichtung für den 200-Punkte-Score <---
        self.gesamt_anteil_am_200score = config.getfloat('Erkennung', 'gesamt_anteil_am_200score', fallback=0.667)

        # Internes Gedächtnis des Detectors
        self.ref_left = None
        self.ref_right = None
        self.calib_feedback_left = None
        self.calib_feedback_right = None

    def save_debug_image(self, name, image):
        self.dm.save_debug_image(name, image)
        self.log("SYSTEM", f"📸 Debug-Bild gespeichert: {name}")

    def normalize_brightness(self, ref, live):
        mean_ref = cv2.mean(ref)[:3]
        mean_live = cv2.mean(live)[:3]
        diff = np.array(mean_ref) - np.array(mean_live)
        live_float = live.astype(np.float32)
        live_float += diff
        return np.clip(live_float, 0, 255).astype(np.uint8)

    def calculate_hole_score(self, cx, cy, radius, thresh_new, thresh_raw):
        """
        Berechnet die Qualität eines potenziellen Schusslochs (Score 0 bis 200).
        """
        circle_mask = np.zeros_like(thresh_new)
        cv2.circle(circle_mask, (int(cx), int(cy)), int(radius), 255, -1)
        
        pixels_in_circle = cv2.countNonZero(circle_mask)
        if pixels_in_circle == 0: 
            return 0.0, 0.0, 0.0
            
        # 1. Check: Anteil am NEUEN Riss (thresh_new)
        intersection_new = cv2.bitwise_and(thresh_new, circle_mask)
        pixels_in_new = cv2.countNonZero(intersection_new)
        coverage_new = (pixels_in_new / pixels_in_circle) * 100 
        
        # 2. Check: Anteil am GESAMTEN Lochbild (thresh_raw)
        intersection_raw = cv2.bitwise_and(thresh_raw, circle_mask)
        pixels_in_raw = cv2.countNonZero(intersection_raw)
        coverage_raw = (pixels_in_raw / pixels_in_circle) * 100 
        
        # ---> NEU: Die gewichtete Berechnung! <---
        weight_new = 1.0 - self.gesamt_anteil_am_200score
        total_score = 2.0 * ((coverage_new * weight_new) + (coverage_raw * self.gesamt_anteil_am_200score))
        
        return total_score, coverage_new, coverage_raw

    def ninja_kalibrierungs_check(self, ref_bgr, side):
        """Findet den Nullpunkt mit dem unbestechlichen 'Weißen-Punkt-Sniper'."""
        aktive_scheibe_id = self.config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
        targets = self.dm.load_targets()
        
        if aktive_scheibe_id not in targets: return None
            
        spiegel_mm = targets[aktive_scheibe_id].get('spiegel_durchmesser_mm', 30.5)
        gray_frame = cv2.cvtColor(ref_bgr, cv2.COLOR_BGR2GRAY)
        
        _, thresh = cv2.threshold(gray_frame, 100, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours: return None
            
        groesste_kontur = max(contours, key=cv2.contourArea)
        if cv2.contourArea(groesste_kontur) < 1000: return None
            
        x, y, w, h = cv2.boundingRect(groesste_kontur)

        mask = np.zeros_like(gray_frame)
        cv2.drawContours(mask, [groesste_kontur], -1, 255, -1)
        
        shrink_size = int(w * 0.15)
        kernel = np.ones((shrink_size, shrink_size), np.uint8)
        mask_shrunk = cv2.erode(mask, kernel, iterations=1)
        
        masked_gray = cv2.bitwise_and(gray_frame, gray_frame, mask=mask_shrunk)
        blurred_gray = cv2.GaussianBlur(masked_gray, (5, 5), 0)
        _, max_val, _, max_loc = cv2.minMaxLoc(blurred_gray)
        
        if max_val > 100:
            cx, cy = max_loc
            self.log("SYSTEM", f"🎯 Weißer Punkt exakt zentriert auf X:{cx} Y:{cy}", True)
            punkt_gefunden = True
        else:
            cx, cy = int(x + (w / 2)), int(y + (h / 2))
            self.log("SYSTEM", f"⚠️ Kein weißer Punkt! Fallback auf Erdnuss-Mitte.", True)
            punkt_gefunden = False

        seite_str = "links" if side == 'left' else "rechts"
        config_x = self.config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
        config_y = self.config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
        
        ideal_rx = int((spiegel_mm * config_x) / 2)
        ideal_ry = int((spiegel_mm * config_y) / 2)
        is_erdnuss = (w > ideal_rx * 2.2) or (h > ideal_ry * 2.2)

        feedback_data = {
            'cx': cx, 'cy': cy,
            'red_cx': int(x + w/2), 'red_cy': int(y + h/2),
            'ideal_rx': ideal_rx, 'ideal_ry': ideal_ry,
            'red_rx': int(w/2), 'red_ry': int(h/2),
            'show_red': is_erdnuss,
            'time': time.time()
        }
        
        if side == 'left': self.calib_feedback_left = feedback_data
        else: self.calib_feedback_right = feedback_data

        return (cx, cy)

    def set_reference_image(self, frame, side):
        bgr_blur = cv2.GaussianBlur(frame, (7, 7), 0)
        if side == 'left': self.ref_left = bgr_blur
        else: self.ref_right = bgr_blur
            
        self.save_debug_image(f"referenz_{side}", frame)
        
        if self.ringwertung_aktiv:
            mitte = self.ninja_kalibrierungs_check(bgr_blur, side)
            if mitte:
                self.sm.set_nullpunkt(side, mitte[0], mitte[1]) 
                self.log("SYSTEM", f"🎯 Nullpunkt {side.upper()} gesetzt auf X:{int(mitte[0])} Y:{int(mitte[1])}", True)

    def detect_new_shot(self, frame, side):
        state = self.sm.state_left if side == 'left' else self.sm.state_right
        reference_bgr = self.ref_left if side == 'left' else self.ref_right
        
        if reference_bgr is None or frame is None: 
            self.log(side, "Fehler: Keine Referenz vorhanden!")
            return False

        current_bgr_blur = cv2.GaussianBlur(frame, (7, 7), 0) 
        current_normalized = self.normalize_brightness(reference_bgr, current_bgr_blur)
        
        #ALTE FARBERKENNUNG
        #diff_bgr = cv2.absdiff(reference_bgr, current_normalized) 
        #diff_gray = cv2.cvtColor(diff_bgr, cv2.COLOR_BGR2GRAY)
        #_, thresh_raw = cv2.threshold(diff_gray, self.hit_tolerance, 255, cv2.THRESH_BINARY) 
        
        #NEUE FARBERKENNUNG
        diff_bgr = cv2.absdiff(reference_bgr, current_normalized) 
        # ---> DER COLOR-HACK: Wir nehmen einfach den maximalen Ausschlag aus B, G oder R <---
        # Verhindert, dass massive Rot-Änderungen von der Graustufen-Formel verschluckt werden!
        diff_gray = np.max(diff_bgr, axis=2) 
        _, thresh_raw = cv2.threshold(diff_gray, self.hit_tolerance, 255, cv2.THRESH_BINARY)

        # 1. ERST die alten Treffer abziehen (Stanzt den Riss aus)
        if state.cumulative_mask is not None:
            thresh_new = cv2.subtract(thresh_raw, state.cumulative_mask)
            # Zerstört alle grauen Reste aus eventuell unsauberen Masken
            _, thresh_new = cv2.threshold(thresh_new, 127, 255, cv2.THRESH_BINARY)
        else:
            thresh_new = thresh_raw.copy()
            state.cumulative_mask = np.zeros_like(thresh_raw)

        # 2. DANN den Morph-Filter auf die rohen NEUEN Fragmente anwenden!
        k_size = self.morph_kernel_size
        if k_size > 0:
            kernel = np.ones((k_size, k_size), np.uint8)
            thresh_new = cv2.morphologyEx(thresh_new, cv2.MORPH_CLOSE, kernel)

        changed_pixels = cv2.countNonZero(thresh_new)
        total_pixels = thresh_new.shape[0] * thresh_new.shape[1]
        change_percent = (changed_pixels / total_pixels) * 100
        
        if change_percent > self.max_image_change_percent:
            self.log(side, f"⚠️ SANITY CHECK FEHLGESCHLAGEN: Neuer Zuwachs zu {change_percent:.2f}%")
            self.log(side, "-> Ignoriere Frame.")
            return False 

        ##DEBUG-Ausgabe
        #import os
        #export_dir = "labor_export"
        #os.makedirs(export_dir, exist_ok=True)
        #cv2.imwrite(os.path.join(export_dir, "DETECTION_00_thresh_new.png"), thresh_new)

        contours, _ = cv2.findContours(thresh_new, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        new_shots_found_this_frame = []
        
        # NEU: Flag, um zu merken, ob wir Riesen-Risse maskieren müssen
        update_mask_only = False 
        
        if self.ausloeser_durch_erschuetterung or len(contours) > 0:
            self.log(side, f"Analysiere Konturen... (Neuer Zuwachs: {change_percent:.2f}% | Konturen: {len(contours)})")

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > self.min_hole_area:
                
                # ---> NEU: Der Anti-Verschiebungs-Filter (Aspect Ratio) <---
                rx, ry, rw, rh = cv2.boundingRect(cnt)
                if rw == 0 or rh == 0: continue
                aspect_ratio = rh/rw 
                if aspect_ratio > self.max_aspect_ratio:
                    self.log(side, f"🚫 Störung ignoriert (Zu schmal: Ratio {aspect_ratio:.1f} > {self.max_aspect_ratio:.1f}). Maskiert! (Info: zu flache Treffer sind okay)")
                    update_mask_only = True
                    continue 

                # Globale Variablen für diesen Treffer initialisieren
                final_shot_score = 0.0
                cx, cy = 0, 0
               
                if self.erkennungs_methode == 'C':
                    # 1. Kandidat A: Minimum Enclosing Circle (MEC)
                    (circle_x, circle_y), radius = cv2.minEnclosingCircle(cnt)
                    score_mec, mec_new, mec_raw = self.calculate_hole_score(circle_x, circle_y, self.caliber_radius, thresh_new, thresh_raw)
                    
                    # 2. Kandidat B: Center of Gravity / Schwerpunkt (CoG)
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cog_x = M["m10"] / M["m00"]
                        cog_y = M["m01"] / M["m00"]
                        score_cog, cog_new, cog_raw = self.calculate_hole_score(cog_x, cog_y, self.caliber_radius, thresh_new, thresh_raw)
                    else:
                        score_cog, cog_new, cog_raw = -1.0, 0.0, 0.0
                        cog_x, cog_y = circle_x, circle_y

                    # 3. Das Baseline-Duell: Wer hat den besseren Fit?
                    if score_cog > score_mec:
                        base_score, base_new, base_raw = score_cog, cog_new, cog_raw
                        base_x, base_y = cog_x, cog_y
                        base_name = "Schwerpunkt (CoG)" # <--- NEU: Namensschild
                        self.log(side, f"⚖️ Baseline-Duell: Schwerpunkt gewinnt! (CoG: {score_cog:.1f} > MEC: {score_mec:.1f})")
                    else:
                        base_score, base_new, base_raw = score_mec, mec_new, mec_raw
                        base_x, base_y = circle_x, circle_y
                        base_name = "MinCircle (MEC)" # <--- NEU: Namensschild
                        # Nur loggen, wenn der Unterschied relevant ist, um die Konsole sauber zu halten
                        if score_mec - score_cog > 5.0:
                            self.log(side, f"⚖️ Baseline-Duell: MinCircle gewinnt! (MEC: {score_mec:.1f} > CoG: {score_cog:.1f})")
                            
                    # ---> AB HIER ARBEITEN WIR MIT base_x, base_y und base_score <---
                    
                    limit_sichel = self.caliber_radius * self.hybrid_sichel_faktor
                    limit_riss = self.caliber_radius * self.hybrid_riss_faktor
                    limit_discard = self.caliber_radius * self.hybrid_discard_faktor
                    
                    self.log(side, f"🔍 Check Kontur: Radius={radius:.1f}px | Limits: Sichel<{limit_sichel:.1f}, Normal, Riss>{limit_riss:.1f}, Discard>{limit_discard:.1f}")
                    self.log(side, f"📊 Base-Score (Sieger): {base_score:.1f}")
                    
                    if radius > limit_discard:
                        self.log(side, f"🚫 Störung ignoriert (Radius {radius:.1f}px > Limit {limit_discard:.1f}px). Wird maskiert, nicht gewertet!")
                        update_mask_only = True
                        continue 
                        
                    # 1. Check: Ist der Radius ohnehin perfekt in der Norm UND gut gefüllt?
                    elif limit_sichel <= radius <= limit_riss and base_score > 145.0:
                        self.log(side, f"✅ Loch ist in der Norm und gut gefüllt (Radius {radius:.1f}px | Score {base_score:.1f}). Überspringe Hough!")
                        cx, cy = int(base_x), int(base_y) # <--- HIER base_x/y nutzen!
                        final_shot_score = base_score
                        
                    # 2. Check: Form ist makellos?
                    elif base_score > 185.0:
                        self.log(side, f"✅ Form ist makellos (Score {base_score:.1f} > 185), trotz Radius {radius:.1f}px. Überspringe Hough!")
                        cx, cy = int(base_x), int(base_y) # <--- HIER base_x/y nutzen!
                        final_shot_score = base_score
                        
                    # 3. Check: Wir brauchen Hough!
                    else:
                        self.log(side, f"🛠️ Sichel/Riss bestätigt (Score {base_score:.1f}) -> Aktiviere HoughCircles...")
                        mask = np.zeros_like(thresh_new)
                        cv2.drawContours(mask, [cnt], -1, 255, -1)
                        
                        mask_blurred = cv2.GaussianBlur(mask, (9, 9), 0)
                        min_r = max(2, int(self.caliber_radius * self.hough_min_faktor))
                        max_r = int(self.caliber_radius * self.hough_max_faktor)
                        
                        circles = cv2.HoughCircles(mask_blurred, cv2.HOUGH_GRADIENT, dp=1, minDist=2,
                                                   param1=self.hough_param1, param2=self.hough_param2, 
                                                   minRadius=min_r, maxRadius=max_r)
                        
                        hough_success = False
                        
                        if circles is not None:
                            best_score = base_score
                            best_cx, best_cy = int(base_x), int(base_y) # <--- HIER base_x/y nutzen!
                            winner_new = base_new
                            hough_beat_base = False
                            
                            found_circles = np.round(circles[0, :]).astype("int")
                            self.log(side, f"🔎 Hough hat {len(found_circles)} Kandidaten. Duell gegen Base-Score ({base_score:.1f})...")
                            
                            for (hx, hy, hr) in found_circles:
                                total_score, coverage_new, coverage_raw = self.calculate_hole_score(hx, hy, self.caliber_radius, thresh_new, thresh_raw)
                                if total_score > best_score:
                                    best_score = total_score
                                    best_cx, best_cy = hx, hy
                                    winner_new = coverage_new
                                    hough_beat_base = True

                            if winner_new >= 5.0:
                                cx, cy = best_cx, best_cy
                                final_shot_score = best_score 
                                if hough_beat_base:
                                    self.log(side, f"🏆 Hough-Sieger triumphiert (Score {best_score:.1f}) und setzt Zentrum.")
                                else:
                                    # ---> NEU: Dynamischer Name <---
                                    self.log(side, f"🛡️ {base_name} verteidigt Titel! (Score {best_score:.1f})")
                                hough_success = True
                            else:
                                self.log(side, "⚠️ Sieger hat zu wenig Anteil am neuen Riss (< 5%). Verwerfe Sieger!")
                                
                        if not hough_success:
                            self.log(side, "⚠️ Wechsle zu Abrisskante / Fallback...")
                            erfolg_abriss = False
                            
                            if state.cumulative_mask is not None and cv2.countNonZero(state.cumulative_mask) > 0:
                                kernel_dilate = np.ones((5, 5), np.uint8)
                                old_holes = cv2.dilate(state.cumulative_mask, kernel_dilate, iterations=1)
                                intersection = cv2.bitwise_and(old_holes, mask)
                                inter_contours, _ = cv2.findContours(intersection, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                                
                                ts_abriss = datetime.now().strftime('%H%M%S_%f')[:-3]
                                self.save_debug_image(f"abrisskante_schnittmenge_{side}_{ts_abriss}", intersection)
                                
                                if inter_contours:
                                    largest_inter = max(inter_contours, key=cv2.contourArea)
                                    if cv2.contourArea(largest_inter) > 3:
                                        M_int = cv2.moments(largest_inter)
                                        if M_int["m00"] != 0:
                                            cx_int = int(M_int["m10"] / M_int["m00"])
                                            cy_int = int(M_int["m01"] / M_int["m00"])
                                            
                                            M_new = cv2.moments(cnt)
                                            if M_new["m00"] != 0:
                                                cx_new = int(M_new["m10"] / M_new["m00"])
                                                cy_new = int(M_new["m01"] / M_new["m00"])
                                                
                                                dx = cx_new - cx_int
                                                dy = cy_new - cy_int
                                                dist = np.hypot(dx, dy)
                                                
                                                if dist > 0:
                                                    nx = dx / dist
                                                    ny = dy / dist
                                                    
                                                    # ---> DIE NEUE, INTELLIGENTE ABRISSKANTE <---
                                                    test_cx = int(cx_int + nx * self.caliber_radius)
                                                    test_cy = int(cy_int + ny * self.caliber_radius)
                                                    
                                                    # Der Schiedsrichter testet die Vektor-Kante!
                                                    abriss_score, abriss_new, _ = self.calculate_hole_score(test_cx, test_cy, self.caliber_radius, thresh_new, thresh_raw)
                                                    self.log(side, f"🧪 TEST-ABRISSKANTE: Theor. Zentrum X:{test_cx} Y:{test_cy} | Score: {abriss_score:.1f}")
                                                    
                                                    if abriss_score > base_score and abriss_new >= 5.0:
                                                        self.log(side, f"🎯 Abrisskante AKTIV! Schlägt Base-Score ({abriss_score:.1f} > {base_score:.1f}). Zentrum gesetzt.")
                                                        cx, cy = test_cx, test_cy
                                                        final_shot_score = abriss_score
                                                        erfolg_abriss = True 
                                                    else:
                                                        self.log(side, f"⚠️ Abrisskante verworfen! (Score {abriss_score:.1f} ist schlechter als Base {base_score:.1f})")
                                                else:
                                                    self.log(side, "⚠️ Abrisskante gescheitert: Schwerpunkte liegen exakt aufeinander.")
                                            else:
                                                self.log(side, "⚠️ Abrisskante gescheitert: Schnittmenge hat keine berechenbare Masse.")
                                        else:
                                            self.log(side, "⚠️ Abrisskante gescheitert: Schnittmenge ist zu winzig (< 3px).")
                                    else:
                                        self.log(side, "⚠️ Abrisskante gescheitert: Keine Überlappung mit alten Löchern gefunden.")
                            else:
                                self.log(side, "⚠️ Abrisskante übersprungen: Noch keine alten Treffer auf der Scheibe vorhanden.")

                            # FALLBACK FÜR BEIDE MODI
                            if not erfolg_abriss:
                                cx, cy = int(base_x), int(base_y) 
                                final_shot_score = base_score 
                                # ---> NEU: Dynamischer Name <---
                                self.log(side, f"⚠️ Verwende FALLBACK-Zentrum ({base_name}) für Wertung: X:{cx} Y:{cy} (Score {base_score:.1f})")
                                
                elif self.erkennungs_methode == 'B':
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        final_shot_score, _, _ = self.calculate_hole_score(cx, cy, self.caliber_radius, thresh_new, thresh_raw)                                                                                                       
                    else:
                        continue 
                else:
                    (circle_x, circle_y), _ = cv2.minEnclosingCircle(cnt)
                    cx, cy = int(circle_x), int(circle_y)
                    # HIER FEHLTE DIE ZUWEISUNG:
                    final_shot_score, _, _ = self.calculate_hole_score(cx, cy, self.caliber_radius, thresh_new, thresh_raw)
                
                # --- FEHLALARM-FILTER: Score < 70 ---
                if final_shot_score < 80:
                    self.log(side, f"🚫 Fehlalarm: Score {final_shot_score:.1f} < 70 -> nicht als Treffer gewertet!")
                    update_mask_only = True
                    continue

                
                # Doppelzählungs-Schutz (Getrennt nach Historie und aktueller Frame-Schleife)
                is_new = True
                # 1. Prüfung gegen Historie (alte Treffer aus vorherigen Frames) -> Sehr streng (0.15)
                clipping_factor_history = 0.15
                for shot in self.sm.shots:
                    if shot['side'] == side:
                        dist = np.hypot(shot['pos'][0] - cx, shot['pos'][1] - cy)
                        if dist < self.caliber_radius * clipping_factor_history:
                            is_new = False
                            self.log(side, f"⚠️ Treffer ignoriert: Zu nah ({dist:.1f}px) an bekanntem alten Schuss aus vorherigen Frames!")
                            break
                            
                # 2. Prüfung gegen Fragmente aus DIESEM Frame -> Großzügig (0.95), um Sichel-Risse abzuwürgen
                if is_new:
                    # ---> DIE FEHLERHAFTE NEUBERECHNUNG WURDE HIER ENTFERNT <---
                    
                    clipping_factor_current = 0.95
                    for i, existing_shot in enumerate(new_shots_found_this_frame):
                        dist = np.hypot(existing_shot['cx'] - cx, existing_shot['cy'] - cy)
                        if dist < self.caliber_radius * clipping_factor_current:
                            
                            # ---> NEU: Das Sichel-Duell! Wer hat den höheren Weißanteil? <---
                            if final_shot_score > existing_shot['score']:
                                self.log(side, f"🔄Aussortieren von Dublikaten: Sichel-Duell: Ersetze altes Fragment (Score {final_shot_score:.1f} > {existing_shot['score']:.1f})")
                                # Überschreibe den Verlierer mit dem neuen, besseren Kandidaten
                                new_shots_found_this_frame[i] = {'cx': cx, 'cy': cy, 'area': area, 'score': final_shot_score}
                            else:
                                self.log(side, f"⚠️ Treffer ignoriert: Verliert Sichel-Duell gegen besseres Fragment (Score {existing_shot['score']:.1f} > {final_shot_score:.1f})!")
                            
                            is_new = False
                            break

                if is_new:
                    # ---> NEU: Den Score mit abspeichern, damit spätere Fragmente dagegen antreten können!
                    new_shots_found_this_frame.append({'cx': cx, 'cy': cy, 'area': area, 'score': final_shot_score})
                    self.log(side, f"-> NEUES LOCH GEFUNDEN: Pos ({cx}, {cy}) | Fläche {area:.1f}px | Score {final_shot_score:.1f}")
                    
        # ---> BLOCK FÜR TREFFER UND DISCARD-MASKEN <---
        if new_shots_found_this_frame or update_mask_only:
            
            # Echte Treffer dem StateManager übergeben
            if new_shots_found_this_frame:
                for s in self.sm.shots:
                    if s['side'] == side:
                        s['is_new'] = False

                for sd in new_shots_found_this_frame:
                    shot = self.sm.add_shot(side, sd['cx'], sd['cy'], sd['area'], cv_score=sd.get('score', 0.0))
                    self.log(side, f"💥 Treffer gewertet: {shot['score']} Ringe!")
                self.log(side, f"🎯 {len(new_shots_found_this_frame)} neue(r) Treffer bestätigt!", True)
            
            # Maske für BEIDE Fälle (Treffer & Discard-Risse) updaten
            state.cumulative_mask = cv2.bitwise_or(state.cumulative_mask, thresh_new)
            self.save_debug_image(f"diff_gesamt_{side}", state.cumulative_mask)
            self.save_debug_image(f"diff_letzter_treffer_{side}", thresh_new)
            self.save_debug_image(f"letzte_aufnahme_{side}", frame)
            
            # Bei puren Masken-Updates speichern wir keine separaten Schuss_XX Dateien ab
            if self.debug_alle_bilder_speichern and new_shots_found_this_frame:
                ts = datetime.now().strftime('%H%M%S_%f')[:-3]
                shot_idx = sum(1 for s in self.sm.shots if s['side'] == side) 
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_diff", thresh_new)
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_orig", frame)
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_diff_gesamt", state.cumulative_mask)

            return True if new_shots_found_this_frame else False
        else:
            if self.ausloeser_durch_erschuetterung:
                self.log(side, "Keine validen neuen Treffer im Bild gefunden.")
            self.save_debug_image(f"diff_letzte_verworfene_auswertung_{side}", thresh_new)
            self.save_debug_image(f"letzte_verworfene_aufnahme_{side}", frame)
            return False

    def check_background_and_evaluate(self, frame, state):
        current_ref = self.ref_left if state.side == 'left' else self.ref_right
        bg_visible, bg_percent = state.is_background_visible(frame)
        diff = bg_percent - state.min_area 
        
        if bg_visible:
            if state.target_present:
                self.log(state.side, f"Hintergrund-Analyse: {bg_percent:.1f}% -> WAND (+{diff:.1f}% über Limit {state.min_area}%)")
                self.log(state.side, "Scheibe außer Sicht -> Warte auf Zielscheibe...", True)
                state.target_present = False
        else:
            if not state.target_present:
                self.log(state.side, f"Hintergrund-Analyse: {bg_percent:.1f}% -> SCHEIBE ({abs(diff):.1f}% unter Limit {state.min_area}%)")
                state.target_present = True
                #SOOOOOOOOOOOOOOOOOOOOONEEEEEEEEEEEEEEEEESCHEIIIIIIIIIIIIISSSSSSSSSSEEEEEEEEEEEEEEEEEEE
                #if hasattr(self.dm, 'clear_debug_images'):
                #    self.dm.clear_debug_images(state.side)
                
                if current_ref is None:
                    self.set_reference_image(frame, state.side)
                else:
                    self.detect_new_shot(frame, state.side)
            else:
                self.detect_new_shot(frame, state.side)