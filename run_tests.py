import os
import sys
import zipfile
import json
import cv2
import numpy as np
import configparser
import re
from datetime import datetime

# Deine echte Engine importieren
from DetectionDeLuebs import TargetDetector

# ==========================================
# MINIMALISTISCHE DUMMYS FÜR DEN TESTLAUF
# ==========================================
class DummyState:
    def __init__(self, side):
        self.side = side
        self.cumulative_mask = None

class DummyStateManager:
    def __init__(self):
        self.state_left = DummyState('left')
        self.state_right = DummyState('right')
        self.shots = []
        
    def add_shot(self, side, cx, cy, area, cv_score=0.0):
        shot = {'side': side, 'pos': (cx, cy), 'area': area, 'score': -1.0, 'is_new': True, 'cv_score': cv_score}
        self.shots.append(shot)
        return shot
        
    def set_nullpunkt(self, side, x, y): pass

class DummyDateiManager:
    # Schluckt alle Speicherbefehle
    def save_debug_image(self, name, image): pass
    def load_targets(self): return {}

def silent_logger(side, msg, show_gui=False):
    pass 

# ==========================================
# HAUPT-TEST-LOGIK
# ==========================================
def run_all_tests():
    test_dir = "testcases"
    report_file = "test_report.txt"
    
    if not os.path.exists(test_dir):
        print(f"❌ Ordner '{test_dir}' nicht gefunden. Keine Tests ausgeführt.")
        sys.exit(1)

    zip_files = [f for f in os.listdir(test_dir) if f.endswith('.zip')]
    if not zip_files:
        print(f"⚠️ Keine ZIP-Dateien im Ordner '{test_dir}' gefunden.")
        sys.exit(1)

    # ANSI Color Codes für die Konsole
    C_GREEN = '\033[92m'
    C_RED = '\033[91m'
    C_YELLOW = '\033[93m'
    C_END = '\033[0m'
    
    report_lines = []

    def log(msg):
        """Druckt in die Konsole und speichert eine saubere Version (ohne Farbcodes) für den Report."""
        print(msg)
        # Regex entfernt alle ANSI-Farbcodes für die Textdatei
        clean_msg = re.sub(r'\033\[[0-9;]*m', '', msg)
        report_lines.append(clean_msg)

    log("\n" + "="*70)
    log(f"🚀 STARTE AUTOMATISIERTE REGRESSION-TESTS ({datetime.now().strftime('%d.%m.%Y %H:%M:%S')})")
    log("="*70)

    passed_count = 0
    failed_count = 0

    for zip_file in zip_files:
        zip_path = os.path.join(test_dir, zip_file)
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                all_files = zf.namelist()
                orig_files = sorted([f for f in all_files if "_orig" in f])
                
                # 1. config.ini laden
                config_name = next((f for f in all_files if "config.ini" in f), None)
                if not config_name:
                    log(f"{C_YELLOW}⏭️ SKIPPED: {zip_file} (Keine config.ini gefunden){C_END}")
                    continue
                    
                config = configparser.ConfigParser()
                config.read_string(zf.read(config_name).decode('utf-8'))
                
                # =======================================================
                # WAS-WÄRE-WENN OVERRIDES
                # =======================================================
                GLOBAL_OVERRIDES = {
                    'Erkennung': {
                        # 'hit_tolerance': '35',
                        # 'morph_kernel_size': '8',
                    }
                }
                
                for section, keys in GLOBAL_OVERRIDES.items():
                    if not config.has_section(section):
                        config.add_section(section)
                    for key, val in keys.items():
                        config.set(section, key, val)
                # =======================================================

                # 2. Golden Master match.json laden
                match_json_name = next((f for f in all_files if "match.json" in f), None)
                if not match_json_name:
                    log(f"{C_YELLOW}⏭️ SKIPPED: {zip_file} (Keine match.json gefunden){C_END}")
                    continue
                original_match_data = json.loads(zf.read(match_json_name).decode('utf-8'))
                
                # 3. Engine aufbauen
                d_dm = DummyDateiManager()
                d_sm = DummyStateManager()
                detector = TargetDetector(config, d_dm, d_sm, silent_logger)
                
                # 4. Bilder durch die Engine jagen
                for s in ['left', 'right']:
                    ref_name = next((f for f in all_files if f"referenz_{s}" in f), None)
                    if ref_name:
                        ref_img = cv2.imdecode(np.frombuffer(zf.read(ref_name), np.uint8), cv2.IMREAD_COLOR)
                        detector.set_reference_image(ref_img, s)
                    
                    startmask_name = next((f for f in all_files if f"cumulative_startmask_{s}" in f), None)
                    if startmask_name:
                        startmask_bgr = cv2.imdecode(np.frombuffer(zf.read(startmask_name), np.uint8), cv2.IMREAD_COLOR)
                        state = d_sm.state_left if s == 'left' else d_sm.state_right
                        state.cumulative_mask = cv2.cvtColor(startmask_bgr, cv2.COLOR_BGR2GRAY)

                for orig_name in orig_files:
                    img = cv2.imdecode(np.frombuffer(zf.read(orig_name), np.uint8), cv2.IMREAD_COLOR)
                    s = 'left' if 'left' in orig_name else 'right'
                    detector.detect_new_shot(img, s)
                    
                # 5. ABWEICHUNG MESSEN
                match_passed = True
                error_messages = []
                
                cal_r = config.getint('Erkennung', 'caliber_radius', fallback=11)
                tolerance_px = 2.0 
                
                for side, side_char in [('left', 'l'), ('right', 'r')]:
                    orig_shots = [s for s in original_match_data.get("timeline", []) if s.get('s') == side_char]
                    curr_shots = [s for s in d_sm.shots if s.get('side') == side]
                    
                    if len(orig_shots) != len(curr_shots):
                        match_passed = False
                        error_messages.append(f"[{side.upper()}] Schuss-Anzahl weicht ab: Original {len(orig_shots)} vs. Neu {len(curr_shots)}")
                        continue
                        
                    for idx, (orig, curr) in enumerate(zip(orig_shots, curr_shots)):
                        ox, oy = orig['x'], orig['y']
                        cx, cy = int(curr['pos'][0]), int(curr['pos'][1])
                        dist = np.hypot(cx - ox, cy - oy)
                        
                        if dist > tolerance_px:
                            match_passed = False
                            error_messages.append(f"[{side.upper()}] Schuss {idx+1} abgewichen um {dist:.1f}px (Erlaubt: {tolerance_px}px)")
                
                # 6. ERGEBNIS DRUCKEN & LOGGEN
                if match_passed:
                    log(f"{C_GREEN}✅ PASS:{C_END} {zip_file}")
                    passed_count += 1
                else:
                    log(f"{C_RED}❌ FAIL:{C_END} {zip_file}")
                    for err in error_messages:
                        log(f"      {C_RED}-> {err}{C_END}")
                    failed_count += 1
                    
        except Exception as e:
            log(f"{C_RED}⚠️ ERROR bei {zip_file}:{C_END} {str(e)}")
            failed_count += 1

    # ZUSAMMENFASSUNG
    log("\n" + "="*70)
    log("📊 TEST ZUSAMMENFASSUNG")
    log("="*70)
    log(f"Insgesamt ausgeführt: {passed_count + failed_count}")
    log(f"{C_GREEN}Erfolgreich (PASS): {passed_count}{C_END}")
    if failed_count > 0:
        log(f"{C_RED}Fehlgeschlagen (FAIL): {failed_count}{C_END}")
    else:
        log(f"{C_GREEN}🎉 ALLE TESTS BESTANDEN! Dein Code ist bereit für die Produktion.{C_END}")
    log("="*70 + "\n")

    # REPORT IN DATEI SCHREIBEN
    try:
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(report_lines))
        print(f"\n💾 Ein detaillierter Bericht wurde in '{report_file}' gespeichert.")
    except Exception as e:
        print(f"\n⚠️ Konnte Report nicht speichern: {e}")

    # =======================================================
    # EXIT-CODE AN DAS BETRIEBSSYSTEM / GITHUB ACTIONS MELDEN
    # =======================================================
    if failed_count > 0:
        sys.exit(1)  # GitHub Actions wird ROT ❌ und Badge wechselt auf "failing"
    else:
        sys.exit(0)  # GitHub Actions wird GRÜN ✅ und Badge bleibt "passing"

if __name__ == "__main__":
    run_all_tests()