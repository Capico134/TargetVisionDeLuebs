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
        #self.caliber_radius = config.getfloat('Erkennung', 'caliber_radius')
        #self.caliber_durchmesser = config.getfloat('Erkennung', 'caliber_durchmesser') #NICHT NOTWENDIG
        self.hit_tolerance = config.getint('Erkennung', 'hit_tolerance', fallback=25)
        self.erkennungs_methode = config.get('Erkennung', 'erkennungs_methode', fallback='C').upper()
        self.hybrid_riss_faktor = config.getfloat('Erkennung', 'hybrid_riss_faktor', fallback=1.175)
        self.hybrid_sichel_faktor = config.getfloat('Erkennung', 'hybrid_sichel_faktor', fallback=1.05)
        self.hybrid_discard_faktor = config.getfloat('Erkennung', 'hybrid_discard_faktor', fallback=2.5)
        self.hough_min_faktor = config.getfloat('Erkennung', 'hough_min_faktor', fallback=0.85)
        self.hough_max_faktor = config.getfloat('Erkennung', 'hough_max_faktor', fallback=1.15)
        self.ausloeser_durch_erschuetterung = config.getboolean('Erkennung', 'ausloeser_durch_erschuetterung', fallback=False)
        self.max_image_change_percent = config.getfloat('Erkennung', 'max_image_change_percent', fallback=5.0)
        self.debug_alle_bilder_speichern = config.getboolean('Erkennung', 'debug_alle_bilder_speichern', fallback=False)
        self.ringwertung_aktiv = config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
        self.hough_param1 = config.getint('Erkennung', 'hough_param1', fallback=25)
        self.hough_param2 = config.getint('Erkennung', 'hough_param2', fallback=4)
        self.morph_kernel_size = config.getint('Erkennung', 'morph_kernel_size', fallback=5)
        self.max_aspect_ratio = config.getfloat('Erkennung', 'max_aspect_ratio', fallback=3.5)
        # ---> NEU: Die Gewichtung für den 200-Punkte-Score <---
        self.gesamt_anteil_am_200score = config.getfloat('Erkennung', 'gesamt_anteil_am_200score', fallback=0.667)
        # ---> NEU: Extrahierte Magic Numbers <---
        self.abriss_max_edge_percent = config.getfloat('Erkennung', 'abriss_max_edge_percent', fallback=0.75)
        self.abriss_base_bonus = config.getfloat('Erkennung', 'abriss_base_bonus', fallback=10.0)
        self.early_exit_min_score = config.getfloat('Erkennung', 'early_exit_min_score', fallback=145.0)
        self.early_exit_perfect_score = config.getfloat('Erkennung', 'early_exit_perfect_score', fallback=196.0)
        self.min_score_valid = config.getfloat('Erkennung', 'min_score_valid', fallback=70.0)
        self.clipping_factor_history = config.getfloat('Erkennung', 'clipping_factor_history', fallback=0.15)
        self.clipping_factor_current = config.getfloat('Erkennung', 'clipping_factor_current', fallback=0.95)
        self.max_treffer_je_frame = config.getint('Erkennung', 'max_treffer_je_frame', fallback=0)

        # Internes Gedächtnis des Detectors
        self.ref_left = None
        self.ref_right = None
        #self.calib_feedback_left = None #JETZT IN DER GUI
        #self.calib_feedback_right = None #JETZT IN DER GUI

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
        
        # ---> NEU: Wir geben das ganze Paket sauber zurück! <---
        return feedback_data

    def set_reference_image(self, frame, side):
        bgr_blur = cv2.GaussianBlur(frame, (7, 7), 0)
        if side == 'left': self.ref_left = bgr_blur
        else: self.ref_right = bgr_blur
        self.save_debug_image(f"referenz_{side}", frame)
        feedback = None
        if self.ringwertung_aktiv:
            feedback = self.ninja_kalibrierungs_check(bgr_blur, side)
            if feedback:
                self.sm.set_nullpunkt(side, feedback['cx'], feedback['cy']) 
                self.log("SYSTEM", f"🎯 Nullpunkt {side.upper()} gesetzt auf X:{int(feedback['cx'])} Y:{int(feedback['cy'])}", True)
        # ---> NEU: Daten an den Aufrufer (die GUI) weitergeben <---
        return feedback

    def get_caliber_radius(self, side):
        """Berechnet den dynamischen Pixel-Radius anhand der optischen Linsen-Kalibrierung."""
        val = self.config.get('Erkennung', 'caliber_durchmesser', fallback=None)
        
        # 1. Der physikalische Weg (Millimeter) -> Automatisch linsenkorrigiert!
        if val is not None:
            if str(val).strip().lower() == 'auto':
                aktive_scheibe_id = self.config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
                targets = self.dm.load_targets()
                durchmesser_mm = targets.get(aktive_scheibe_id, {}).get('kaliber_mm', 4.5)
            else:
                durchmesser_mm = float(val)
                
            radius_mm = durchmesser_mm / 2.0
            seite_str = "links" if side == 'left' else "rechts"
            px_x = self.config.getfloat('Kameras', f'px_pro_mm_x_{seite_str}', fallback=5.0)
            px_y = self.config.getfloat('Kameras', f'px_pro_mm_y_{seite_str}', fallback=5.0)
            
            # Skaliert den Radius perfekt in Pixel um, basierend auf der aktuellen Kamera
            return radius_mm * ((px_x + px_y) / 2.0)
            
        # 2. ABWÄRTSKOMPATIBILITÄT: Der alte, starre Legacy-Pixel-Radius
        else:
            return self.config.getfloat('Erkennung', 'caliber_radius', fallback=15.0)
            
            


    def detect_new_shot(self, frame, side):
        current_caliber_radius = self.get_caliber_radius(side)
        state = self.sm.state_left if side == 'left' else self.sm.state_right
        reference_bgr = self.ref_left if side == 'left' else self.ref_right
        
        if reference_bgr is None or frame is None: 
            self.log(side, "Fehler: Keine Referenz vorhanden!")
            return False
        
        # ---> NEU: Schutzschild gegen heimliche Crop-Änderungen <---
        if reference_bgr.shape != frame.shape:
            self.log(side, "⚠️ Bildgröße hat sich geändert (Crop)! Erneuere Referenz automatisch...", True)
            self.set_reference_image(frame, side)
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
        
        # ---> NEU: Leere Leinwand für die siegreichen Abrisskanten dieses Frames <---
        frame_abrisskanten = np.zeros_like(thresh_raw)

        # 1. ERST die alten Treffer abziehen (Stanzt den Riss aus)
        if state.cumulative_mask is not None:
            # ---> NEU: Schutzschild für die Maske <---
            if thresh_raw.shape != state.cumulative_mask.shape:
                self.log(side, "⚠️ Maskengröße inkompatibel (Crop)! Setze Maske zurück.", True)
                state.cumulative_mask = np.zeros_like(thresh_raw)
                
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
                current_outer_edge = None # <--- NEU: Platzhalter für diese Iteration
                winning_method = "Unbekannt" # <--- NEU: Sicherheits-Fallback
               
                if self.erkennungs_methode == 'C':
                    kandidaten = []
                    
                    # --- HILFSFUNKTION FÜR DAS BATTLE ROYALE ---
                    def add_candidate(name, c_x, c_y, min_coverage=0.0, bonus=0.0):
                        score, cov_new, _ = self.calculate_hole_score(c_x, c_y, current_caliber_radius, thresh_new, thresh_raw)
                        final_score = score + bonus # <--- NEU: Die Material-Prämie!
                        valid = cov_new >= min_coverage
                        kandidaten.append({
                            'name': name, 'cx': int(c_x), 'cy': int(c_y), 
                            'score': final_score, 'cov_new': cov_new, 'valid': valid
                        })
                        valid_str = "✅" if valid else f"❌ (Zu wenig Riss-Anteil: < {min_coverage}%)"
                        # Vorher:
                        # bonus_str = f" [+{bonus:.1f} Bonus]" if bonus > 0 else ""
                        # Besser und absolut eindeutig:
                        bonus_str = f" (inkl. +{bonus:.1f} Bonus)" if bonus > 0 else ""
                        self.log(side, f"   -> Kandidat [{name}]: X:{int(c_x)} Y:{int(c_y)} | Score: {final_score:.1f}{bonus_str} | Riss-Anteil: {cov_new:.1f}% {valid_str}")
                        return final_score

                    self.log(side, "🔍 Sammle Kandidaten für das Battle Royale...")

                    # 1. BASELINE KANDIDATEN (MEC & CoG)
                    (circle_x, circle_y), radius = cv2.minEnclosingCircle(cnt)
                    add_candidate("MinCircle (MEC)", circle_x, circle_y)

                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cog_x, cog_y = M["m10"] / M["m00"], M["m01"] / M["m00"]
                        add_candidate("Schwerpunkt (CoG)", cog_x, cog_y)
                    else:
                        cog_x, cog_y = circle_x, circle_y
                        
                    # Besten Base-Score für Limit-Checks ermitteln
                    best_base = max(kandidaten, key=lambda x: x['score'])
                    base_score = best_base['score']
                    
                    limit_sichel = current_caliber_radius * self.hybrid_sichel_faktor
                    limit_riss = current_caliber_radius * self.hybrid_riss_faktor
                    limit_discard = current_caliber_radius * self.hybrid_discard_faktor

                    self.log(side, f"📊 Base-Leader: {best_base['name']} (Score: {base_score:.1f}) | Radius: {radius:.1f}px")
                    # ---> WIEDER DA: Die detaillierte Grenzwert-Auflistung in Pixeln <---
                    self.log(side, f"🔍 Check Kontur: Limits -> Sichel < {limit_sichel:.1f}px | Normal | Riss > {limit_riss:.1f}px | Discard > {limit_discard:.1f}px")

                    # DISCARD CHECK (Mega-Störungen sofort abwürgen)
                    if radius > limit_discard:
                        self.log(side, f"🚫 Störung ignoriert (Radius {radius:.1f}px > Limit {limit_discard:.1f}px). Wird maskiert!")
                        update_mask_only = True
                        continue

                    # 2. EARLY EXIT (CPU sparen bei perfekten Löchern)
                    needs_deep_analysis = True
                    if limit_sichel <= radius <= limit_riss and base_score > self.early_exit_min_score:
                        # ---> NEU: Zeigt direkt, dass der Radius in der goldenen Mitte lag <---
                        self.log(side, f"✅ Loch ist in der Norm ({limit_sichel:.1f}px <= {radius:.1f}px <= {limit_riss:.1f}px) und gut gefüllt. Überspringe Deep-Analysis!")
                        needs_deep_analysis = False
                    elif base_score > self.early_exit_perfect_score:
                        # ---> NEU: Zeigt den makellosen Score und den "geretteten" Radius <---
                        self.log(side, f"✅ Form ist makellos (Score {base_score:.1f} > 196), trotz Radius {radius:.1f}px. Überspringe Deep-Analysis!")
                        needs_deep_analysis = False

                    # 3. DEEP ANALYSIS (Hough & Abrisskante)
                    if needs_deep_analysis:
                        self.log(side, "🛠️ Form inperfekt. Aktiviere Deep-Analysis (Hough & Abrisskante)...")
                        
                        mask_for_deep = np.zeros_like(thresh_new)
                        cv2.drawContours(mask_for_deep, [cnt], -1, 255, -1)
                        
                        # --- HOUGH KANDIDAT ---
                        mask_blurred = cv2.GaussianBlur(mask_for_deep, (9, 9), 0)
                        min_r = max(2, int(current_caliber_radius * self.hough_min_faktor))
                        max_r = int(current_caliber_radius * self.hough_max_faktor)
                        
                        circles = cv2.HoughCircles(mask_blurred, cv2.HOUGH_GRADIENT, dp=1, minDist=2,
                                                   param1=self.hough_param1, param2=self.hough_param2, 
                                                   minRadius=min_r, maxRadius=max_r)
                                                   
                        if circles is not None:
                            found_circles = np.round(circles[0, :]).astype("int")
                            self.log(side, f"🔎 Hough hat {len(found_circles)} Kandidaten gefunden. Evaluiere den Besten...")
                            
                            best_hough_score = -1.0
                            best_h_cx, best_h_cy = 0, 0
                            for (hx, hy, hr) in found_circles:
                                h_score, _, _ = self.calculate_hole_score(hx, hy, current_caliber_radius, thresh_new, thresh_raw)
                                if h_score > best_hough_score:
                                    best_hough_score, best_h_cx, best_h_cy = h_score, hx, hy
                                    
                            grenzwert_hough = 7.0 
                            add_candidate("Hough-Sieger", best_h_cx, best_h_cy, min_coverage=grenzwert_hough)

                        # --- ABRISSKANTEN KANDIDATEN ---
                        if state.cumulative_mask is not None and cv2.countNonZero(state.cumulative_mask) > 0:
                            kernel_dilate = np.ones((5, 5), np.uint8)
                            dilated_new = cv2.dilate(mask_for_deep, kernel_dilate, iterations=1)
                            ring = cv2.subtract(dilated_new, mask_for_deep)
                            
                            intact_paper = cv2.bitwise_not(state.cumulative_mask)
                            outer_edge = cv2.bitwise_and(ring, intact_paper)
                            current_outer_edge = outer_edge # <--- NEU: Für den Sieger-Check merken
                            
                            ts_abriss = datetime.now().strftime('%H%M%S_%f')[:-3]
                            self.save_debug_image(f"abrisskante_outer_{side}_{ts_abriss}", outer_edge)
                            #self.save_debug_image(f"letzte_abrisskante_{side}", outer_edge) # <--- Unser Schmuggel-Bild für das Labor!
                            
                            inter_contours, _ = cv2.findContours(outer_edge, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                            if inter_contours:
                                # ---> NEU: Rauschen filtern (nur Kanten > 3 Pixel) <---
                                valid_edges = [cnt for cnt in inter_contours if len(cnt) > 3]
                                
                                if not valid_edges:
                                    self.log(side, "⚠️ Abrisskante gescheitert: Kanten-Fragmente zu klein.")
                                else:
                                    # Erwarteter Umfang und Fläche für einen perfekten Schuss
                                    expected_circ = 2 * np.pi * current_caliber_radius
                                    expected_area = np.pi * (current_caliber_radius ** 2)
                                    
                                    # Dein Tuning-Parameter für den Bonus!
                                    max_edge_percent = self.abriss_max_edge_percent
                                    limit_len = expected_circ * max_edge_percent
                                    
                                    # ---> NEU: Dynamischer Bonus basierend auf der Riss-Größe <---
                                    # Bei einem perfekten Loch ist der Faktor ~1.0 (Bonus bleibt nah an 7.5).
                                    # Bei einem riesigen Riss (z.B. Faktor 1.8) wächst der Bonus linear mit!
                                    area_ratio = area / expected_area if expected_area > 0 else 1.0
                                    dynamic_bonus = self.abriss_base_bonus * area_ratio
                                    
                                    # Haben wir exakt EINE Kante?
                                    is_single_edge = len(valid_edges) == 1
                                    
                                    for e_idx, edge_cnt in enumerate(valid_edges):
                                        # Durch 2 teilen wegen der Hin-und-Zurück-Kontur!
                                        edge_len = cv2.arcLength(edge_cnt, True) / 2.0
                                        
                                        # Der Flächen-Check (Donut vs. Wurst)
                                        edge_area = cv2.contourArea(edge_cnt)
                                        is_closed_ring = edge_area > (current_caliber_radius * current_caliber_radius)
                                        
                                        # Ist die Kante kürzer als unser Limit UND kein geschlossener Ring?
                                        is_true_tear = (edge_len < limit_len) and not is_closed_ring
                                        
                                        # Bonus gibt es NUR bei exakt einer Kante, die auch noch kurz genug ist!
                                        gets_bonus = is_single_edge and is_true_tear
                                        bonus = dynamic_bonus if gets_bonus else 0.0
                                        
                                        M_int = cv2.moments(edge_cnt)
                                        if M_int["m00"] != 0:
                                            cx_float = M_int["m10"] / M_int["m00"]
                                            cy_float = M_int["m01"] / M_int["m00"]
                                        else:
                                            cx_float, cy_float = np.mean(edge_cnt[:,0,0]), np.mean(edge_cnt[:,0,1])
                                            
                                        best_pt = min(edge_cnt, key=lambda pt: np.hypot(pt[0][0] - cx_float, pt[0][1] - cy_float))[0]
                                        cx_edge, cy_edge = best_pt
                                        
                                        # Das Log zeigt dir exakt, warum ein Bonus vergeben oder verweigert wurde
                                        pct_str = int(max_edge_percent * 100)
                                        if gets_bonus:
                                            bonus_log = f" (+{bonus:.1f} Bonus [Faktor {area_ratio:.2f}], Einzelkante & L={edge_len:.1f}px < {pct_str}% Limit {limit_len:.1f}px)"
                                        elif is_closed_ring:
                                            bonus_log = f" (Kein Bonus, Vollkreis erkannt! Area={edge_area:.0f}px)"
                                        elif not is_single_edge:
                                            bonus_log = f" (Kein Bonus, da {len(valid_edges)} Kanten gefunden | L={edge_len:.1f}px)"
                                        else:
                                            bonus_log = f" (Kein Bonus, L={edge_len:.1f}px >= {pct_str}% Limit {limit_len:.1f}px)"
                                            
                                        self.log(side, f"📍 Abrisskante #{e_idx+1} gefunden (Snap-to-Edge): X:{cx_edge} Y:{cy_edge}{bonus_log}")
                                        
                                        grenzwert_abriss = 1.0
                                        
                                        # Kandidaten für Kante X ins Rennen schicken
                                        d_cog = np.hypot(cog_x - cx_edge, cog_y - cy_edge)
                                        if d_cog > 0:
                                            tcx_cog = int(cx_edge + ((cog_x - cx_edge)/d_cog) * current_caliber_radius)
                                            tcy_cog = int(cy_edge + ((cog_y - cy_edge)/d_cog) * current_caliber_radius)
                                            add_candidate(f"Abriss-{e_idx+1}-CoG", tcx_cog, tcy_cog, min_coverage=grenzwert_abriss, bonus=bonus)
                                            
                                        d_mec = np.hypot(circle_x - cx_edge, circle_y - cy_edge)
                                        if d_mec > 0:
                                            tcx_mec = int(cx_edge + ((circle_x - cx_edge)/d_mec) * current_caliber_radius)
                                            tcy_mec = int(cy_edge + ((circle_y - cy_edge)/d_mec) * current_caliber_radius)
                                            add_candidate(f"Abriss-{e_idx+1}-MEC", tcx_mec, tcy_mec, min_coverage=grenzwert_abriss, bonus=bonus)
                            else:
                                self.log(side, "⚠️ Abrisskante gescheitert: Berührt kein intaktes Papier.")

                    # 4. DAS GROSSE BATTLE ROYALE AUSWERTEN
                    valid_candidates = [c for c in kandidaten if c['valid']]
                    
                    if not valid_candidates:
                        # Fallback (Passiert nur, falls Base aus irgendeinem Grund rausfliegt)
                        valid_candidates = kandidaten

                    winner = max(valid_candidates, key=lambda x: x['score'])
                    
                    self.log(side, f"🏆 BATTLE ROYALE SIEGER: {winner['name']} setzt Zentrum (Score {winner['score']:.1f})")
                    
                    cx, cy = winner['cx'], winner['cy']
                    final_shot_score = winner['score']
                    winning_method = winner['name'] # <--- NEU
                    
                    # ---> NEU: Kante nur auf die Leinwand malen, wenn sie das Duell gewinnt! <---
                    if "Abriss" in winner['name'] and current_outer_edge is not None:
                        frame_abrisskanten = cv2.bitwise_or(frame_abrisskanten, current_outer_edge)
                                
                elif self.erkennungs_methode == 'B':
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        final_shot_score, _, _ = self.calculate_hole_score(cx, cy, current_caliber_radius, thresh_new, thresh_raw)     
                        winning_method = "Schwerpunkt (Mode B)" # <--- HIER EINFÜGEN
                    else:
                        continue 
                else:
                    (circle_x, circle_y), _ = cv2.minEnclosingCircle(cnt)
                    cx, cy = int(circle_x), int(circle_y)
                    # HIER FEHLTE DIE ZUWEISUNG:
                    final_shot_score, _, _ = self.calculate_hole_score(cx, cy, current_caliber_radius, thresh_new, thresh_raw)
                    winning_method = "MinCircle (Mode A)" # <--- UND HIER EINFÜGEN
                
                # --- FEHLALARM-FILTER: Score < 70 ---
                if final_shot_score < self.min_score_valid: 
                    self.log(side, f"🚫 Fehlalarm: Score {final_shot_score:.1f} < {self.min_score_valid} -> nicht als Treffer gewertet!")
                    update_mask_only = True
                    continue

                
                # Doppelzählungs-Schutz (Getrennt nach Historie und aktueller Frame-Schleife)
                is_new = True
                
                # 1. Prüfung gegen Historie (alte Treffer aus vorherigen Frames) -> Sehr streng (0.15)
                clipping_factor_history = self.clipping_factor_history
                for shot in self.sm.shots:
                    if shot['side'] == side:
                        dist = np.hypot(shot['pos'][0] - cx, shot['pos'][1] - cy)
                        if dist < current_caliber_radius * clipping_factor_history:
                            is_new = False
                            self.log(side, f"⚠️ Treffer ignoriert (Fläche {area:.1f}px): Zu nah ({dist:.1f}px) an bekanntem alten Schuss!")
                            
                            # ---> NEU: Maske trotzdem updaten, damit der Riss im nächsten Frame ignoriert wird! <---
                            update_mask_only = True 
                            break
                            
                # 2. Prüfung gegen Fragmente aus DIESEM Frame -> Großzügig (0.95), um Sichel-Risse abzuwürgen
                if is_new:
                    clipping_factor_current = self.clipping_factor_current
                    for i, existing_shot in enumerate(new_shots_found_this_frame):
                        dist = np.hypot(existing_shot['cx'] - cx, existing_shot['cy'] - cy)
                        if dist < current_caliber_radius * clipping_factor_current:
                            
                            # ---> NEU: Das Sichel-Duell! Wer hat den höheren Weißanteil? <---
                            if final_shot_score > existing_shot['score']:
                                self.log(side, f"🔄 Sichel-Duell: Neues Fragment (Fläche {area:.1f}px | Score {final_shot_score:.1f}) schlägt altes Fragment ({existing_shot['score']:.1f}).")
                                # Überschreibe den Verlierer mit dem neuen, besseren Kandidaten
                                new_shots_found_this_frame[i] = {'cx': cx, 'cy': cy, 'area': area, 'score': final_shot_score}
                            else:
                                self.log(side, f"⚠️ Treffer ignoriert: Fragment (Fläche {area:.1f}px | Score {final_shot_score:.1f}) verliert Sichel-Duell gegen besseres Fragment ({existing_shot['score']:.1f})!")
                            
                            is_new = False
                            break

                if is_new:
                    new_shots_found_this_frame.append({
                        'cx': cx, 'cy': cy, 'area': area, 'score': final_shot_score,
                        'winner_method': winning_method # <--- NEU
                    })
                    self.log(side, f"-> NEUES LOCH BESTÄTIGT: Pos ({cx}, {cy}) | Fläche {area:.1f}px | Score {final_shot_score:.1f}")
                    
        # =========================================================================
        # ---> NEU: Filter für maximale Trefferanzahl je Frame (nach Fläche) <---
        # =========================================================================
        if self.max_treffer_je_frame > 0 and len(new_shots_found_this_frame) > self.max_treffer_je_frame:
            # Sortiere die validen Treffer absteigend nach ihrer Pixel-Fläche (größte zuerst!)
            new_shots_found_this_frame.sort(key=lambda x: x['area'], reverse=True)
            
            # Trenne die Gewinner von den Verlierern
            verworfen = new_shots_found_this_frame[self.max_treffer_je_frame:]
            new_shots_found_this_frame = new_shots_found_this_frame[:self.max_treffer_je_frame]
            
            # Logge die verworfenen Treffer sauber aus
            for v in verworfen:
                self.log(side, f"✂️ Überzähliger Treffer verworfen (Limit: {self.max_treffer_je_frame}): Pos X:{v['cx']}, Y:{v['cy']} mit Fläche {v['area']:.1f}px")


        # ---> BLOCK FÜR TREFFER UND DISCARD-MASKEN <---
        if new_shots_found_this_frame or update_mask_only:
            
            # Echte Treffer dem StateManager übergeben
            if new_shots_found_this_frame:
                for s in self.sm.shots:
                    if s['side'] == side:
                        s['is_new'] = False

                for sd in new_shots_found_this_frame:
                    shot = self.sm.add_shot(side, sd['cx'], sd['cy'], sd['area'], cv_score=sd.get('score', 0.0))
                    shot['winner_method'] = sd.get('winner_method', 'Unbekannt') # <--- NEU: Direkt an den Schuss heften!
                    
                    # ---> NEU: Schuss-Nummer ermitteln, um das Log mit dem GUI-HUD zu synchronisieren <---
                    shot_num = sum(1 for s in self.sm.shots if s['side'] == side)
                    
                    # ---> NEU: Perfekte Log-Ausgabe mit ID, Koordinaten und 3 Nachkommastellen beim Rohwert <---
                    self.log(side, f"💥 Schuss #{shot_num} | Pos X:{int(sd['cx'])}, Y:{int(sd['cy'])} | {shot['score']:.1f} Ringe (Roh: {shot.get('raw_score', 0.0):.3f})")
                    
                self.log(side, f"🎯 {len(new_shots_found_this_frame)} neue(r) Treffer bestätigt!", True)
            
            # Maske für BEIDE Fälle (Treffer & Discard-Risse) updaten
            state.cumulative_mask = cv2.bitwise_or(state.cumulative_mask, thresh_new)
            self.save_debug_image(f"diff_gesamt_{side}", state.cumulative_mask)
            self.save_debug_image(f"diff_letzter_treffer_{side}", thresh_new)
            self.save_debug_image(f"letzte_aufnahme_{side}", frame)
            
            # ---> NEU: Die gesammelten Sieger-Kanten für das Offline-Labor bereitstellen <--- #######################################################################################################################################################################################################
            self.save_debug_image(f"letzte_abrisskante_{side}", frame_abrisskanten)
            
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