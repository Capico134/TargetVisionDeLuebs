import glob
import os
import cv2
import configparser
import subprocess
import zipfile
import json  
from datetime import datetime

class DateiManager:
    def __init__(self):
        self.CONFIG_FILE = 'config.ini'
        self.DEBUG_FOLDER = 'debug_bilder'
        self.LOG_FILE = 'treffer_log.txt'
        self.ZIP_FOLDER = 'debug_pakete'
        
        self._init_system()

    def _init_system(self):
        """Erstellt Ordner und leert das Log beim Start."""
        if not os.path.exists(self.DEBUG_FOLDER):
            os.makedirs(self.DEBUG_FOLDER)
        else:
            # ---> NEU (Punkt A): Löscht alte Debug-Bilder bei jedem Programmstart <---
            alte_dateien = glob.glob(os.path.join(self.DEBUG_FOLDER, "*"))
            for f in alte_dateien:
                try:
                    if os.path.isfile(f):
                        os.remove(f)
                except Exception:
                    pass
            
        if not os.path.exists(self.ZIP_FOLDER):
            os.makedirs(self.ZIP_FOLDER)    

        with open(self.LOG_FILE, "w", encoding="utf-8") as f:
            f.write(f"=== DIGITALE TREFFERANZEIGE LOG - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")

    def get_current_version(self):
        """Holt die Version aus Git oder gibt einen Fallback zurück."""
        try:
            raw_git = subprocess.check_output(
                ["git", "describe", "--tags", "--always", "--dirty"], 
                stderr=subprocess.DEVNULL
            ).strip().decode("utf-8")
            return raw_git.lstrip('v') 
        except Exception:
            return "1.1.0-dev"

    def write_log(self, log_msg):
        """Schreibt eine fertige Nachricht in die Textdatei."""
        with open(self.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")

    def save_debug_image(self, name, image):
        """Speichert Debug-Bilder intelligent als JPG (Fotos) oder PNG (Masken)."""
        ext = ".png" if "diff" in name.lower() else ".jpg"
        path = os.path.join(self.DEBUG_FOLDER, f"{name}{ext}")
        cv2.imwrite(path, image)

    def update_ini_value(self, target_section, target_key, new_value):
        """Aktualisiert oder fügt einen Wert in der config.ini hinzu (Ninja-Patch)."""
        if not os.path.exists(self.CONFIG_FILE):
            return

        with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        in_target_section = False
        section_found = False
        key_found = False
        insert_idx = -1

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('[') and stripped.endswith(']'):
                if stripped == f"[{target_section}]":
                    in_target_section = True
                    section_found = True
                    insert_idx = i + 1
                else:
                    if in_target_section:
                        in_target_section = False
                        insert_idx = i
            elif in_target_section and not stripped.startswith('#') and '=' in stripped:
                k, _ = line.split('=', 1)
                if k.strip() == target_key:
                    lines[i] = f"{target_key} = {new_value}\n"
                    key_found = True
                    break
                insert_idx = i + 1

        if section_found and not key_found:
            if insert_idx == -1: insert_idx = len(lines)
            lines.insert(insert_idx, f"{target_key} = {new_value}\n")
        elif not section_found:
            if lines and not lines[-1].endswith('\n'):
                lines.append('\n')
            lines.append(f"\n[{target_section}]\n{target_key} = {new_value}\n")

        with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        print(f"💾 config.ini Update: [{target_section}] {target_key} = {new_value}")


    def load_or_create_config(self):
        """Lädt die Konfiguration, erstellt sie neu oder führt Patches aus."""
        if not os.path.exists(self.CONFIG_FILE):
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                f.write("""[Zielscheibe]
# Die aktive Zielscheibe (muss exakt dem Namen in der zielscheiben.json entsprechen)
aktive_scheibe = Luftgewehr_10m             
# Schaltet die 10.9 Zehntel-Ringwertung und die Nullpunkt-Zentrierung ein (yes) oder aus (no)
ringwertung_aktiv = no
                
[Kameras]
# Aktiviert oder deaktiviert die jeweilige Kameraansicht
nutze_kamera_links = yes
nutze_kamera_rechts = yes
# Kamera-Indizes im System (0 ist meist die Standard-Webcam/OBS Virtual Cam)
cam_left_index = 0
cam_right_index = 1
px_pro_mm_x_links = 5.0
px_pro_mm_y_links = 5.0
px_pro_mm_x_rechts = 5.0
px_pro_mm_y_rechts = 5.0

[Erkennung]
# Auslöser für die Auswertung:
# yes = Auslösen erst durch Bewegungen im Kamerabild (Z.B. durch Bewegung der laufenden Scheibe, sehr ressourcenschonend)
# no = Dauerhaftes Scannen (Für statische Scheiben, Webcams, Lasertraining)
ausloeser_durch_erschuetterung = no
# Auswertungsmethode für die Form des Schusslochs:
# A = Umschließender Kreis (Standard, gut für leicht ausgefranste Löcher)
# B = Schwerpunkt (Zieht bei unsauberen Rissen oft zum Papierschnipsel hin)
# C = Smart-Hybrid (Hough-Kreisbogen + minEnclosingCircle - Empfohlen!)
erkennungs_methode = C
# Für Methode C: Ab welchem Vergrößerungs-Faktor (im Vergleich zum Normal-Kaliber) ein unsauberes Loch
# nicht mehr als "Normal" gilt und den Hough-Algorithmus auslöst. (Standard: 1.5)
hybrid_riss_faktor = 1.5
hybrid_sichel_faktor = 0.75
# Für Methode C: Begrenzungen für den Hough-Algorithmus (Faktor bezogen auf caliber_radius)
hough_min_faktor = 0.85
hough_max_faktor = 1.15
# Mindestfläche in Pixeln, die eine Farb/Helligkeitsänderung haben muss, um als Loch zu gelten.
min_hole_area = 25
# Sperr-Radius um bestehende Treffer (in Pixeln) gegen Doppelzählungen.
caliber_radius = 14
# Anzahl veränderter Pixel im Bild, ab der eine Bewegung (Vibration/Fahrt) erkannt wird.
motion_threshold = 2000
# Farb/Helligkeits-Toleranz für die Bewegungserkennung.
motion_tolerance = 40
# Empfindlichkeit für Löcher (Referenz vs. Live).
hit_tolerance = 20
# Notbremse gegen Standbild/Ruckler in Prozent.
max_image_change_percent = 5.0
# Speichert bei JEDEM erkannten Treffer die Bilder separat ab (für Entwicklungszwecke)
debug_alle_bilder_speichern = yes

[Timing]
# Bildwiederholrate/Haupttakt in Millisekunden (33 ms entspricht ca. 30 FPS).
poll_ms = 33
# Wie viele Frames am Stück absolute Ruhe herrschen muss, damit das Bild als "stabil" gilt.
stillness_frames = 10

[Hintergrund_Links]
rgb_r = 234
rgb_g = 241
rgb_b = 190
tolerance = 30
min_area_percent = 40

[Hintergrund_Rechts]
rgb_r = 220
rgb_g = 135
rgb_b = 114
tolerance = 30
min_area_percent = 40

[Crop_Links]
cut_top = 0
cut_bottom = 0
cut_left = 175
cut_right = 20

[Crop_Rechts]
cut_top = 0
cut_bottom = 0
cut_left = 175
cut_right = 20

[Anzeige]
# Skalierungsfaktor für das Hauptfenster der Anzeige.
fenster_skalierung = 1.0
# Kiosk-Modus für den Schießstand (yes/no)
vollbild = no
# Hübscht das Bild für das Auge auf (mehr Farbe/Kontrast), ohne die Erkennung zu beeinflussen
darstellung_ohne_weissabgleich = yes
""")
            print("Standard config.ini erstellt.")

        config = configparser.ConfigParser()
        config.read(self.CONFIG_FILE, encoding='utf-8')

        # --- AUTO-PATCH / MIGRATION ---
        needs_reload = False
        
        if not config.has_option('Erkennung', 'ausloeser_durch_erschuetterung'):
            print("🔧 Führe Auto-Patch aus: Füge 'ausloeser_durch_erschuetterung = yes' hinzu...")
            self.update_ini_value('Erkennung', 'ausloeser_durch_erschuetterung', 'yes')
            needs_reload = True
            
        if not config.has_option('Erkennung', 'erkennungs_methode'):
            print("🔧 Führe Auto-Patch aus: Füge 'erkennungs_methode = C' hinzu...")
            self.update_ini_value('Erkennung', 'erkennungs_methode', 'C')
            needs_reload = True
        
        if not config.has_option('Erkennung', 'hybrid_riss_faktor'):
            print("🔧 Führe Auto-Patch aus: Füge 'hybrid_riss_faktor = 1.5' hinzu...")
            self.update_ini_value('Erkennung', 'hybrid_riss_faktor', '1.5')
            needs_reload = True
        
        if not config.has_option('Erkennung', 'hybrid_sichel_faktor'):
            print("🔧 Führe Auto-Patch aus: Füge 'hybrid_sichel_faktor = 0.75' hinzu...")
            self.update_ini_value('Erkennung', 'hybrid_sichel_faktor', '0.75')
            needs_reload = True
            
        if not config.has_option('Erkennung', 'hough_min_faktor'):
            print("🔧 Führe Auto-Patch aus: Füge 'hough_min_faktor = 0.85' hinzu...")
            self.update_ini_value('Erkennung', 'hough_min_faktor', '0.85')
            needs_reload = True
            
        if not config.has_option('Erkennung', 'hough_max_faktor'):
            print("🔧 Führe Auto-Patch aus: Füge 'hough_max_faktor = 1.15' hinzu...")
            self.update_ini_value('Erkennung', 'hough_max_faktor', '1.15')
            needs_reload = True
            
        if config.has_option('Erkennung', 'min_hole_area'):
            try:
                current_area = config.getint('Erkennung', 'min_hole_area')
                if current_area < 25:
                    print(f"🔧 Führe Auto-Patch aus: Erhöhe 'min_hole_area' von {current_area} auf 25...")
                    self.update_ini_value('Erkennung', 'min_hole_area', '25')
                    needs_reload = True
            except ValueError:
                pass 

        if not config.has_section('Zielscheibe'):
            print("🔧 Führe Auto-Patch aus: Füge Sektion '[Zielscheibe]' hinzu...")
            config.add_section('Zielscheibe')
            self.update_ini_value('Zielscheibe', 'aktive_scheibe', 'Luftgewehr_10m')
            needs_reload = True
            
        if not config.has_option('Zielscheibe', 'ringwertung_aktiv'):
            print("🔧 Führe Auto-Patch aus: Füge 'ringwertung_aktiv = no' hinzu...")
            self.update_ini_value('Zielscheibe', 'ringwertung_aktiv', 'no')
            needs_reload = True
            
        for seite in ['links', 'rechts']:
            for achse in ['x', 'y']:
                key = f'px_pro_mm_{achse}_{seite}'
                if not config.has_option('Kameras', key):
                    print(f"🔧 Führe Auto-Patch aus: Füge '{key} = 5.0' hinzu...")
                    self.update_ini_value('Kameras', key, '5.0')
                    needs_reload = True    
                    
        if not config.has_option('Erkennung', 'debug_alle_bilder_speichern'):
            print("🔧 Führe Auto-Patch aus: Füge 'debug_alle_bilder_speichern = yes' hinzu...")
            self.update_ini_value('Erkennung', 'debug_alle_bilder_speichern', 'yes')
            needs_reload = True
        
        if needs_reload:
            config.read(self.CONFIG_FILE, encoding='utf-8')

        return config


    def clear_debug_images(self, side):
        """Löscht alte Debug-Bilder einer spezifischen Kamera vor einem neuen Match absolut wasserdicht."""
        try:
            ordner = self.DEBUG_FOLDER

            # ---> NEU (Punkt B & C): Robuste Suche, die "left", "links", "l" sauber von rechts trennt <---
            if side == 'all':
                suchmuster = ["*"]
            elif side == 'left':
                suchmuster = ["*left*", "*links*", "*_l.*", "*_l_*"]
            elif side == 'right':
                suchmuster = ["*right*", "*rechts*", "*_r.*", "*_r_*"]
            else:
                suchmuster = [f"*{side}*"]
                
            alte_bilder = []
            for muster in suchmuster:
                alte_bilder.extend(glob.glob(os.path.join(ordner, muster)))
            
            # set() verhindert, dass wir versuchen, dieselbe Datei doppelt zu löschen
            for bild in set(alte_bilder):
                if os.path.isfile(bild):
                    try:
                        os.remove(bild)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Fehler beim Aufräumen des Debug-Ordners: {e}")

        
    def create_debug_zip(self):
        """Generiert den Pfad für das Debug-Paket und ruft die allgemeine ZIP-Funktion auf."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filepath = os.path.join(self.ZIP_FOLDER, f"Debug_Paket_{timestamp}.zip")
        
        return self.create_zip_package(zip_filepath)

    def create_zip_package(self, zip_filepath, match_data=None):
        """
        Erstellt ein ZIP-Archiv mit Config, Log und allen aktuellen Bildern.
        Wenn match_data übergeben wird, wird zusätzlich eine match.json erzeugt.
        """
        try:
            with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                if os.path.exists(self.CONFIG_FILE):
                    zipf.write(self.CONFIG_FILE, os.path.basename(self.CONFIG_FILE))
                if os.path.exists(self.LOG_FILE):
                    zipf.write(self.LOG_FILE, os.path.basename(self.LOG_FILE))
                
                if os.path.exists(self.DEBUG_FOLDER):
                    for file in os.listdir(self.DEBUG_FOLDER):
                        file_path = os.path.join(self.DEBUG_FOLDER, file)
                        if os.path.isfile(file_path):
                            zipf.write(file_path, os.path.join(self.DEBUG_FOLDER, file))
                            
                if match_data is not None:
                    json_str = json.dumps(match_data, indent=4)
                    zipf.writestr("match.json", json_str)
                            
            print(f"📦 ZIP-Paket erfolgreich erstellt: {zip_filepath}")
            self.write_log(f"SYSTEM: 📦 Datenpaket erstellt -> {zip_filepath}")
            return True
        except Exception as e:
            print(f"❌ Fehler beim Erstellen der ZIP: {e}")
            self.write_log(f"SYSTEM: ❌ Fehler beim Erstellen der ZIP -> {e}")
            return False
            
    def load_targets(self):
        """Lädt die zielscheiben.json aus dem Projektverzeichnis."""
        target_file = "zielscheiben.json"
        
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Fehler beim Lesen der {target_file}: {e}")
            self.write_log(f"SYSTEM: ❌ Fehler beim Lesen der zielscheiben.json -> {e}")
            return {}