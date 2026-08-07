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
        self.caliber_radius = config.getint('Erkennung', 'caliber_radius')
        self.hit_tolerance = config.getint('Erkennung', 'hit_tolerance', fallback=15)
        self.erkennungs_methode = config.get('Erkennung', 'erkennungs_methode', fallback='C').upper()
        self.hybrid_riss_faktor = config.getfloat('Erkennung', 'hybrid_riss_faktor', fallback=1.5)
        self.hybrid_sichel_faktor = config.getfloat('Erkennung', 'hybrid_sichel_faktor', fallback=0.75)
        self.hybrid_discard_faktor = config.getfloat('Erkennung', 'hybrid_discard_faktor', fallback=2.5)
        self.hough_min_f = config.getfloat('Erkennung', 'hough_min_faktor', fallback=0.85)
        self.hough_max_f = config.getfloat('Erkennung', 'hough_max_faktor', fallback=1.15)
        self.ausloeser_erschuetterung = config.getboolean('Erkennung', 'ausloeser_durch_erschuetterung', fallback=False)
        self.max_img_change = config.getfloat('Erkennung', 'max_image_change_percent', fallback=5.0)
        self.debug_alle_bilder_speichern = config.getboolean('Erkennung', 'debug_alle_bilder_speichern', fallback=False)
        self.ringwertung_aktiv = config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)

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

    def ninja_kalibrierungs_check(self, ref_bgr, side):
        """Findet den Nullpunkt mit dem unbestechlichen 'Weißen-Punkt-Sniper'."""
        aktive_scheibe_id = self.config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
        targets = self.dm.load_targets()
        
        if aktive_scheibe_id not in targets: return None
            
        spiegel_mm = targets[aktive_scheibe_id].get('spiegel_durchmesser_mm', 30.5)
        gray_frame = cv2.cvtColor(ref_bgr, cv2.COLOR_BGR2GRAY)
        
        _, thresh = cv2.threshold(gray_frame, 80, 255, cv2.THRESH_BINARY_INV)
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
            self.log("SYSTEM", f"🎯 Weißer Punkt exakt zentriert auf X:{cx} Y:{cy}")
            punkt_gefunden = True
        else:
            cx, cy = int(x + (w / 2)), int(y + (h / 2))
            self.log("SYSTEM", f"⚠️ Kein weißer Punkt! Fallback auf Erdnuss-Mitte.")
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
                self.log("SYSTEM", f"🎯 Nullpunkt {side.upper()} gesetzt auf X:{int(mitte[0])} Y:{int(mitte[1])}")

    def detect_new_shot(self, frame, side):
        state = self.sm.state_left if side == 'left' else self.sm.state_right
        reference_bgr = self.ref_left if side == 'left' else self.ref_right
        
        if reference_bgr is None or frame is None: 
            self.log(side, "Fehler: Keine Referenz vorhanden!")
            return False

        current_bgr_blur = cv2.GaussianBlur(frame, (7, 7), 0) 
        current_normalized = self.normalize_brightness(reference_bgr, current_bgr_blur)
        
        diff_bgr = cv2.absdiff(reference_bgr, current_normalized) 
        diff_gray = cv2.cvtColor(diff_bgr, cv2.COLOR_BGR2GRAY)
        _, thresh_raw = cv2.threshold(diff_gray, self.hit_tolerance, 255, cv2.THRESH_BINARY) 

        kernel = np.ones((6, 6), np.uint8)
        thresh_raw = cv2.morphologyEx(thresh_raw, cv2.MORPH_CLOSE, kernel)

        if state.cumulative_mask is not None:
            thresh_new = cv2.subtract(thresh_raw, state.cumulative_mask)
        else:
            thresh_new = thresh_raw.copy()
            state.cumulative_mask = np.zeros_like(thresh_raw)

        changed_pixels = cv2.countNonZero(thresh_new)
        total_pixels = thresh_new.shape[0] * thresh_new.shape[1]
        change_percent = (changed_pixels / total_pixels) * 100
        
        if change_percent > self.max_img_change:
            self.log(side, f"⚠️ SANITY CHECK FEHLGESCHLAGEN: Neuer Zuwachs zu {change_percent:.2f}%")
            self.log(side, "-> Ignoriere Frame.")
            return False 

        contours, _ = cv2.findContours(thresh_new, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        new_shots_found_this_frame = []
        
        # NEU: Flag, um zu merken, ob wir Riesen-Risse maskieren müssen
        update_mask_only = False 
        
        if self.ausloeser_erschuetterung or len(contours) > 0:
            self.log(side, f"Analysiere Konturen... (Neuer Zuwachs: {change_percent:.2f}% | Konturen: {len(contours)})")

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > self.min_hole_area:
               
                if self.erkennungs_methode == 'C':
                    (circle_x, circle_y), radius = cv2.minEnclosingCircle(cnt)
                    
                    # ---> NEU: Der Discard-Check für Riesen-Konturen <---
                    if radius > (self.caliber_radius * self.hybrid_discard_faktor):
                        self.log(side, f"🚫 Störung ignoriert (Radius {radius:.1f}px > Limit). Wird maskiert, nicht gewertet!")
                        update_mask_only = True
                        continue # Überspringt die Treffer-Auswertung für diese Kontur!
                    
                    if (radius > (self.caliber_radius * self.hybrid_riss_faktor)) or (radius < (self.caliber_radius * self.hybrid_sichel_faktor)):
                        self.log(side, f"🛠️ Sichel oder Riss erkannt (Radius: {radius:.1f}px) -> Aktiviere HoughCircles...")
                        mask = np.zeros_like(thresh_new)
                        cv2.drawContours(mask, [cnt], -1, 255, -1)
                        
                        mask_blurred = cv2.GaussianBlur(mask, (9, 9), 0)
                        min_r = max(2, int(self.caliber_radius * self.hough_min_f))
                        max_r = int(self.caliber_radius * self.hough_max_f)
                        
                        circles = cv2.HoughCircles(mask_blurred, cv2.HOUGH_GRADIENT, dp=1, minDist=20,
                                                   param1=40, param2=10, 
                                                   minRadius=min_r, maxRadius=max_r)
                        
                        hough_success = False
                        
                        if circles is not None:
                            # Wir haben Hough-Ergebnisse. Starte Ranking!
                            best_coverage = -1
                            best_cx, best_cy = int(circle_x), int(circle_y)
                            
                            found_circles = np.round(circles[0, :]).astype("int")
                            self.log(side, f"🔎 HoughCircles hat {len(found_circles)} Kandidaten gefunden. Starte Ranking...")
                            
                            for (hx, hy, hr) in found_circles:
                                circle_mask = np.zeros_like(thresh_new)
                                cv2.circle(circle_mask, (hx, hy), hr, 255, -1)
                                
                                intersection = cv2.bitwise_and(thresh_new, circle_mask)
                                pixels_in_circle = cv2.countNonZero(circle_mask)
                                pixels_in_intersection = cv2.countNonZero(intersection)
                                
                                coverage_percent = (pixels_in_intersection / pixels_in_circle) * 100 if pixels_in_circle > 0 else 0
                                
                                if coverage_percent > best_coverage:
                                    best_coverage = coverage_percent
                                    best_cx, best_cy = hx, hy

                            self.log(side, f"📊 Bester Kreis hat {best_coverage:.1f}% Weißanteil.")

                            # Reduziert auf 5% wie gewünscht
                            if best_coverage >= 5.0:
                                cx, cy = best_cx, best_cy
                                self.log(side, "✅ HoughCircles erfolgreich: Zentrum wurde über Weiß-Ranking korrigiert.")
                                hough_success = True
                            else:
                                self.log(side, "⚠️ Hough-Sieger hat zu wenig Weißanteil (< 5%). Verwerfe Hough-Ergebnis!")

                        # Gemeinsamer Fallback-Pfad für "Hough liefert Müll" UND "Hough findet nichts"
                        if not hough_success:
                            self.log(side, "⚠️ Wechsle zu Abrisskante / Fallback...")
                            erfolg_abriss = False
                            
                            # 1. Check: Gibt es überhaupt alte Löcher für eine Abrisskante?
                            if state.cumulative_mask is not None and cv2.countNonZero(state.cumulative_mask) > 0:
                                kernel_dilate = np.ones((5, 5), np.uint8)
                                old_holes = cv2.dilate(state.cumulative_mask, kernel_dilate, iterations=1)
                                
                                intersection = cv2.bitwise_and(old_holes, mask)
                                inter_contours, _ = cv2.findContours(intersection, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                                
                                ts_abriss = datetime.now().strftime('%H%M%S_%f')[:-3]
                                self.save_debug_image(f"abrisskante_schnittmenge_{side}_{ts_abriss}", intersection)
                                
                                # 2. Check: Gibt es eine Schnittmenge?
                                if inter_contours:
                                    largest_inter = max(inter_contours, key=cv2.contourArea)
                                    # 3. Check: Ist die Schnittmenge groß genug?
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
                                                    
                                                    # VARIANTE A: SHADOW-MODE
                                                    test_cx = int(cx_int + nx * self.caliber_radius)
                                                    test_cy = int(cy_int + ny * self.caliber_radius)
                                                    self.log(side, f"🧪 TEST-ABRISSKANTE: Theoretisches Zentrum bei X:{test_cx} Y:{test_cy}")
                                                    
                                                    # VARIANTE B: SCHARF-MODUS
                                                    # cx = int(cx_int + nx * self.caliber_radius)
                                                    # cy = int(cy_int + ny * self.caliber_radius)
                                                    # self.log(side, f"🎯 Abrisskante AKTIV! Zentrum gesetzt auf X:{cx} Y:{cy}")
                                                    # erfolg_abriss = True 
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
                                cx, cy = int(circle_x), int(circle_y)
                                self.log(side, f"⚠️ Verwende FALLBACK-Zentrum (minEnclosingCircle) für Wertung: X:{cx} Y:{cy}")
                                
                    else:
                        cx, cy = int(circle_x), int(circle_y)
                        
                elif self.erkennungs_methode == 'B':
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                    else:
                        continue 
                else:
                    (circle_x, circle_y), _ = cv2.minEnclosingCircle(cnt)
                    cx, cy = int(circle_x), int(circle_y)

                # Doppelzählungs-Schutz (mit reparierter Logik!)
                is_new = True
                clipping_factor = 0.15
                for shot in self.sm.shots:
                    if shot['side'] == side:
                        dist = np.hypot(shot['pos'][0] - cx, shot['pos'][1] - cy)
                        if dist < self.caliber_radius * clipping_factor:
                            is_new = False
                            break

                if is_new:
                    new_shots_found_this_frame.append({'cx': cx, 'cy': cy, 'area': area})
                    self.log(side, f"-> NEUES LOCH GEFUNDEN: Pos ({cx}, {cy}) | Fläche {area:.1f}px")
                
        # ---> BLOCK FÜR TREFFER UND DISCARD-MASKEN <---
        if new_shots_found_this_frame or update_mask_only:
            
            # Echte Treffer dem StateManager übergeben
            if new_shots_found_this_frame:
                for s in self.sm.shots:
                    if s['side'] == side:
                        s['is_new'] = False

                for sd in new_shots_found_this_frame:
                    shot = self.sm.add_shot(side, sd['cx'], sd['cy'], sd['area'])
                    self.log(side, f"💥 Treffer gewertet: {shot['score']} Ringe!")
                self.log(side, f"🎯 {len(new_shots_found_this_frame)} neue(r) Treffer bestätigt!")
            
            # Maske für BEIDE Fälle (Treffer & Discard-Risse) updaten
            state.cumulative_mask = cv2.bitwise_or(state.cumulative_mask, thresh_raw)
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
            if self.ausloeser_erschuetterung:
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
                self.log(state.side, "Scheibe außer Sicht -> Warte auf Zielscheibe...")
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