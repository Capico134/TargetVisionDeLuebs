import cv2
import numpy as np
import time
from datetime import datetime
import math
from HelperDeLuebs import Helfer  # <--- NEU: Für die Linsen-Mathematik

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
        
        # ---> NEU: Einmaliges Laden aller Erkennungs-Parameter in schnelle RAM-Attribute <---
        self.refresh_settings_from_config()

        # ---> NEU: Interner Zähler für die Test-Suite (bleibt im Live-Betrieb stumm) <---
        self.eval_counter = 0

        # Internes Gedächtnis des Detectors
        self.ref_left = None
        self.ref_right = None
        
        # --- AUSSCHLIESSLICH FÜR VERSCHIEBUNGSKORREKTUR ---
        # Speichert den zuletzt angewendeten Verschiebungsvektor (dx, dy) je Seite
        self.last_shift = {'left': (0, 0), 'right': (0, 0)}
        # Speichert das allererste Bild, das erstmalig Treffer enthielt (0,0 Referenz)
        self.first_hit_frame = {'left': None, 'right': None}
        # --------------------------------------------------
        
        # --- AUSSCHLIESSLICH FÜR VERSCHIEBUNGSKORREKTUR ---
        #self.last_aligned_left = None
        #self.last_aligned_right = None
        # --------------------------------------------------

    def refresh_settings_from_config(self):
        """Lädt alle performance-kritischen Parameter aus der Config in schnelle Objekt-Attribute."""
        self.min_hole_area = self.config.getint('Erkennung', 'min_hole_area')
        self.hit_tolerance = self.config.getint('Erkennung', 'hit_tolerance', fallback=25)
        self.erkennungs_methode = self.config.get('Erkennung', 'erkennungs_methode', fallback='C').upper()
        self.discard_big_hits = self.config.getfloat('Erkennung', 'discard_big_hits', fallback=3.0)
        self.hough_min_faktor = self.config.getfloat('Erkennung', 'hough_min_faktor', fallback=0.85)
        self.hough_max_faktor = self.config.getfloat('Erkennung', 'hough_max_faktor', fallback=1.15)
        self.ausloeser_durch_erschuetterung = self.config.getboolean('Erkennung', 'ausloeser_durch_erschuetterung', fallback=False)
        self.max_image_change_percent = self.config.getfloat('Erkennung', 'max_image_change_percent', fallback=5.0)
        #self.debug_alle_bilder_speichern = self.config.getboolean('Erkennung', 'debug_alle_bilder_speichern', fallback=False)
        self.detail_export_aktiv = self.config.getboolean('Erkennung', 'detail_export_aktiv', fallback=False) # <--- NEU
        self.ringwertung_aktiv = self.config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
        self.ringwertung_nachkommastellen = self.config.getint('Zielscheibe', 'ringwertung_nachkommastellen', fallback=1) # <--- HIER ERGÄNZEN
        self.hough_param1 = self.config.getint('Erkennung', 'hough_param1', fallback=25)
        self.hough_param2 = self.config.getint('Erkennung', 'hough_param2', fallback=4)
        self.morph_kernel_size = self.config.getint('Erkennung', 'morph_kernel_size', fallback=5)
        self.max_aspect_ratio = self.config.getfloat('Erkennung', 'max_aspect_ratio', fallback=3.5)
        self.gesamt_anteil_am_200score = self.config.getfloat('Erkennung', 'gesamt_anteil_am_200score', fallback=0.667)
        self.abriss_max_edge_percent = self.config.getfloat('Erkennung', 'abriss_max_edge_percent', fallback=0.75)
        self.abriss_base_bonus = self.config.getfloat('Erkennung', 'abriss_base_bonus', fallback=10.0)
        self.min_score_valid = self.config.getfloat('Erkennung', 'min_score_valid', fallback=70.0)
        self.clipping_factor_history = self.config.getfloat('Erkennung', 'clipping_factor_history', fallback=0.15)
        self.clipping_factor_current = self.config.getfloat('Erkennung', 'clipping_factor_current', fallback=0.95)
        self.max_treffer_je_frame = self.config.getint('Erkennung', 'max_treffer_je_frame', fallback=0)
        self.randaufschlag_cumulative = self.config.getint('Erkennung', 'randaufschlag_cumulative', fallback=0)
        
        # Farb-Bonus System
        self.farb_bonus_aktiv = self.config.getboolean('Erkennung', 'farb_bonus_aktiv', fallback=False)
        self.farb_bonus_limit = self.config.getfloat('Erkennung', 'farb_bonus_limit', fallback=150.0)
        self.farb_bonus_kurve = self.config.getfloat('Erkennung', 'farb_bonus_kurve', fallback=2.0)
        self.grenzwert_hough = self.config.getfloat('Erkennung', 'grenzwert_hough', fallback=7.0)
        self.abriss_min_hebel = self.config.getfloat('Erkennung', 'abriss_min_hebel', fallback=0.0)
        
        # ---> NEU: Optische Parameter & Linsen-Geometrie komplett im RAM cachen <---
        self.caliber_durchmesser = self.config.getfloat('Erkennung', 'caliber_durchmesser', fallback=4.5)
        self.px_x_links = self.config.getfloat('Kameras', 'px_pro_mm_x_links', fallback=5.0)
        self.px_y_links = self.config.getfloat('Kameras', 'px_pro_mm_y_links', fallback=5.0)
        self.px_x_rechts = self.config.getfloat('Kameras', 'px_pro_mm_x_rechts', fallback=5.0)
        self.px_y_rechts = self.config.getfloat('Kameras', 'px_pro_mm_y_rechts', fallback=5.0)
        
        aktive_scheibe = self.config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
        targets = self.dm.load_targets()
        
        # =========================================================================
        # BEISPIEL-STRUKTUR für self.lens_cache:
        # {
        #     'left': {
        #         'korr':       -0.0004455,    # Linsenverzerrung k1
        #         'korr_r4':     0.000000699,  # Linsenverzerrung k2 (r^4)
        #         'lens_cx':     570.0,        # Optische Linsenmitte X (in Pixeln)
        #         'lens_cy':     540.0,        # Optische Linsenmitte Y (in Pixeln)
        #         'r_limit_mm':  25.0,         # Limit-Korsett für die Entzerrung in mm
        #         'px_x':        18.9,         # Pixel pro mm (X-Achse)
        #         'px_y':        18.9          # Pixel pro mm (Y-Achse)
        #     },
        #     'right': { ... analog ... }
        # }
        # =========================================================================
        self.lens_cache = {}
        for s_key, s_str, c_sec in [('left', 'links', 'Crop_Links'), ('right', 'rechts', 'Crop_Rechts')]:
            korr = self.config.getfloat('Kameras', f'linsen_verzerrung_{s_str}', fallback=0.0)
            korr_r4 = self.config.getfloat('Kameras', f'linsen_verzerrung_{s_str}_r4', fallback=0.0)
            cam_w = self.config.getint('Kameras', f'cam_width_{s_str}', fallback=1280)
            cam_h = self.config.getint('Kameras', f'cam_height_{s_str}', fallback=720)
            cut_l = self.config.getint(c_sec, 'cut_left', fallback=0)
            cut_t = self.config.getint(c_sec, 'cut_top', fallback=0)
            off_x = self.config.getint('Kameras', f'lens_offset_x_{s_str}', fallback=0)
            off_y = self.config.getint('Kameras', f'lens_offset_y_{s_str}', fallback=0)
            cfg_lim = self.config.getfloat('Kameras', f'linsen_verzerrung_limit_{s_str}', fallback=0.0)
            
            lcx, lcy = Helfer.get_optical_center(cam_w, cam_h, cut_l, cut_t, off_x, off_y)
            r_lim = Helfer.get_r_limit(targets, aktive_scheibe, config_limit_mm=cfg_lim)
            
            self.lens_cache[s_key] = {
                'korr': korr, 'korr_r4': korr_r4,
                'lens_cx': lcx, 'lens_cy': lcy, 'r_limit_mm': r_lim,
                'px_x': self.px_x_links if s_key == 'left' else self.px_x_rechts,
                'px_y': self.px_y_links if s_key == 'left' else self.px_y_rechts
            }
        
        self.blur_kernel_size = self.config.getint('Erkennung', 'blur_kernel_size', fallback=7)
        # --- AUSSCHLIESSLICH FÜR VERSCHIEBUNGSKORREKTUR ---
        self.verschiebungskorrektur = self.config.getboolean('Erkennung', 'verschiebungskorrektur', fallback=False)
        # --------------------------------------------------

    def save_debug_image(self, name, image):
        # Der Live-Manager schiebt das Bild in die Warteschlange.
        # Der DummyManager (Labor) blockiert oder speichert physisch.
        result = self.dm.save_debug_image(name, image)
        
        # ---> DER FIX: Wir loggen das Bild NUR, wenn der Manager explizit True zurückgibt!
        if result is True:
            self.log("SYSTEM", f"📸 Debug-Bild gespeichert: {name}")

    def normalize_brightness(self, ref, live):
        """Passt ausschließlich die globale Helligkeit des Live-Bildes an das Referenzbild an."""
        mean_ref = cv2.mean(ref)[:3]
        mean_live = cv2.mean(live)[:3]
        diff = np.array(mean_ref) - np.array(mean_live)
        live_float = live.astype(np.float32)
        live_float += diff
        return np.clip(live_float, 0, 255).astype(np.uint8)

    def calculate_raw_diff_mask(self, reference_bgr, current_normalized, side):
        """
        ELA-Hilfsmethode: Berechnet das rohe binäre Differenzbild (thresh_raw) 
        OHNE Abzug von Diff-Gesamt (inkl. Color-Hack und optionalem Farb-Bonus).
        """
        # NEUE FARBERKENNUNG
        diff_bgr = cv2.absdiff(reference_bgr, current_normalized)
        # ---> DER COLOR-HACK: Wir nehmen einfach den maximalen Ausschlag aus B, G oder R <---
        # Verhindert, dass massive Rot-Änderungen von der Graustufen-Formel verschluckt werden!
        diff_gray = np.max(diff_bgr, axis=2)

        # =========================================================================
        # ---> NEU: Der smoothe Farb-Bonus (NORMALIZED RGB / CHROMINANCE) <---
        # =========================================================================
        if self.farb_bonus_aktiv:
            farb_bonus_limit = self.farb_bonus_limit
            farb_bonus_kurve = self.farb_bonus_kurve

            bg_sec = 'Hintergrund_Links' if side == 'left' else 'Hintergrund_Rechts'
            r_tgt = self.config.getint(bg_sec, 'rgb_r')
            g_tgt = self.config.getint(bg_sec, 'rgb_g')
            b_tgt = self.config.getint(bg_sec, 'rgb_b')

            # 1. Ziel-Farbe normalisieren
            sum_tgt = float(r_tgt + g_tgt + b_tgt)
            if sum_tgt == 0: sum_tgt = 1.0
            target_norm = np.array([b_tgt/sum_tgt, g_tgt/sum_tgt, r_tgt/sum_tgt], dtype=np.float32)

            # 2. Live-Bild normalisieren
            live_float = current_normalized.astype(np.float32)
            live_sum = np.sum(live_float, axis=2, keepdims=True)
            live_sum[live_sum == 0] = 1.0
            live_norm = live_float / live_sum

            # 3. Distanz berechnen (Faktor 1000 für schöne Werte)
            dist_matrix = np.linalg.norm(live_norm - target_norm, axis=2) * 1000.0

            # ---> ELA-konforme Multiplikator-Logik mit Rausch-Plateau <---
            multiplier = 1.0 - (dist_matrix / farb_bonus_limit)
            multiplier = np.clip(multiplier * 1.15, 0.0, 1.0)

            if farb_bonus_kurve != 1.0:
                multiplier = multiplier ** farb_bonus_kurve

            # Diff-Werte bestrafen (abdunkeln)
            diff_gray = np.clip(diff_gray.astype(np.float32) * multiplier, 0, 255).astype(np.uint8)

        _, thresh_raw = cv2.threshold(diff_gray, self.hit_tolerance, 255, cv2.THRESH_BINARY)
        return thresh_raw

    # =========================================================================
    # --- AUSSCHLIESSLICH FÜR VERSCHIEBUNGSKORREKTUR ---
    # =========================================================================
    def _shift_image_exact(self, img, dx, dy):
        """
        Verschiebt ein Bild exakt um ganzzahlige Pixel (dx, dy):
        Positives dx schiebt den Bildinhalt nach RECHTS, negatives dx nach LINKS.
        Positives dy schiebt den Bildinhalt nach UNTEN, negatives dy nach OBEN.
        """
        if dx == 0 and dy == 0:
            return img.copy()
        h, w = img.shape[:2]
        # In OpenCV ohne WARP_INVERSE_MAP gilt: dst(x, y) = src(x - tx, y - ty).
        # Damit der Inhalt um +dx wandert, muss tx = +dx in der Matrix stehen.
        M = np.float32([[1, 0, float(dx)], [0, 1, float(dy)]])
        return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)

    def _export_shift_layers(self, side, shot_count, ref_00_img, orig_unshifted, target_mask,
                             thresh_unshifted, thresh_shifted, orig_shifted, best_dx, best_dy,
                             cov_zero, cov_best):
        """
        Exportiert alle Ebenen der Verschiebungskorrektur als echte mehrschichtige .ora (GIMP/Krita)
        UND .svg (Inkscape/Browser) Datei mit 100% transparentem Hintergrund bei Masken/Diffs.
        Wird NUR ausgeführt, wenn im Labor der Bilder-Export aktiviert ist!
        """
        # Prüfen, ob wir im Labor sind und der Bildexport-Haken aktiv ist
        app = getattr(self.dm, 'app', None)
        if not app or not hasattr(app, 'export_images_var') or not app.export_images_var.get():
            return

        import os
        import zipfile
        import base64

        export_folder = getattr(self.dm, 'export_folder', 'labor_export')
        os.makedirs(export_folder, exist_ok=True)
        h, w = thresh_unshifted.shape[:2]

        # ---> ELA-FIX: Erlaubt harte Kanten ODER weiche Heatmaps! <---
        def mask_to_bgra(mask, b, g, r, base_alpha=170, draw_outline=False, soft=False):
            bgra = np.zeros((h, w, 4), dtype=np.uint8)
            if soft:
                # Weiche Heatmap: Grauwert der Maske bestimmt die Transparenz!
                # (100% Weiß in der Maske = base_alpha in der Grafik)
                alpha_channel = (mask.astype(np.float32) / 255.0 * base_alpha).astype(np.uint8)
                active = alpha_channel > 0
                bgra[active, 0] = b
                bgra[active, 1] = g
                bgra[active, 2] = r
                bgra[active, 3] = alpha_channel[active]
            else:
                # Klassisch harte Kante
                active = mask > 127
                bgra[active, 0] = b
                bgra[active, 1] = g
                bgra[active, 2] = r
                bgra[active, 3] = base_alpha
                if draw_outline:
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(bgra, contours, -1, (b, g, r, 255), 2)
            return bgra

        def bgr_to_bgra(bgr_img):
            return cv2.cvtColor(bgr_img, cv2.COLOR_BGR2BGRA)

        # 1. Ebene: Info & Verschiebungsvektor (Transparentes Overlay ganz oben)
        info_bgra = np.zeros((h, w, 4), dtype=np.uint8)
        box_overlay = np.zeros((110, 680, 4), dtype=np.uint8)
        box_overlay[:, :] = (20, 20, 20, 210)
        info_bgra[15:125, 15:695] = box_overlay

        txt1 = f"Verschiebungskorrektur (Anker-Treffer: {shot_count}) | Seite: {side.upper()}"
        txt2 = f"Korrektur-Vektor: X = {best_dx:+d} px, Y = {best_dy:+d} px"
        txt3 = f"Treffer-Deckung: {cov_zero:.1f}% (unverschoben) -> {cov_best:.1f}% (korrigiert)"
        cv2.putText(info_bgra, txt1, (30, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255, 255), 2)
        cv2.putText(info_bgra, txt2, (30, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255, 255), 2)
        cv2.putText(info_bgra, txt3, (30, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (100, 255, 100, 255), 2)

        # Vektor-Pfeil in der Bildmitte zeichnen (20x gestreckt für klare Sichtbarkeit)
        cx, cy = w // 2, h // 2
        cv2.circle(info_bgra, (cx, cy), 5, (0, 255, 255, 255), -1)
        if best_dx != 0 or best_dy != 0:
            end_pt = (int(cx + best_dx * 1), int(cy + best_dy * 1))
            cv2.arrowedLine(info_bgra, (cx, cy), end_pt, (0, 255, 255, 255), 1, tipLength=0.25)

        # 2. Alle gewünschten Ebenen zusammenstellen (von oben nach unten im Ebenen-Stapel)
        layers = [
            ("07_Info_und_Vektor", info_bgra, "normal", 1.0),
            ("06_Diff_Verschoben_GRUEN", mask_to_bgra(thresh_shifted, 0, 255, 0, base_alpha=160), "normal", 1.0),
            ("05_Diff_Unverschoben_ROT", mask_to_bgra(thresh_unshifted, 0, 0, 255, base_alpha=160), "normal", 1.0),
            # ---> NEU: 'soft=True' zeichnet das weiche Gravitationsfeld exakt so, wie die Mathematik es berechnet! <---
            ("04_Suchbereich_Heatmap_CYAN", mask_to_bgra(target_mask, 255, 255, 0, base_alpha=180, soft=True), "normal", 1.0),
            ("03_Bild_Aktuell_Verschoben", bgr_to_bgra(orig_shifted), "normal", 1.0),
            ("02_Bild_Aktuell_Unverschoben", bgr_to_bgra(orig_unshifted), "normal", 1.0),
            ("01_Referenz_Bild1_0_0", bgr_to_bgra(ref_00_img), "normal", 1.0),
        ]

        ts = datetime.now().strftime('%H%M%S')
        base_filename = f"ShiftLayers_Anker{shot_count:02d}_{side}_{ts}"
        ora_path = os.path.join(export_folder, f"{base_filename}.ora")
        svg_path = os.path.join(export_folder, f"{base_filename}.svg")

        # A) OpenRaster (.ora) schreiben -> Direkt in GIMP / Krita / Paint.NET mit allen Ebenen zu öffnen!
        stack_xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<image version="0.0.3" w="{w}" h="{h}" xres="72" yres="72">',
            '  <stack>'
        ]
        svg_lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        ]

        with zipfile.ZipFile(ora_path, 'w', compression=zipfile.ZIP_STORED) as zf:
            # mimetype muss laut Spezifikation unkomprimiert als erstes rein
            zf.writestr('mimetype', 'image/openraster')

            for idx, (l_name, bgra_img, _, opacity) in enumerate(layers):
                ok, png_buf = cv2.imencode('.png', bgra_img)
                if not ok:
                    continue
                png_bytes = png_buf.tobytes()
                internal_path = f"data/{l_name}.png"
                zf.writestr(internal_path, png_bytes)
                stack_xml_lines.append(
                    f'    <layer name="{l_name}" src="{internal_path}" x="0" y="0" opacity="{opacity:.2f}" visibility="visible" composite-op="svg:src-over"/>'
                )

            # Mini-Vorschaubild & Merged-Image für GIMP-Kompatibilität
            ok_m, merged_buf = cv2.imencode('.png', bgr_to_bgra(orig_shifted))
            if ok_m:
                zf.writestr('mergedimage.png', merged_buf.tobytes())
                thumb = cv2.resize(orig_shifted, (min(256, w), int(h * (min(256, w) / float(w)))))
                _, thumb_buf = cv2.imencode('.png', thumb)
                zf.writestr('Thumbnails/thumbnail.png', thumb_buf.tobytes())

            stack_xml_lines.append('  </stack>')
            stack_xml_lines.append('</image>')
            zf.writestr('stack.xml', "\n".join(stack_xml_lines))

        # B) Zusätzlich als .svg mit eingebetteten Inkscape-Ebenen speichern (in umgekehrter Reihenfolge: unten -> oben)
        for l_name, bgra_img, _, opacity in reversed(layers):
            ok, png_buf = cv2.imencode('.png', bgra_img)
            if not ok:
                continue
            b64_str = base64.b64encode(png_buf.tobytes()).decode('ascii')
            svg_lines.append(
                f'  <g inkscape:groupmode="layer" id="{l_name}" inkscape:label="{l_name}" style="display:inline;opacity:{opacity:.2f}">'
                f'<image x="0" y="0" width="{w}" height="{h}" xlink:href="data:image/png;base64,{b64_str}"/></g>'
            )
        svg_lines.append('</svg>')
        with open(svg_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(svg_lines))

        self.log("SYSTEM", f"📸 Ebenen-Paket gespeichert: {base_filename}.ora (GIMP) & .svg (Inkscape/Browser)")

    # =========================================================================
    # --- AUSSCHLIESSLICH FÜR VERSCHIEBUNGSKORREKTUR ---
    # =========================================================================
    def align_frame_by_shots(self, reference_bgr, current_normalized, side):
        """Zweistufige Image Registration: 1. Grob über Zielscheibe, 2. Fein über Schusslöcher"""
        prev_shots = self.sm.get_shots_for_side(side)
        h, w = current_normalized.shape[:2]

        # =========================================================================
        # STUFE 1: GROB-AUSRICHTUNG (Die Ringe der Zielscheibe)
        # Verhindert, dass der Algorithmus bei weiten OBS-Sprüngen auf neue Löcher springt!
        # =========================================================================
        gray_ref = cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2GRAY)
        gray_live = cv2.cvtColor(current_normalized, cv2.COLOR_BGR2GRAY)
        
        y1, y2 = int(h * 0.2), int(h * 0.8)
        x1, x2 = int(w * 0.2), int(w * 0.8)
        hann = cv2.createHanningWindow((x2 - x1, y2 - y1), cv2.CV_32F)
        
        roi_ref = gray_ref[y1:y2, x1:x2].astype(np.float32)
        roi_live = gray_live[y1:y2, x1:x2].astype(np.float32)
        
        # phaseCorrelate liefert den Shift UND die Response (Konfidenz zwischen 0.0 und 1.0)
        (dx_c, dy_c), response = cv2.phaseCorrelate(roi_ref, roi_live, window=hann)
        
        # ---> DIE ADAPTIVE WEICHE <---
        # Ein typischer guter Wert für scharfe Bilder liegt oft über 0.05 (5%).
        # Bei matschigen Analogbildern oder fehlendem schwarzen Spiegel bricht er ein.
        CONFIDENCE_THRESHOLD = 0.04 
        
        if response >= CONFIDENCE_THRESHOLD:
            # 1. Bild ist scharf & kontrastreich genug -> Grobe Korrektur anwenden!
            coarse_dx = int(round(-dx_c))
            coarse_dy = int(round(-dy_c))
            
            # Rausch-Filter für Grob-Shift: Nur bei echten Sprüngen (> 1px)
            if abs(coarse_dx) < 2 and abs(coarse_dy) < 2:
                coarse_dx, coarse_dy = 0, 0
                
            fine_search_radius = 5  # Die Mikro-Leine (Wir liegen grob ja schon perfekt)
            self.log(side, f"🔎 Grob-Ausrichtung (Sicherheit {response*100:.1f}%): Shift X:{coarse_dx:+d}, Y:{coarse_dy:+d}")
        else:
            # 2. Bild ist zu "matschig" oder kontextarm (Analog / 50m) -> Grob-Shift ignorieren!
            coarse_dx, coarse_dy = 0, 0
            fine_search_radius = 35  # Große Leine (50m Löcher liegen weit auseinander)
            self.log(side, f"⚠️ Grob-Ausrichtung unsicher (Sicherheit {response*100:.1f}% < {CONFIDENCE_THRESHOLD*100:.1f}%). Nutze erweiterten Suchradius ({fine_search_radius}px).")

        # Bild grob vorschieben (passiert nur, wenn Konfidenz hoch genug war)
        coarse_shifted = self._shift_image_exact(current_normalized, coarse_dx, coarse_dy)

        # Wenn noch gar keine Treffer da sind, bleibt es bei der Grob-Korrektur!
        if not prev_shots:
            self.last_shift[side] = (coarse_dx, coarse_dy)
            if self.first_hit_frame.get(side) is None:
                self.first_hit_frame[side] = coarse_shifted.copy()
            return coarse_shifted, (coarse_dx, coarse_dy)

        # =========================================================================
        # STUFE 2: FEIN-AUSRICHTUNG (Die Schusslöcher)
        # =========================================================================
        # Wir erzeugen das Diff-Bild auf Basis der bereits (ggf.) grob korrigierten Ringe!
        thresh_raw_coarse = self.calculate_raw_diff_mask(reference_bgr, coarse_shifted, side)
        
        # ---> MAGIC NUMBERS FÜR WEICHEN SUCHBEREICH (WEIGHTED TEMPLATE) <---
        # Setze boost auf 0.0 und blur auf 0, um alles auf den harten Standard zurückzusetzen
        magic_radius_boost = 3.0  # Erweitert den Schablonen-Kreis um X Pixel
        magic_blur_kernel = 9     # Muss ungerade sein (z.B. 5, 9, 15)
        # -------------------------------------------------------------------

        # ---> DER ADAPTIVE RADIUS <---
        max_shift = fine_search_radius  
        target_mask = np.zeros((h, w), dtype=np.uint8)
        
        shift_bits = 4
        multiplier = 1 << shift_bits
        x_min_all, y_min_all = w, h
        x_max_all, y_max_all = 0, 0

        # Schablonen der alten Löcher zeichnen
        for shot in prev_shots:
            sx, sy = shot['pos']
            
            # ---> DER ELA-FIX: Den Drift herausrechnen! <---
            old_dx = shot.get('shift_x', 0)
            old_dy = shot.get('shift_y', 0)
            clean_sx = sx - old_dx
            clean_sy = sy - old_dy
            
            r_local = shot.get('cal_radius') or self.get_local_caliber_radius(side, clean_sx, clean_sy)
            
            # ---> NEU: Radius für den weichen Trichter vergrößern <---
            r_local += magic_radius_boost
            
            sub_cx = int(round((clean_sx - 0.5) * multiplier))
            sub_cy = int(round((clean_sy - 0.5) * multiplier))
            sub_r  = int(round((r_local - 0.707 / 2.0) * multiplier))
            cv2.circle(target_mask, (sub_cx, sub_cy), sub_r, 255, -1, cv2.LINE_8, shift=shift_bits)

            r_pad = int(r_local) + max_shift + 2
            x_min_all = min(x_min_all, max(0, int(clean_sx) - r_pad))
            y_min_all = min(y_min_all, max(0, int(clean_sy) - r_pad))
            x_max_all = max(x_max_all, min(w, int(clean_sx) + r_pad))
            y_max_all = max(y_max_all, min(h, int(clean_sy) + r_pad))

        # ---> DER 1-ZEILER FÜR DAS WEICHE STERNBILD <---
        if magic_blur_kernel > 0:
            target_mask = cv2.GaussianBlur(target_mask, (magic_blur_kernel, magic_blur_kernel), 0)

        # ---> NEU: Die Gesamtpixel als Gewichtungssumme berechnen (statt hartem countNonZero) <---
        total_template_pixels = float(np.sum(target_mask)) / 255.0

        if total_template_pixels <= 0 or x_max_all <= x_min_all or y_max_all <= y_min_all:
            self.last_shift[side] = (coarse_dx, coarse_dy)
            return coarse_shifted, (coarse_dx, coarse_dy)

        # Schnelle 2D-Korrelation im winzigen Suchfenster (CCOEFF_NORMED ignoriert Scheiben-Schlieren!)
        t_x1 = max(0, x_min_all + max_shift)
        t_y1 = max(0, y_min_all + max_shift)
        t_x2 = min(w, x_max_all - max_shift)
        t_y2 = min(h, y_max_all - max_shift)

        if t_x2 <= t_x1 or t_y2 <= t_y1:
            self.last_shift[side] = (coarse_dx, coarse_dy)
            return coarse_shifted, (coarse_dx, coarse_dy)

        template_crop = (target_mask[t_y1:t_y2, t_x1:t_x2]).astype(np.float32)
        search_crop = (thresh_raw_coarse[
            t_y1 - max_shift : t_y2 + max_shift,
            t_x1 - max_shift : t_x2 + max_shift
        ]).astype(np.float32)

        res = cv2.matchTemplate(search_crop, template_crop, cv2.TM_CCOEFF_NORMED)
        
        # ---> NEU: Pixeldeckungen über gewichtete Summe (np.sum) zählen <---
        zero_hits = float(np.sum(cv2.bitwise_and(thresh_raw_coarse, target_mask))) / 255.0
        cov_zero = (zero_hits / total_template_pixels) * 100.0

        best_dx, best_dy = 0, 0
        cov_best = cov_zero
        final_shifted = coarse_shifted
        thresh_raw_final = thresh_raw_coarse

        # ---> ELA FIX: Mehrere starke Peaks (Kandidaten) suchen! <---
        res_blurred = cv2.GaussianBlur(res, (3, 3), 0)
        _, max_val, _, _ = cv2.minMaxLoc(res_blurred)
        threshold_res = max_val * 0.90 
        
        y_locs, x_locs = np.where(res_blurred >= threshold_res)
        
        peak_candidates = []
        for x, y in zip(x_locs, y_locs):
            is_new = True
            for cx, cy in peak_candidates:
                if abs(x - cx) <= 2 and abs(y - cy) <= 2:
                    is_new = False
                    break
            if is_new:
                peak_dx = -(x - max_shift)
                peak_dy = -(y - max_shift)
                if peak_dx != 0 or peak_dy != 0:
                    peak_candidates.append((peak_dx, peak_dy))

        # ---> BATTLE ROYALE FÜR DIE VERSCHIEBUNGSVEKTOREN <---
        best_cand_hits = zero_hits
        
        for cand_dx, cand_dy in peak_candidates:
            cand_thresh_sim = self._shift_image_exact(thresh_raw_coarse, cand_dx, cand_dy)
            
            # ---> NEU: Gewichtete Deckung für die Kandidaten! <---
            verified_hits = float(np.sum(cv2.bitwise_and(cand_thresh_sim, target_mask))) / 255.0
            
            dist_pixels = math.hypot(cand_dx, cand_dy)
            required_bonus_hits = total_template_pixels * ((dist_pixels ** 2) * 0.0025) 
            
            penalized_hits = verified_hits - required_bonus_hits
            
            if penalized_hits > best_cand_hits:
                best_cand_hits = penalized_hits
                best_dx, best_dy = cand_dx, cand_dy

        # ---> JETZT ERST DEN SIEGER ECHT BERECHNEN <---
        if best_dx != 0 or best_dy != 0:
            final_shifted = self._shift_image_exact(coarse_shifted, best_dx, best_dy)
            thresh_raw_final = self.calculate_raw_diff_mask(reference_bgr, final_shifted, side)
            
            # ---> NEU: Gewichtete Deckung für den endgültigen Sieger! <---
            final_hits = float(np.sum(cv2.bitwise_and(thresh_raw_final, target_mask))) / 255.0
            cov_best = (final_hits / total_template_pixels) * 100.0
        else:
            final_shifted = coarse_shifted
            thresh_raw_final = thresh_raw_coarse
            cov_best = cov_zero
                
        total_dx = coarse_dx + best_dx
        total_dy = coarse_dy + best_dy

        if total_dx != 0 or total_dy != 0:
            self.log(side, f"⚙️ Verschiebungskorrektur ({len(prev_shots)} Anker): Grob X:{coarse_dx:+d} Y:{coarse_dy:+d} | Fein X:{best_dx:+d} Y:{best_dy:+d} (Deckung: {cov_zero:.1f}% -> {cov_best:.1f}%).")
        else:
            self.log(side, f"🛡️ Verschiebungskorrektur ({len(prev_shots)} Anker): X:+0px, Y:+0px ist optimal (Deckung: {cov_zero:.1f}%).")

        # Optionaler Ebenen-Export
        ref_00 = self.first_hit_frame.get(side)
        if ref_00 is None: 
            ref_00 = reference_bgr
            
        self._export_shift_layers(
            side=side, shot_count=len(prev_shots), ref_00_img=ref_00,
            orig_unshifted=current_normalized, target_mask=target_mask,
            thresh_unshifted=self.calculate_raw_diff_mask(reference_bgr, current_normalized, side),
            thresh_shifted=thresh_raw_final, orig_shifted=final_shifted,
            best_dx=total_dx, best_dy=total_dy, cov_zero=cov_zero, cov_best=cov_best
        )

        self.last_shift[side] = (total_dx, total_dy)
        return final_shifted, (total_dx, total_dy)
    # =========================================================================

    def calculate_hole_score(self, cx, cy, radius, thresh_new, thresh_raw, export_details=False):
        """
        Berechnet den Score mit unbestechlichem harten Supersampling.
        Optional: Exportiert die exakten Subpixel-Daten für das Labor-HUD!
        """
																	
        self.eval_counter += 1
        
        # 1. Bounding Box (ROI) um den Treffer berechnen (+2 Pixel Puffer)
        r_int = int(radius) + 2
        x1 = max(0, int(cx) - r_int)
        y1 = max(0, int(cy) - r_int)
        x2 = min(thresh_new.shape[1], int(cx) + r_int)
        y2 = min(thresh_new.shape[0], int(cy) + r_int)
        
        roi_w = x2 - x1
        roi_h = y2 - y1
        
        if roi_w <= 0 or roi_h <= 0:
            if export_details: return 0.0, 0.0, 0.0, None
            return 0.0, 0.0, 0.0
            
        local_cx = cx - x1
        local_cy = cy - y1
        
        # ---> NEU: Echter Supersampling-Faktor (1 physischer Pixel wird zu 4x4=16 Subpixeln) <---
        scale = 4
        
        # 2. Die originalen ROIs ausschneiden
        roi_new = thresh_new[y1:y2, x1:x2]
        roi_raw = thresh_raw[y1:y2, x1:x2]
        
        # 3. Hartes Hochskalieren (NEAREST bewahrt die pixeligen, harten Treppenstufen!)
        roi_new_highres = cv2.resize(roi_new, (roi_w * scale, roi_h * scale), interpolation=cv2.INTER_NEAREST)
        roi_raw_highres = cv2.resize(roi_raw, (roi_w * scale, roi_h * scale), interpolation=cv2.INTER_NEAREST)
        # 4. Hochauflösende Kreis-Maske erstellen
        circle_mask_highres = np.zeros((roi_h * scale, roi_w * scale), dtype=np.uint8)
        
        
        # Variante G: Der OpenCV Subpixel-Shift (Perfekt symmetrisch) + Geometric Offset
        shift_bits = 4               
        multiplier = 1 << shift_bits # = 16
        # Der 0.5 Offset ist zwingend nötig, um den cv2.circle auf das 
        # INTER_NEAREST Raster (welches links-oben verankert ist) zu zentrieren!
        offset = 0.5
        sub_cx = int(round((local_cx * scale - offset) * multiplier))
        sub_cy = int(round((local_cy * scale - offset) * multiplier))
        # Der Radius braucht keinen Offset, da er eine reine Längenangabe ist
        #sub_r  = int(round(radius * scale * multiplier))
        sub_r = int(round(((radius * scale- 0.707/2)) * multiplier))
        cv2.circle(circle_mask_highres, (sub_cx, sub_cy), sub_r, 255, -1, cv2.LINE_8, shift=shift_bits)
        

        ##A)
        ##scaled_cx = int(round(local_cx * scale))
        ##scaled_cy = int(round(local_cy * scale))
        ##B)
        ##scaled_cx = int(round((local_cx + 0.5) * scale - 0.5))
        ##scaled_cy = int(round((local_cy + 0.5) * scale - 0.5))		  
        ##C)
        ##scaled_cx = int(round((local_cx ) * scale - 0.5))
        ##scaled_cy = int(round((local_cy ) * scale - 0.5))	
        ##D)
        ##scaled_cx = int(round((local_cx ) * scale - 0.7071))
        ##scaled_cy = int(round((local_cy ) * scale - 0.7071))	        
        ##F)
        #scaled_cx = int(round((local_cx ) * scale - 0.501))
        #scaled_cy = int(round((local_cy ) * scale - 0.501))
        #scaled_r = int(round(radius * scale))
        #cv2.circle(circle_mask_highres, (scaled_cx, scaled_cy), scaled_r, 255, -1, cv2.LINE_8)
        
        #pixels_in_circle = cv2.countNonZero(circle_mask_highres)
        #if pixels_in_circle == 0: 
        #    if export_details: return 0.0, 0.0, 0.0, None
        #    return 0.0, 0.0, 0.0
        ## 5. Echte, binäre Schnittmengen bilden (0 oder 255)
        #intersection_new = cv2.bitwise_and(circle_mask_highres, roi_new_highres)
        #intersection_raw = cv2.bitwise_and(circle_mask_highres, roi_raw_highres)
        #pixels_in_new = cv2.countNonZero(intersection_new)
        #pixels_in_raw = cv2.countNonZero(intersection_raw)
        #coverage_new = (pixels_in_new / pixels_in_circle) * 100.0
        #coverage_raw = (pixels_in_raw / pixels_in_circle) * 100.0
        #weight_new = 1.0 - self.gesamt_anteil_am_200score
        #total_score = 2.0 * ((coverage_new * weight_new) + (coverage_raw * self.gesamt_anteil_am_200score))
        
       
        # 5. Echte, binäre Schnittmengen bilden (0 oder 255)
        intersection_new = cv2.bitwise_and(circle_mask_highres, roi_new_highres)
        intersection_raw = cv2.bitwise_and(circle_mask_highres, roi_raw_highres)
        pixels_in_new = cv2.countNonZero(intersection_new)
        pixels_in_raw = cv2.countNonZero(intersection_raw)
        # ---> DER FIX: Wir nutzen die exakte mathematische Fläche statt zitternder Raster-Pixel! <---
        # Da wir 'scale' verwendet haben, müssen wir den Radius für die Flächenformel ebenfalls skalieren.
        ideal_pixels_in_circle = math.pi * (radius * scale) ** 2
        if ideal_pixels_in_circle == 0: 
            if export_details: return 0.0, 0.0, 0.0, None
            return 0.0, 0.0, 0.0
        # min(100.0, ...) stellt sicher, dass wir durch Rasterungs-Rundungen 
        # niemals astronomische Werte über 100% erhalten können.
        coverage_new = min(100.0, (pixels_in_new / ideal_pixels_in_circle) * 100.0)
        coverage_raw = min(100.0, (pixels_in_raw / ideal_pixels_in_circle) * 100.0)
        weight_new = 1.0 - self.gesamt_anteil_am_200score
        total_score = 2.0 * ((coverage_new * weight_new) + (coverage_raw * self.gesamt_anteil_am_200score))
        
        
        # =========================================================================
        # ---> NEU: DER SUBPIXEL-DATEN-EXPORT FÜR DAS LABOR <---
        # =========================================================================
        if export_details:
            # ---> DER FIX: reshape(-1, 2) bügelt alle OpenCV-Dimensionen glatt! <---
            pts_new = cv2.findNonZero(intersection_new)
            if pts_new is not None:
                list_new = [(int(pt[0]), int(pt[1])) for pt in pts_new.reshape(-1, 2)]
            else:
                list_new = []
            
            pts_raw = cv2.findNonZero(intersection_raw)
            if pts_raw is not None:
                list_raw = [(int(pt[0]), int(pt[1])) for pt in pts_raw.reshape(-1, 2)]
            else:
                list_raw = []
            
            details = {
                'scale': scale,          # Skalierungsfaktor (Wichtig fürs Labor zum Rückrechnen!)
                'offset_x': x1,          # Die echte X-Startkoordinate der Bounding-Box im Originalbild
                'offset_y': y1,          # Die echte Y-Startkoordinate der Bounding-Box im Originalbild
                'local_cx': local_cx,    # Der Mittelpunkt innerhalb der Bounding Box
                'local_cy': local_cy,
                'radius': radius,        # Der exakte Radius in Original-Pixeln
                'subpixels_new': list_new, # Liste aller X/Y Subpixel des NEUEN Risses (Orange)
                'subpixels_raw': list_raw  # Liste aller X/Y Subpixel des RAW Hintergrunds (Rot)
            }
            return total_score, coverage_new, coverage_raw, details
            
        return total_score, coverage_new, coverage_raw
            

    def resolve_tie_breaker(self, candidates, anker_x, anker_y):
        """
        ELA-Zentrum für Gleichstände: Findet den Sieger aus einer Liste von Kandidaten.
        1. Höchster Score gewinnt.
        2. Bei Gleichstand (auf 1 Nachkommastelle): Nächster zum Anker gewinnt.
        
        Gibt den Sieger-Kandidaten sowie eine Liste aller "Tied"-Kandidaten (fürs Log) zurück.
        """
        best_score = -1.0
        best_cand = None
        best_dist = float('inf')
        tied_candidates = []

        for cand in candidates:
            # Toleranz: Wir runden auf 1 Nachkommastelle für den Gleichstands-Check
            cand_score_rounded = round(cand['score'], 1)
            best_score_rounded = round(best_score, 1)
            dist_to_anker = np.hypot(cand['cx'] - anker_x, cand['cy'] - anker_y)
            
            # Wichtig: Distanz für späteres Logging sichern
            cand['_dist'] = dist_to_anker

            # 1. Höherer Score gewinnt IMMER
            if cand_score_rounded > best_score_rounded:
                best_score = cand['score']
                best_cand = cand
                best_dist = dist_to_anker
                tied_candidates = [cand] # Alte Verlierer wegschmeißen
                
            # 2. Bei GLEICHSTAND: Kandidat vermerken
            elif cand_score_rounded == best_score_rounded:
                tied_candidates.append(cand)
                
                # Wenn er näher am Anker ist, übernimmt er intern die Krone
                if dist_to_anker < best_dist:
                    best_score = cand['score']
                    best_cand = cand
                    best_dist = dist_to_anker
                    
        return best_cand, tied_candidates
        
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
        k = self.blur_kernel_size
        
        # ---> ELA-FIX: Wenn der Blur-Kernel 0 (oder ungültig) ist, 
        # überspringen wir den Gauß-Filter komplett und nehmen das rohe Bild! <---
        if k > 0 and k % 2 == 1:
            bgr_blur = cv2.GaussianBlur(frame, (k, k), 0)
        else:
            bgr_blur = frame.copy()
        
        if side == 'left': 
            self.ref_left = bgr_blur
            # --- AUSSCHLIESSLICH FÜR VERSCHIEBUNGSKORREKTUR ---
            self.last_shift['left'] = (0, 0)
            self.first_hit_frame['left'] = None
        else: 
            self.ref_right = bgr_blur
            # --- AUSSCHLIESSLICH FÜR VERSCHIEBUNGSKORREKTUR ---
            self.last_shift['right'] = (0, 0)
            self.first_hit_frame['right'] = None
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
        """Berechnet den dynamischen Pixel-Radius im Linsen-Zentrum (Basis)."""
        radius_mm = self.caliber_durchmesser / 2.0
        if side == 'left':
            return radius_mm * ((self.px_x_links + self.px_y_links) / 2.0)
        else:
            return radius_mm * ((self.px_x_rechts + self.px_y_rechts) / 2.0)

    def get_local_caliber_radius(self, side, x_px, y_px):
        """
        Berechnet den linsenkorrigierten Kaliber-Radius exakt als Mittelwert 
        der beiden Ellipsen-Halbachsen (radial & tangential) aus draw_smart_ellipse.
        """
        base_r_px = self.get_caliber_radius(side)
        lc = self.lens_cache.get(side)
        if not lc or (lc['korr'] == 0.0 and lc['korr_r4'] == 0.0):
            return base_r_px
            
        dx_mm = (x_px - lc['lens_cx']) / lc['px_x']
        dy_mm = (y_px - lc['lens_cy']) / lc['px_y']
        r_mm_center = math.hypot(dx_mm, dy_mm)
        
        if r_mm_center <= 0.05:
            return base_r_px
            
        # Exakt dieselbe Skalierungsberechnung wie in Helfer.draw_smart_ellipse (is_hit=True):
        r_cal_mm = self.caliber_durchmesser / 2.0
        scale_tangential, _ = Helfer.get_ellipse_scales(r_mm_center, lc['korr'], lc['korr_r4'], r_limit=lc['r_limit_mm'])
        
        r_eval = abs(r_mm_center - (r_cal_mm / 2.0))
        _, scale_radial = Helfer.get_ellipse_scales(r_eval, lc['korr'], lc['korr_r4'], r_limit=lc['r_limit_mm'])
        
        # Mittelwert aus beiden Ellipsen-Radien (große + kleine Halbachse durch 2)
        avg_lens_scale = max(0.5, min(1.5, 0.5 * (scale_radial + scale_tangential)))
        return base_r_px * avg_lens_scale

    def detect_new_shot(self, frame, side):
        current_caliber_radius = self.get_caliber_radius(side)
        state = self.sm.state_left if side == 'left' else self.sm.state_right
        reference_bgr = self.ref_left if side == 'left' else self.ref_right
        
        # 1. ERST auf None prüfen:
        if reference_bgr is None or frame is None: 
            self.log(side, "Fehler: Keine Referenz oder kein Frame vorhanden!")
            return False
        
        # 2. DANN erst auf die Bilddimensionen zugreifen:
        if reference_bgr.shape != frame.shape:
            self.log(side, "⚠️ Bildgröße hat sich geändert (Crop)! Erneuere Referenz automatisch...", True)
            self.set_reference_image(frame, side)
            return False
        
        k = self.blur_kernel_size
        if k > 0 and k % 2 == 1:
            current_bgr_blur = cv2.GaussianBlur(frame, (k, k), 0) 
        else:
            current_bgr_blur = frame.copy()
            
        # 1. Helligkeit anpassen
        current_normalized = self.normalize_brightness(reference_bgr, current_bgr_blur)

        # =========================================================================
        # --- AUSSCHLIESSLICH FÜR VERSCHIEBUNGSKORREKTUR (SCHRITT 1) ---
        # Korrigiert die Bildposition anhand der alten Treffer-Landmarks
        # =========================================================================
        applied_shift = (0, 0)
        if self.verschiebungskorrektur:
            current_normalized, applied_shift = self.align_frame_by_shots(
                reference_bgr, current_normalized, side
            )
        # =========================================================================

        # SCHRITT 2: Rohes Diff-Bild des (ggf. verschobenen) Bildes erzeugen
        # (Nutzt dieselbe gemeinsame Methode, um perfekt sauber zu arbeiten!)
        thresh_raw = self.calculate_raw_diff_mask(reference_bgr, current_normalized, side)

        # Ab hier läuft deine gewohnte Masken-Verarbeitung weiter:
        if state.cumulative_mask is not None:
            if thresh_raw.shape != state.cumulative_mask.shape:
                self.log(side, "⚠️ Maskengröße inkompatibel (Crop)! Setze Maske zurück.", True)
                state.cumulative_mask = np.zeros_like(thresh_raw)

                
            # =========================================================================
            # ---> DER FIX: Schutz gegen tanzende Löcher (Kamerawackler) & JPG-Artefakte
            # =========================================================================
            # 1. Alte Masken (oft JPGs aus der 480p-Zeit) absolut sauber auf Schwarz/Weiß zwingen
            _, pure_mask = cv2.threshold(state.cumulative_mask, 127, 255, cv2.THRESH_BINARY)
            # 2. Den "Schutzrand": Maske aufblähen, um Kameraverschiebungen abzufangen
            # VORERST AUSKOMMENTIERT: Idee für später, vor dem Derby kein Risiko!
            # kernel_wobble = np.ones((5, 5), np.uint8)
            # safe_mask = cv2.dilate(pure_mask, kernel_wobble, iterations=1)
            safe_mask = pure_mask # <--- Wir nutzen einfach direkt die desinfizierte Maske!

            # Jetzt stanzen wir mit der massiven, abgedichteten Maske!
            thresh_new = cv2.subtract(thresh_raw, safe_mask)
            # Zerstört alle restlichen grauen Schlieren
            _, thresh_new = cv2.threshold(thresh_new, 127, 255, cv2.THRESH_BINARY)
        else:
            thresh_new = thresh_raw.copy()
            state.cumulative_mask = np.zeros_like(thresh_raw)

        # 2. DANN den Morph-Filter auf die rohen NEUEN Fragmente anwenden!
        k_size = self.morph_kernel_size
        if k_size > 0:
            kernel = np.ones((k_size, k_size), np.uint8)
            thresh_new = cv2.morphologyEx(thresh_new, cv2.MORPH_CLOSE, kernel)

        # ---> DEIN GENIALER STREICH: Ab hier wird thresh_raw zum kompletten "Diff-Gesamt" <---
        # Enthält garantiert alle historischen Pixel (inkl. alter Morph-Brücken) + den neuen gemorphten Riss!
        thresh_raw = cv2.bitwise_or(state.cumulative_mask, thresh_new)

        changed_pixels = cv2.countNonZero(thresh_new)
        total_pixels = thresh_new.shape[0] * thresh_new.shape[1]
        change_percent = (changed_pixels / total_pixels) * 100
        
        if change_percent > self.max_image_change_percent:
            # ---> NEU: 3 Nachkommastellen <---
            self.log(side, f"⚠️ SANITY CHECK FEHLGESCHLAGEN: Neuer Zuwachs zu {change_percent:.3f}%")
            self.log(side, "-> Ignoriere Frame.")
            return False
            
        ##DEBUG-Ausgabe
        #import os
        #export_dir = "labor_export"
        #os.makedirs(export_dir, exist_ok=True)
        #cv2.imwrite(os.path.join(export_dir, "DETECTION_00_thresh_new.png"), thresh_new)

        contours, _ = cv2.findContours(thresh_new, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        new_shots_found_this_frame = []
        update_mask_only = False 
        
        if self.ausloeser_durch_erschuetterung or len(contours) > 0:
            # ---> NEU: 3 Nachkommastellen <---
            self.log(side, f"Analysiere Konturen... (Neuer Zuwachs: {change_percent:.3f}% | Konturen: {len(contours)})")

        for c_idx, cnt in enumerate(contours):
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

                # =========================================================================
                # ---> TEST: Lokalen Kaliber-Radius inkl. Linsenkorrektur für diese Kontur!
                # =========================================================================
                #WENN MAN DAS AUSKOMMENTIERT IST ALLES WIE VORHER!
                current_caliber_radius = self.get_local_caliber_radius(side, rx + rw / 2.0, ry + rh / 2.0)

                # Globale Variablen für diesen Treffer initialisieren
                final_shot_score = 0.0
                cx, cy = 0, 0
                current_outer_edge = None # <--- NEU: Platzhalter für diese Iteration
                winning_method = "Unbekannt" # <--- NEU: Sicherheits-Fallback
               
                if self.erkennungs_methode == 'C':
                    kandidaten = []
                    
                    # --- HILFSFUNKTION FÜR DAS BATTLE ROYALE ---
                    def add_candidate(name, c_x, c_y, min_coverage=0.0, bonus=0.0, base_pos=None, end_pos=None, cand_radius=None):
                        score, cov_new, _ = self.calculate_hole_score(c_x, c_y, current_caliber_radius, thresh_new, thresh_raw)
                        final_score = score + bonus
                        valid = cov_new >= min_coverage
                        
                        bp = (float(base_pos[0]), float(base_pos[1])) if base_pos else (float(c_x), float(c_y))
                        ep = (float(end_pos[0]), float(end_pos[1])) if end_pos else (float(c_x), float(c_y))
                        
                        kandidaten.append({
                            'name': name, 'cx': float(c_x), 'cy': float(c_y), 
                            'score': final_score, 'cov_new': cov_new, 'valid': valid,
                            'base_pos': bp, 'end_pos': ep,
                            'mec_radius': cand_radius,
                            'cal_radius': float(current_caliber_radius) # <--- NEU: Lokaler Prüf-Radius
                        })
                        
                        valid_str = "✅" if valid else f"❌ (Zu wenig Flächen-Ratio: < {min_coverage}%)"
                        bonus_str = f" (inkl. +{bonus:.2f} Bonus)" if bonus > 0 else ""
                        
                        # =====================================================================
                        # ---> NEU: Perfekt ausgerichtete, tabellarische Log-Mauer <---
                        # =====================================================================
                        name_part = f"Kandidat [{name}]:"
                        
                        if "Abriss" in name:
                            # Feste Breite für die Koordinaten (je >6.2f), damit die Spalten exakt stehen!
                            bp_str = f"{bp[0]:>6.2f}, {bp[1]:>6.2f}"
                            ep_str = f"{ep[0]:>6.2f}, {ep[1]:>6.2f}"
                            path_part = f"Kante ({bp_str}) -> Rumpf ({ep_str})"
                        else:
                            # Exakt 53 Leerzeichen, um die Lücke für die Nicht-Abriss-Kandidaten zu füllen
                            path_part = "-" * 48 
                            
                        # Einheitliches Ziel-Format für ALLE Kandidaten
                        ziel_part = f" - Ziel X:{c_x:>6.2f} Y:{c_y:>6.2f} "
                        
                        # Zusammenbauen: Name (auf 34 Zeichen fixiert) + Path (53 Zeichen) + Ziel
                        full_prefix = f"{name_part:<34} {path_part}{ziel_part}"
                        
                        # Rest mit Bindestrichen bis zur rechtsbündigen Score-Mauer auffüllen
                        padded_prefix = f"{full_prefix:-<110}>"
                        
                        self.log(side, f"--> {padded_prefix} Score: {final_score:5.1f}{bonus_str} | Flächen-Ratio: {cov_new:5.1f}% {valid_str}")
                        return final_score

                    self.log(side, "🔍 Sammle Kandidaten für das Battle Royale...")

                    # 1. BASELINE KANDIDATEN (MEC & CoG)
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        # ---> DER FIX: +0.5 für die echte physikalische Mitte! <---
                        cog_x, cog_y = (M["m10"] / M["m00"]) + 0.5, (M["m01"] / M["m00"]) + 0.5
                        base_pos = (int(cog_x), int(cog_y))
                        # ---> NEU: Fester 1.0 Bonus für den Schwerpunkt (Heimvorteil gegen Rand-Schätzer) <---
                        add_candidate("Schwerpunkt (CoG)", cog_x, cog_y, bonus=1.0)
                    else:
                        (circle_x, circle_y), _ = cv2.minEnclosingCircle(cnt)
                        base_pos = (int(circle_x), int(circle_y))
                        cog_x, cog_y = float(circle_x) + 0.5, float(circle_y) + 0.5 # Fallback
                        
                    (circle_x, circle_y), radius = cv2.minEnclosingCircle(cnt)
                    # ---> DER FIX: Mittelpunkt und Radius auf die Pixel-Quadrate anpassen! <---
                    circle_x += 0.5
                    circle_y += 0.5
                    radius += 0.5+0.2071# !!FIXXX!!
                    
                    # ---> NEU: Radius an den Kandidaten übergeben <---
                    add_candidate("MinCircle (MEC)", circle_x, circle_y, cand_radius=float(radius))

                    # Besten Base-Score für Limit-Checks ermitteln
                    best_base = max(kandidaten, key=lambda x: x['score'])
                    base_score = best_base['score']
                    
                    limit_discard = current_caliber_radius * self.discard_big_hits

                    self.log(side, f"📊 Base-Leader: {best_base['name']} (Score: {base_score:.1f}) | Radius: {radius:.1f}px (Discard-Limit: {limit_discard:.1f}px)")

                    # =====================================================================
                    # ---> DER FIX: Den dynamischen Tie-Breaker Anker HIER definieren! <---
                    # =====================================================================
                    expected_area = np.pi * (current_caliber_radius ** 2)
                    raw_area_ratio = area / expected_area if expected_area > 0 else 1.0
                    
                    if raw_area_ratio >= 0.80:
                        anker_x, anker_y = cog_x, cog_y
                        anker_name = "CoG"
                    else:
                        anker_x, anker_y = circle_x, circle_y
                        anker_name = "MEC"
                        
                    self.log(side, f"⚓ Tie-Breaker Anker gesetzt auf: {anker_name} (Flächen-Ratio: {raw_area_ratio*100:.1f}%)")

                    # 2. DISCARD CHECK (Mega-Störungen & Mini-Fragmente sofort abwürgen)
                    if radius > limit_discard:
                        self.log(side, f"🚫 Störung ignoriert (Radius {radius:.1f}px > Limit {limit_discard:.1f}px). Wird maskiert!")
                        update_mask_only = True
                        continue

                    # ---> ELA-OPTIMIERUNG: Frühzeitiger Abbruch bei chancenlosen Rauschen/Fehlalarmen <---
                    # Basierend auf dem Worst-Case von stark überlappenden Sicheln (~20% vom min_score_valid).
                    min_base_score = self.min_score_valid * 0.2
                    if base_score < min_base_score:
                        self.log(side, f"🚫 Fehlalarm (Basis): Score {base_score:.1f} < {min_base_score:.1f} (20% von min_score_valid) -> Deep-Analysis übersprungen!")
                        update_mask_only = True
                        continue

                    # 3. DEEP ANALYSIS (Hough & Abrisskante laufen jetzt IMMER mit!)
                    # self.log(side, "🔬 >>> DEEP-ANALYSIS WIRD IMMER AUSGEFUEHRT <<< (Hough & Abrisskanten-Check)")
                        
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
                        found_circles = circles[0, :]
                        self.log(side, f"🔎 Hough hat {len(found_circles)} Kandidaten gefunden. Evaluiere den Besten...")
                        
                        # Vorberechnung für den ultraschnellen Einschluss-Check
                        cnt_pts = cnt.reshape(-1, 2)
                        max_r_sq = (current_caliber_radius + 1.0) ** 2
                        
                        # 1. Alle lokal verankerten Hough-Kreise in das Kandidaten-Format pressen
                        hough_cands = []
                        for (hx, hy, hr) in found_circles:
                            # A) Option 1 (C++ PointPolygonTest): Liegt (hx, hy) überhaupt nah genug 
                            # an der Kontur 'cnt', damit der Kaliber-Kreis sie signifikant erreicht?
                            dist_to_cnt = cv2.pointPolygonTest(cnt, (float(hx), float(hy)), True)
                            if dist_to_cnt < -(current_caliber_radius * 0.85):
                                continue
                                
                            # B) Konkavitäts-Schutz: Wenn der Mittelpunkt außerhalb von 'cnt' liegt, 
                            # müssen mind. 25% der Konturpunkte von 'cnt' im Kaliber-Kreis liegen 
                            # (verhindert, dass ein Kreis nur die Spitze streift und beim Nachbarn klaut).
                            if dist_to_cnt < 0:
                                pts_inside = np.count_nonzero(((cnt_pts[:, 0] - hx) ** 2 + (cnt_pts[:, 1] - hy) ** 2) <= max_r_sq)
                                if pts_inside < max(3, int(len(cnt_pts) * 0.25)):
                                    continue

                            h_score, _, _ = self.calculate_hole_score(hx, hy, current_caliber_radius, thresh_new, thresh_raw)
                            hough_cands.append({'cx': float(hx), 'cy': float(hy), 'score': h_score})
                            
                        # 2. Die Tie-Breaker-Jury rufen (nur wenn valide lokale Kreise übrig sind!)
                        if hough_cands:
                            best_hough, tied_hough = self.resolve_tie_breaker(hough_cands, anker_x, anker_y)
                            # 3. Logging
                            if len(tied_hough) > 1:
                                self.log(side, f"   ⚖️ GLEICHSTAND (Hough): {len(tied_hough)} Kreise mit Top-Score ({round(best_hough['score'], 1)}).")
                                for i, cand in enumerate(tied_hough):
                                    is_winner = (cand['cx'] == best_hough['cx'] and cand['cy'] == best_hough['cy'])
                                    marker = "👑 SIEGER" if is_winner else "❌"
                                    self.log(side, f"      -> Opt {i+1}: X:{cand['cx']:.2f} Y:{cand['cy']:.2f} | Distanz zum Anker ({anker_name}): {cand['_dist']:.2f}px {marker}")
                            add_candidate("Hough-Sieger", best_hough['cx'], best_hough['cy'], min_coverage=self.grenzwert_hough)
                        else:
                            self.log(side, f"   🚫 Alle {len(found_circles)} Hough-Kreise verworfen (kein Kreis schließt die aktuelle Fläche sinnvoll ein).")

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
                        
                        #inter_contours, _ = cv2.findContours(outer_edge, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        inter_contours, _ = cv2.findContours(outer_edge, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
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
                                
                                
                                # =========================================================================
                                # ---> DYNAMISCHER ABRISS-BONUS (Die "Scharnier"-Logik) <---
                                # =========================================================================
                                # Physischer Hintergrund: Schlägt ein Diabolo nah an einem alten Loch ein, 
                                # reißt oft ein massives Stück Papier weg, das nur noch an einem kleinen 
                                # Steg (der eigentlichen Einschlagstelle) gehalten wurde.
                                # 
                                # Ein reiner Flächen-Algorithmus (CoG/MEC) würde fälschlicherweise die Mitte 
                                # dieses riesigen Risses als Treffer werten. Wir wollen aber exakt den Steg!
                                # 
                                # Quadratischer Multiplikator: 
                                # Je gigantischer die weggerissene Fläche im Verhältnis zur normalen Kaliber-
                                # fläche (area_ratio) ist, desto extremer pushen wir den Score der Abrisskante.
                                # So gewinnt die Kante das Battle Royale bei fetten Rissen garantiert gegen CoG, 
                                # während saubere Einzellöcher (area_ratio ~ 1.0) kaum Bonus erhalten.
                                area_ratio = area / expected_area if expected_area > 0 else 1.0
                                faktor = max(0.0, area_ratio + 0.0) ** 2
                                dynamic_bonus = self.abriss_base_bonus * faktor
                                
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
                                    
                                    # =====================================================================
                                    # ---> DIE EIERLEGENDE WOLLMILCHSAU (Classic vs. Dynamic) <---
                                    # =====================================================================
                                    # 1. Startpunkt Variante A: Der Flächenschwerpunkt des Risses (Classic)
                                    M_int = cv2.moments(edge_cnt)
                                    if M_int["m00"] != 0:
                                        cx_float = M_int["m10"] / M_int["m00"]
                                        cy_float = M_int["m01"] / M_int["m00"]
                                    else:
                                        cx_float, cy_float = np.mean(edge_cnt[:,0,0]), np.mean(edge_cnt[:,0,1])
                                        
                                    # =========================================================================
                                    # ---> DER HD-RÖNTGENBLICK: ECHTE LABOR-PIXEL ISOLIEREN <---
                                    # =========================================================================
                                    # Wir malen die Kontur extra dick (5 Pixel) als "Schablone"
                                    blob_mask = np.zeros_like(outer_edge)
                                    cv2.drawContours(blob_mask, [edge_cnt], -1, 255, thickness=5)
                                    
                                    # Jetzt schneiden wir mit der Schablone die echten Pixel aus der Labor-Maske aus!
                                    # Das Donut-Loch bleibt leer, weil "outer_edge" dort schwarz ist.
                                    isolated_edge = cv2.bitwise_and(outer_edge, blob_mask)
                                    
                                    pts_raw = cv2.findNonZero(isolated_edge)
                                    
                                    if pts_raw is not None:
                                        all_pixels = pts_raw.reshape(-1, 2)
                                    else:
                                        all_pixels = edge_cnt.reshape(-1, 2)
                                        
                                    pixel_liste = [(int(pt[0]), int(pt[1])) for pt in all_pixels]
                                    
                                    # ---> DEBUG LOGGING <---
                                    #self.log(side, f"🔴 DEBUG Abrisskante #{e_idx+1}:")
                                    #self.log(side, f"   -> Berechnetes COG (Classic): X:{cx_float:.2f}, Y:{cy_float:.2f}")
                                    #self.log(side, f"   -> Echte Labor-Pixel genutzt: {len(pixel_liste)} (reiner Kontur-Rand war {len(edge_cnt)})")
                                    
                                    # Wir suchen im Array der echten Masken-Pixel nach dem besten Startpunkt!
                                    best_pt_center = min(pixel_liste, key=lambda pt: np.hypot(pt[0] - cx_float, pt[1] - cy_float))
                                    cx_edge_center = float(best_pt_center[0]) + 0.5
                                    cy_edge_center = float(best_pt_center[1]) + 0.5
                                    
                                    # 2. Startpunkt Variante B: Der kürzeste Weg zum Rumpf (Dynamic)
                                    best_pt_cog = min(pixel_liste, key=lambda pt: np.hypot(pt[0] - cog_x, pt[1] - cog_y))
                                    cx_edge_cog = float(best_pt_cog[0]) + 0.5
                                    cy_edge_cog = float(best_pt_cog[1]) + 0.5
                                    
                                    best_pt_mec = min(pixel_liste, key=lambda pt: np.hypot(pt[0] - circle_x, pt[1] - circle_y))
                                    cx_edge_mec = float(best_pt_mec[0]) + 0.5
                                    cy_edge_mec = float(best_pt_mec[1]) + 0.5
                                    
                                    # Das Log zeigt dir exakt, warum ein Bonus vergeben oder verweigert wurde
                                    pct_str = int(max_edge_percent * 100)
                                    if gets_bonus:
                                        bonus_log = f" (+{bonus:.2f} Bonus [Faktor {area_ratio:.2f}], L={edge_len:.1f}px < {pct_str}% Limit)"
                                    elif is_closed_ring:
                                        bonus_log = f" (Kein Bonus, Vollkreis! Area={edge_area:.0f}px)"
                                    elif not is_single_edge:
                                        bonus_log = f" (Kein Bonus, {len(valid_edges)} Kanten gefunden)"
                                    else:
                                        bonus_log = f" (Kein Bonus, L={edge_len:.1f}px >= {pct_str}% Limit)"
                                        
                                    prefix_abriss = f"Kante #{e_idx+1} (Classic vs. Dynamic) "
                                    padded_abriss = f"{prefix_abriss:-<45}>"
                                    
                                    self.log(side, f"📍 {padded_abriss}{bonus_log}")
                                    
                                    # Das Sicherheitsnetz für das "Hebel-Problem"
                                    min_hebel = self.abriss_min_hebel 
                                    grenzwert_abriss = 2.4 #4.58 
                                    
                                    # ---> KANDIDAT 1: CoG (Classic - Riss-Mitte) <---
                                    d_cog_center = np.hypot(cog_x - cx_edge_center, cog_y - cy_edge_center)
                                    if d_cog_center > min_hebel:
                                        tcx = cx_edge_center + ((cog_x - cx_edge_center)/d_cog_center) * (current_caliber_radius+0.25)
                                        tcy = cy_edge_center + ((cog_y - cy_edge_center)/d_cog_center) * (current_caliber_radius+0.25)
                                        add_candidate(f"Abriss-{e_idx+1}-CoG (Classic)", tcx, tcy, min_coverage=grenzwert_abriss, bonus=bonus, base_pos=(cx_edge_center, cy_edge_center), end_pos=(cog_x, cog_y))
                                    else:
                                        self.log(side, f"⚠️ Abriss-{e_idx+1}-CoG (Classic) ignoriert: Hebel zu kurz ({d_cog_center:.2f}px < {min_hebel}px).")
                                        
                                    # ---> KANDIDAT 2: MEC (Classic - Riss-Mitte) <---
                                    d_mec_center = np.hypot(circle_x - cx_edge_center, circle_y - cy_edge_center)
                                    if d_mec_center > min_hebel:
                                        tcx = cx_edge_center + ((circle_x - cx_edge_center)/d_mec_center) * (current_caliber_radius+0.25)
                                        tcy = cy_edge_center + ((circle_y - cy_edge_center)/d_mec_center) * (current_caliber_radius+0.25)
                                        add_candidate(f"Abriss-{e_idx+1}-MEC (Classic)", tcx, tcy, min_coverage=grenzwert_abriss, bonus=bonus, base_pos=(cx_edge_center, cy_edge_center), end_pos=(circle_x, circle_y))
                                    else:
                                        self.log(side, f"⚠️ Abriss-{e_idx+1}-MEC (Classic) ignoriert: Hebel zu kurz ({d_mec_center:.2f}px < {min_hebel}px).")

                                    # ---> KANDIDAT 3: CoG (Dynamic - Kürzester Weg) <---
                                    d_cog_dyn = np.hypot(cog_x - cx_edge_cog, cog_y - cy_edge_cog)
                                    if d_cog_dyn > min_hebel:
                                        tcx = cx_edge_cog + ((cog_x - cx_edge_cog)/d_cog_dyn) * (current_caliber_radius+0.25)
                                        tcy = cy_edge_cog + ((cog_y - cy_edge_cog)/d_cog_dyn) * (current_caliber_radius+0.25)
                                        add_candidate(f"Abriss-{e_idx+1}-CoG (Dynamic)", tcx, tcy, min_coverage=grenzwert_abriss, bonus=bonus, base_pos=(cx_edge_cog, cy_edge_cog), end_pos=(cog_x, cog_y))
                                    else:
                                        self.log(side, f"⚠️ Abriss-{e_idx+1}-CoG (Dynamic) ignoriert: Hebel zu kurz ({d_cog_dyn:.2f}px < {min_hebel}px).")

                                    # ---> KANDIDAT 4: MEC (Dynamic - Kürzester Weg) <---
                                    d_mec_dyn = np.hypot(circle_x - cx_edge_mec, circle_y - cy_edge_mec)
                                    if d_mec_dyn > min_hebel:
                                        tcx = cx_edge_mec + ((circle_x - cx_edge_mec)/d_mec_dyn) * (current_caliber_radius+0.25)
                                        tcy = cy_edge_mec + ((circle_y - cy_edge_mec)/d_mec_dyn) * (current_caliber_radius+0.25)
                                        add_candidate(f"Abriss-{e_idx+1}-MEC (Dynamic)", tcx, tcy, min_coverage=grenzwert_abriss, bonus=bonus, base_pos=(cx_edge_mec, cy_edge_mec), end_pos=(circle_x, circle_y))
                                    else:
                                        self.log(side, f"⚠️ Abriss-{e_idx+1}-MEC (Dynamic) ignoriert: Hebel zu kurz ({d_mec_dyn:.2f}px < {min_hebel}px).")

                                    # =====================================================================
                                    # ---> KANDIDAT 5: CROSS 1 (Start: CoG-Rand ➔ Peilung: MEC) <---
                                    # =====================================================================
                                    d_cross1 = np.hypot(circle_x - cx_edge_cog, circle_y - cy_edge_cog)
                                    if d_cross1 > min_hebel:
                                        tcx = cx_edge_cog + ((circle_x - cx_edge_cog)/d_cross1) * (current_caliber_radius+0.25)
                                        tcy = cy_edge_cog + ((circle_y - cy_edge_cog)/d_cross1) * (current_caliber_radius+0.25)
                                        add_candidate(f"Abriss-{e_idx+1}-X (CoG->MEC)", tcx, tcy, min_coverage=grenzwert_abriss, bonus=bonus, base_pos=(cx_edge_cog, cy_edge_cog), end_pos=(circle_x, circle_y))
                                    else:
                                        self.log(side, f"⚠️ Abriss-{e_idx+1}-X (CoG->MEC) ignoriert: Hebel zu kurz ({d_cross1:.2f}px < {min_hebel}px).")

                                    # =====================================================================
                                    # ---> KANDIDAT 6: CROSS 2 (Start: MEC-Rand ➔ Peilung: CoG) <---
                                    # =====================================================================
                                    d_cross2 = np.hypot(cog_x - cx_edge_mec, cog_y - cy_edge_mec)
                                    if d_cross2 > min_hebel:
                                        tcx = cx_edge_mec + ((cog_x - cx_edge_mec)/d_cross2) * (current_caliber_radius+0.25)
                                        tcy = cy_edge_mec + ((cog_y - cy_edge_mec)/d_cross2) * (current_caliber_radius+0.25)
                                        add_candidate(f"Abriss-{e_idx+1}-X (MEC->CoG)", tcx, tcy, min_coverage=grenzwert_abriss, bonus=bonus, base_pos=(cx_edge_mec, cy_edge_mec), end_pos=(cog_x, cog_y))
                                    else:
                                        self.log(side, f"⚠️ Abriss-{e_idx+1}-X (MEC->CoG) ignoriert: Hebel zu kurz ({d_cross2:.2f}px < {min_hebel}px).")
                        else:
                            self.log(side, "⚠️ Abrisskante gescheitert: Berührt kein intaktes Papier.")
                            
                    # ---> NEU: Erklärung für Schuss #1 <---
                    else:
                        self.log(side, "ℹ️ Abrisskanten-Check übersprungen: Erstes Loch auf der Scheibe (noch keine alten Risse vorhanden).")

                    # 4. DAS GROSSE BATTLE ROYALE AUSWERTEN
                    valid_candidates = [c for c in kandidaten if c['valid']]
                    
                    if not valid_candidates:
                        # Fallback (Passiert nur, falls Base aus irgendeinem Grund rausfliegt)
                        valid_candidates = kandidaten

                    # =========================================================================
                    # ---> NEU: Die erweiterte ELA Tie-Breaker Logik (inkl. Dynamischem Anker) <---
                    # =========================================================================
                    def tie_breaker_key(cand):
                        rounded_score = round(cand['score'], 1)
                        name = cand['name']
                        if name == "Schwerpunkt (CoG)": prio = 1
                        elif "Hough" in name: prio = 2
                        elif name == "MinCircle (MEC)": prio = 3
                        else: prio = 4 
                        # Wir nutzen den dynamisch festgelegten Anker (CoG oder MEC)
                        dist_to_anker = np.hypot(cand['cx'] - anker_x, cand['cy'] - anker_y)
                        cand['_prio'] = prio
                        cand['_dist'] = dist_to_anker
                        return (rounded_score, -prio, -dist_to_anker)
                    # Den Sieger ermitteln
                    winner = max(valid_candidates, key=tie_breaker_key)
                    # ---> NEU: Detaillierte Liste bei Battle-Royale Gleichständen <---
                    highest_score = round(winner['score'], 1)
                    tied_candidates = [c for c in valid_candidates if round(c['score'], 1) == highest_score]
                    if len(tied_candidates) > 1:
                        # ---> DER FIX: Wieder "GLEICHSTAND" nennen! <---
                        self.log(side, f"⚖️ GLEICHSTAND (Battle-Royale): {len(tied_candidates)} Kandidaten mit Top-Score ({highest_score:.1f}).")
                        # Für eine schöne Liste absteigend nach der Tie-Breaker-Stärke sortieren
                        sorted_ties = sorted(tied_candidates, key=tie_breaker_key, reverse=True)
                        for i, cand in enumerate(sorted_ties):
                            is_winner = (cand['name'] == winner['name'])
                            marker = "👑 SIEGER" if is_winner else "❌"
                            # Namen für die Log-Ausgabe auf eine feste Breite (z.B. 25 Zeichen) auffüllen
                            name_padded = f"{cand['name']:<28}"
                            self.log(side, f"      -> {name_padded} | Prio: {cand['_prio']} | Distanz: {cand['_dist']:5.2f}px | X:{cand['cx']:.2f} Y:{cand['cy']:.2f} {marker}")
                        # Kurze Info, falls die Distanz (und nicht die Prio-Klasse) entscheiden musste
                        same_prio_contenders = [c for c in tied_candidates if c['_prio'] == winner['_prio']]
                        if len(same_prio_contenders) > 1:
                            self.log(side, f"   📏 Härtefall! Prio-Klasse {winner['_prio']} war mehrfach vertreten. Distanz-Jury entschied!")

                    # ---> NEU: Formatierter Sieger (Ziel UND Score perfekt im Raster!) <---
                    win_prefix = "BATTLE ROYALE SIEGER:"
                    # 1. Wir füllen den Prefix mit Bindestrichen bis exakt Zeichen 87 auf
                    win_prefix_padded = f"{win_prefix:-<87}" 
                    # 2. Das Ziel hat wie bei den Kandidaten exakt 25 Zeichen (87 + 25 = 112)
                    win_ziel = f" - Ziel X:{winner['cx']:>6.2f} Y:{winner['cy']:>6.2f} "
                    # 3. Wir hängen "-->" an, um auf exakt 115 Zeichen vor dem " Score:" zu kommen
                    win_final_prefix = f"{win_prefix_padded}{win_ziel}->"
                    # 4. Ausgabe: Exakt im Raster, der Siegername steht stolz ganz hinten!
                    self.log(side, f"{win_final_prefix} Score: {winner['score']:5.1f} | {winner['name']} 👑👑👑👑👑👑👑")
                    #self.log(side, f"{win_final_prefix} Score: {winner['score']:5.1f} | {winner['name']}")
                    
                    cx, cy = winner['cx'], winner['cy']
                    final_shot_score = winner['score']
                    winning_method = winner['name']

                    #if "Abriss" in winner['name'] and current_outer_edge is not None:
                    #    frame_abrisskanten = cv2.bitwise_or(frame_abrisskanten, current_outer_edge)
                                
                elif self.erkennungs_methode == 'B':
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        # ---> DER FIX: +0.5 für den Schwerpunkt <---
                        cx = (M["m10"] / M["m00"]) + 0.5
                        cy = (M["m01"] / M["m00"]) + 0.5
                        final_shot_score, _, _ = self.calculate_hole_score(cx, cy, current_caliber_radius, thresh_new, thresh_raw)     
                        winning_method = "Schwerpunkt (Mode B)"
                    else:
                        continue 
                else:
                    (circle_x, circle_y), _ = cv2.minEnclosingCircle(cnt)
                    # ---> DER FIX: +0.5 für den MinCircle <---
                    cx, cy = float(circle_x) + 0.5, float(circle_y) + 0.5
                    final_shot_score, _, _ = self.calculate_hole_score(cx, cy, current_caliber_radius, thresh_new, thresh_raw)
                    winning_method = "MinCircle (Mode A)"
                
                # --- FEHLALARM-FILTER: Score < 70 ---
                if final_shot_score < self.min_score_valid: 
                    self.log(side, f"🚫 Fehlalarm: Score {final_shot_score:.1f} < {self.min_score_valid} -> nicht als Treffer gewertet!")
                    update_mask_only = True
                    continue

                # =========================================================================
                # 🔬 QUICK & DIRTY: RÖNTGENBLICK FÜR DEN FINALAUSGEWÄHLTEN KANDIDATEN
                # =========================================================================
                if self.detail_export_aktiv:
                    _, _, _, export_details = self.calculate_hole_score(cx, cy, current_caliber_radius, thresh_new, thresh_raw, export_details=True)
                    
                    # ---> DEINE IDEE: Wir quetschen die Metadaten der Verlierer schlank mit rein! <---
                    if self.erkennungs_methode == 'C' and 'valid_candidates' in locals():
                        export_details['all_candidates'] = valid_candidates
                        #print(f"valid_candidates: {valid_candidates}")
                    #print(f"export_details: {export_details}")
                else:
                    export_details = None
                # =========================================================================
                # =========================================================================
                
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
                            
                            # =========================================================================
                            # ---> NEU: VAR-SMUGGLER (Verlierer-Kandidaten ins Labor retten!) <---
                            # =========================================================================
                            if self.detail_export_aktiv and export_details and existing_shot.get('score_export_details'):
                                if final_shot_score > existing_shot['score']:
                                    # Das ALTE Fragment verliert -> Rette seine Kandidaten ins neue Fragment
                                    loser_cands = existing_shot['score_export_details'].get('all_candidates', [])
                                    rescued = [dict(lc, name="👻 [Sichel-Verlierer] " + lc['name']) for lc in loser_cands]
                                    export_details['all_candidates'].extend(rescued)
                                else:
                                    # Das NEUE Fragment verliert -> Rette seine Kandidaten ins alte Fragment
                                    loser_cands = export_details.get('all_candidates', [])
                                    rescued = [dict(lc, name="[Sichel-Verlierer] " + lc['name']) for lc in loser_cands]
                                    existing_shot['score_export_details']['all_candidates'].extend(rescued)

                            # ---> Das eigentliche Sichel-Duell <---
                            if final_shot_score > existing_shot['score']:
                                msg = f"🔄 Sichel-Duell: Neues Fragment (Fläche {area:.1f}px | Score {final_shot_score:.1f}) schlägt altes Fragment ({existing_shot['score']:.1f})."
                                self.log(side, f"{msg:<115} 🔄")
                                self.log(side, "-" * 60)
                                
                                # ---> DER FIX: MEC-Radius für den neuen Duell-Sieger berechnen und anhängen! <---
                                _, new_mec_radius = cv2.minEnclosingCircle(cnt)
                                new_mec_radius += 0.5 + 0.2071 # <--- FIX !!FIXXX!!
                                
                                # Überschreibe den Verlierer mit dem neuen, besseren Kandidaten inkl. Radius!
                                new_shots_found_this_frame[i] = {
                                    'cx': cx, 'cy': cy, 'area': area, 'score': final_shot_score,
                                    'winner_method': winning_method,
                                    'mec_radius': new_mec_radius,
                                    'cal_radius': float(current_caliber_radius),
                                    # --- AUSSCHLIESSLICH FÜR VERSCHIEBUNGSKORREKTUR ---
                                    'shift_x': int(applied_shift[0]),
                                    'shift_y': int(applied_shift[1]),
                                    # --------------------------------------------------
                                    'base_pos': winner.get('base_pos', (cx, cy)),
                                    'end_pos': winner.get('end_pos', (cx, cy)),
                                    'score_export_details': export_details,
                                    'outer_edge': current_outer_edge,
                                    'frag_info': f"Frag {c_idx+1}/{len(contours)}"
                                }
                            else:
                                msg = f"⚠️ Treffer ignoriert: Fragment (Fläche {area:.1f}px | Score {final_shot_score:.1f}) verliert Sichel-Duell gegen besseres Fragment ({existing_shot['score']:.1f})!"
                                self.log(side, f"{msg:<115} ⚠️")
                                self.log(side, "-" * 60)
                            is_new = False
                            break

                if is_new:
                    _, mec_radius = cv2.minEnclosingCircle(cnt)
                    mec_radius += 0.5+0.2071 # <--- FIX !!FIXXX!!
                    new_shots_found_this_frame.append({
                        'cx': winner['cx'], 'cy': winner['cy'], 'area': area, 'score': winner['score'],
                        'winner_method': winner['name'],
                        'mec_radius': mec_radius,
                        'cal_radius': float(current_caliber_radius),
                        # --- AUSSCHLIESSLICH FÜR VERSCHIEBUNGSKORREKTUR ---
                        'shift_x': int(applied_shift[0]),
                        'shift_y': int(applied_shift[1]),
                        # --------------------------------------------------
                        'base_pos': winner['base_pos'],
                        'end_pos': winner.get('end_pos', (winner['cx'], winner['cy'])),
                        'score_export_details': export_details,
                        'outer_edge': current_outer_edge,
                        'frag_info': f"Frag {c_idx+1}/{len(contours)}"
                    })
                    # ---> NEU: Exakt ausgerichtete Bestätigungs-Zeile <---
                    area_str = f"{area:>6.1f}"
                    prefix_loch = "---> NEUES LOCH BESTÄTIGT:"
                    prefix_loch_padded = f"{prefix_loch:-<60}"
                    left_part = f"{prefix_loch_padded}| Fläche: {area_str}px "
                    padded_left = f"{left_part:-<87}"
                    ziel_right = f" - Ziel X:{winner['cx']:>6.2f} Y:{winner['cy']:>6.2f} -> Score: {final_shot_score:>5.1f} | Flächen-Ratio: {winner['cov_new']:>5.1f}% 🎯"
                    self.log(side, f"{padded_left}{ziel_right}")
                    self.log(side, "------------------------------------------------------------")
                    
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
                # --- AUSSCHLIESSLICH FÜR VERSCHIEBUNGSKORREKTUR ---
                # Merke das allererste Bild, das einen ECHTEN bestätigten Treffer enthält (0,0 Referenz für Layer-Export)
                if self.first_hit_frame.get(side) is None:
                    self.first_hit_frame[side] = current_normalized.copy()
                # --------------------------------------------------

                # Alte Schüsse als "nicht mehr neu" markieren
                for s in self.sm.shots:
                    if s['side'] == side:
                        s['is_new'] = False

                # Vor der Schleife: Config einmal auslesen (Performance)
                seite_de = "links" if side == 'left' else "rechts"
                px_x = self.config.getfloat('Kameras', f'px_pro_mm_x_{seite_de}')
                px_y = self.config.getfloat('Kameras', f'px_pro_mm_y_{seite_de}')
                avg_px_pro_mm = (px_x + px_y) / 2.0
                decimals = self.ringwertung_nachkommastellen
                
                for sd in new_shots_found_this_frame:
                    
                    # 1. Schuss komplett und sauber übergeben (Einfach & Allgemein)
                    # HINWEIS: Hier wandern 'shift_x' und 'shift_y' automatisch über 'sd' als Metadaten mit in den StateManager!
                    shot = self.sm.add_shot(side, sd['cx'], sd['cy'], cv_data=sd)
                    
                    # 2. Werte für den Log-Ausdruck berechnen (Lesbar)
                    shot_num = sum(1 for s in self.sm.shots if s['side'] == side)
                    durchmesser_mm = (shot.get('mec_radius', 0.0) * 2) / avg_px_pro_mm if avg_px_pro_mm > 0 else 0
                    
                    # Die siegreiche Methode UND das Fragment auslesen
                    base_method = shot.get('winner_method', 'Unbekannt')
                    frag_info = sd.get('frag_info', '')
                    winner_method = f"{base_method} [{frag_info}]" if frag_info else base_method
                    
                    # Perfekt formatiert & 1:1 ausgerichtet mit "NEUES LOCH"
                    ring_str = f"{shot['score']:>4.{decimals}f}"
                    raw_str = f"{shot.get('raw_score', 0.0):>6.3f}"
                    area_str = f"{shot.get('area', 0.0):>6.1f}"
                    
                    prefix_schuss = f"|||||* SCHUSS #{shot_num:>2d} *||||| --> Ringwertung: {ring_str} | {raw_str} Roh "
                    left_part = f"{prefix_schuss}| Fläche: {area_str}px "
                    padded_left = f"{left_part:-<87}"
                    
                    cv_score_str = f"{shot.get('cv_score', 0.0):>5.1f}"
                    
                    # Die Methode wird mit <36 auf eine feste Breite gezwungen
                    ziel_right = f" - Ziel X:{shot['cx']:>6.2f} Y:{shot['cy']:>6.2f} -> Score: {cv_score_str} | {winner_method:<36} | MEC-Ø: {durchmesser_mm:>5.2f}mm 💥"
                    
                    self.log(side, f"{padded_left}{ziel_right}")
                    
                self.log(side, f"🎯 {len(new_shots_found_this_frame)} neue(r) Treffer bestätigt!", True)
            
            # =========================================================================
            # ---> NEU: Aussagekräftige Log-Ausgabe für stille Masken-Updates <---
            # =========================================================================
            elif update_mask_only:
                pixels_added = cv2.countNonZero(thresh_new)
                self.log(side, f"🛡️ Masken-Update (Ohne Treffer): {len(contours)} Kontur(en) / {pixels_added} Pixel in die Basismaske integriert.")
            
            # Maske für BEIDE Fälle (Treffer & Discard-Risse) updaten
            if self.randaufschlag_cumulative > 0:
                k_size = (self.randaufschlag_cumulative * 2) + 1
                kernel_sticker = np.ones((k_size, k_size), np.uint8)
                sticker_to_add = cv2.dilate(thresh_new, kernel_sticker, iterations=1)
                state.cumulative_mask = cv2.bitwise_or(thresh_raw, sticker_to_add)
            else:
                state.cumulative_mask = thresh_raw
                
            # Maske für BEIDE Fälle (Treffer & Discard-Risse) updaten
            #state.cumulative_mask = cv2.bitwise_or(state.cumulative_mask, sticker_to_add)
            
            self.save_debug_image(f"diff_gesamt_{side}", state.cumulative_mask)
            self.save_debug_image(f"diff_letzter_treffer_{side}", thresh_new)
            self.save_debug_image(f"letzte_aufnahme_{side}", frame)
            
            # ---> NEU: Hier ganz am Schluss, NACH allen Sichel-Duellen, malen wir die wahren Sieger!
            frame_abrisskanten = np.zeros_like(thresh_raw)
            for sd in new_shots_found_this_frame:
                if "Abriss" in sd['winner_method'] and sd.get('outer_edge') is not None:
                    frame_abrisskanten = cv2.bitwise_or(frame_abrisskanten, sd['outer_edge'])
                    
            self.save_debug_image(f"letzte_abrisskante_{side}", frame_abrisskanten)
            # ---> NEU: Das normalisierte Bild für Paint-Analysen speichern! <--- AUSKOMMENTIERT ABER BITTE NICHT LÖSCHEN!
            #self.save_debug_image(f"letzte_aufnahme_normalized_{side}", current_normalized)
            
            # =========================================================================
            # ---> NEU: Bilder intelligent abspeichern (Immer aktiv für das Labor) <---
            # =========================================================================
            ts = datetime.now().strftime('%H%M%S_%f')[:-3]
            
            if new_shots_found_this_frame:
                shot_idx = sum(1 for s in self.sm.shots if s['side'] == side) 
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_diff", thresh_new)
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_orig", frame)
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_diff_gesamt", state.cumulative_mask)
                
            elif update_mask_only:
                shot_idx = sum(1 for s in self.sm.shots if s['side'] == side)
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_Geist_diff", thresh_new)
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_Geist_orig", frame)
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_Geist_diff_gesamt", state.cumulative_mask)

            return True if new_shots_found_this_frame else False
            
        else:
            if self.ausloeser_durch_erschuetterung:
                self.log(side, "Keine validen neuen Treffer im Bild gefunden.")
            # =========================================================================
            # ---> NEU: Geisterbilder nur speichern, wenn sich WIRKLICH etwas 
            # Relevantes verändert hat (> 0.005 % entspricht ca. 25 Pixeln)
            # =========================================================================
            if change_percent > 0.005:
                ts = datetime.now().strftime('%H%M%S_%f')[:-3]
                shot_idx = sum(1 for s in self.sm.shots if s['side'] == side)
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_Geist_diff", thresh_new)
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_Geist_orig", frame)
                self.save_debug_image(f"Schuss_{shot_idx:02d}_{side}_{ts}_Geist_diff_gesamt", state.cumulative_mask)
            return False

    def check_background_and_evaluate(self, frame, state):
        current_ref = self.ref_left if state.side == 'left' else self.ref_right
        bg_visible, bg_percent = state.is_background_visible(frame)
        diff = bg_percent - state.min_area 
        
        # ---> NEU: Immer transparent loggen, was die Hintergrund-Analyse sieht! <---
        status_str = "WAND (Scheibe weg)" if bg_visible else "SCHEIBE (Aktiv)"
        self.log(state.side, f"🔎 Hintergrund-Check: {bg_percent:.1f}% Wandfarbe -> {status_str} (Limit: {state.min_area}%)")
        
        if bg_visible:
            if state.target_present:
                self.log(state.side, "⚠️ Scheibe außer Sicht -> Warte auf Zielscheibe...", True)
                state.target_present = False
            else:
                self.log(state.side, "⏸️ Auswertung blockiert: Scheibe laut Farbanalyse immer noch nicht zurück.")
                
            return False  # <--- WICHTIG: Signal weitergeben
        else:
            if not state.target_present:
                self.log(state.side, "✅ Scheibe wieder im Bild erkannt! Starte Auswertung...", True)
                state.target_present = True
                
                if current_ref is None:
                    self.set_reference_image(frame, state.side)
                    return False  # <--- WICHTIG: Signal weitergeben
                else:
                    return self.detect_new_shot(frame, state.side)
            else:
                return self.detect_new_shot(frame, state.side)