import glob
import os
import cv2
import configparser
import subprocess
import zipfile
import json  
from datetime import datetime
from AuditedConfig import AuditedConfigParser
import numpy as np
import io
import threading #Für die Warteschlange
import queue     #Für die Warteschlange

class DateiManager:
    # ---> ELA: Standardmäßig False, damit Zweit-Tools (Labor) nichts löschen!
    def __init__(self, clear_on_start=False):
        self.CONFIG_FILE = 'config.ini'
        self.DEBUG_FOLDER = 'debug_bilder'
        self.LOG_FILE = 'treffer_log.txt'
        self.ZIP_FOLDER = 'debug_pakete'
        
        self._init_system(clear_on_start)
        
        # ---> NEU: Multithreading für verzögerungsfreies Speichern <---
        self.image_queue = queue.Queue()
        self.save_thread = threading.Thread(target=self._image_writer_worker, daemon=True)
        self.save_thread.start()

    def _init_system(self, clear_on_start):
        """Erstellt Ordner und leert das Log beim Start."""
        if not os.path.exists(self.DEBUG_FOLDER):
            os.makedirs(self.DEBUG_FOLDER)
        elif clear_on_start:
            # ---> NEU: Fegt den Ordner nur noch, wenn es explizit gewünscht ist!
            alte_dateien = glob.glob(os.path.join(self.DEBUG_FOLDER, "*"))
            for f in alte_dateien:
                try:
                    if os.path.isfile(f):
                        os.remove(f)
                except Exception:
                    pass
            
        if not os.path.exists(self.ZIP_FOLDER):
            os.makedirs(self.ZIP_FOLDER)    

        # Das Log wird weiterhin bei JEDEM Start der DateiManager-Klasse (also auch 
        # bei TargetVision Start) sauber getrennt. Da die Log-Rotation vorher läuft,
        # geht nichts verloren.
        with open(self.LOG_FILE, "w", encoding="utf-8") as f:
            f.write(f"=== DIGITALE TREFFERANZEIGE LOG - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")

    def _image_writer_worker(self):
        """Der Koch: Läuft unsichtbar im Hintergrund und speichert Bilder ab."""
        while True:
            # Holt den ältesten Auftrag (blockiert sanft, wenn die Queue leer ist)
            task = self.image_queue.get()
            if task is None: 
                break # Das "Feierabend"-Signal
                
            filepath, image_data = task
            cv2.imwrite(filepath, image_data)
            self.image_queue.task_done()


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
        """Schreibt eine fertige Nachricht in die Textdatei UND in die Konsole."""
        # 1. Sofortige Ausgabe in der CMD-Konsole
        print(log_msg) 
        # 2. Archivierung in der Textdatei
        with open(self.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")

    #def save_debug_image(self, name, image):
    #    """Speichert Debug-Bilder intelligent als JPG (Fotos) oder PNG (Masken)."""
    #    # ---> NEU: "mask" hinzugefügt <---
    #    ext = ".png" if "diff" in name.lower() or "mask" in name.lower() else ".jpg"
    #    path = os.path.join(self.DEBUG_FOLDER, f"{name}{ext}")
    #    cv2.imwrite(path, image)

    def save_debug_image(self, name, image):
        """Wirft das Bild in die Warteschlange (als Kopie!), um TargetVision nicht zu blockieren."""
        path = os.path.join(self.DEBUG_FOLDER, f"{name}.png")
        
        # WICHTIG: image.copy(), damit der Main-Thread das Array nicht nachträglich verändert!
        self.image_queue.put((path, image.copy()))

    def flush_image_queue(self):
        """Blockiert den Main-Thread, bis die Warteschlange komplett leer gearbeitet ist."""
        if hasattr(self, 'image_queue'):
            if not self.image_queue.empty():
                self.write_log("SYSTEM: ⏳ Schreibe restliche Bilder aus dem Puffer auf Festplatte...")
            # Hier wartet Python automatisch, bis für jedes 'put' ein 'task_done' vom Koch gemeldet wurde!
            self.image_queue.join()


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
        self.write_log(f"SYSTEM: 💾 config.ini Update: [{target_section}] {target_key} = {new_value}")


    def update_ini_file_bulk(self, updates_dict):
        """
        Aktualisiert die physische config.ini aus einem Dictionary, 
        erhält alle Kommentare und erstellt ein Backup.
        Fügt fehlende Keys sicher in die zugehörige Sektion ein!
        """
        if not os.path.exists(self.CONFIG_FILE):
            return False

        # Backup erstellen
        import shutil
        backup_file = self.CONFIG_FILE.replace('.ini', '_backup.ini')
        shutil.copy2(self.CONFIG_FILE, backup_file)

        with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Zeile für Zeile durchgehen und Werte austauschen
        for section, keys in updates_dict.items():
            in_target_section = False
            section_found = False
            insert_idx = -1
            
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('[') and stripped.endswith(']'):
                    if stripped == f"[{section}]":
                        in_target_section = True
                        section_found = True
                        insert_idx = i + 1 # Fallback, falls Sektion komplett leer ist
                    else:
                        if in_target_section:
                            in_target_section = False
                            insert_idx = i # Wir haben das Ende der Sektion erreicht!
                            
                elif in_target_section and not stripped.startswith('#') and '=' in stripped:
                    k, _ = line.split('=', 1)
                    key_clean = k.strip()
                    insert_idx = i + 1 # Wir merken uns stets die Zeile NACH dem letzten Parameter
                    if key_clean in keys:
                        # Wert austauschen, aber Zeilenumbruch behalten
                        lines[i] = f"{key_clean} = {keys[key_clean]}\n"
                        # Aus dem dict entfernen, damit wir wissen, was übrig ist
                        del keys[key_clean] 
            
            # ---> DER FIX: Fehlende Keys clever einfügen <---
            if keys:
                if section_found:
                    # Sektion existiert, wir schieben die fehlenden Keys einfach unten in die Sektion rein
                    if insert_idx == -1: insert_idx = len(lines)
                    new_lines = [f"{k} = {v}\n" for k, v in keys.items()]
                    lines[insert_idx:insert_idx] = new_lines
                else:
                    # Sektion existiert GAR NICHT im Dokument -> Komplett neu am Ende anhängen
                    if lines and not lines[-1].endswith('\n'):
                        lines.append('\n')
                    lines.append(f"\n[{section}]\n")
                    for k, v in keys.items():
                        lines.append(f"{k} = {v}\n")

        with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.writelines(lines)
            
        self.write_log("SYSTEM: 💾 config.ini (Bulk-Update) erfolgreich gespeichert. Backup erstellt.")
        return True

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
cam_width_links = 1280
cam_height_links = 720
cam_width_rechts = 1280
cam_height_rechts = 720
px_pro_mm_x_links = 5.0
px_pro_mm_y_links = 5.0
px_pro_mm_x_rechts = 5.0
px_pro_mm_y_rechts = 5.0

[Erkennung]
max_aspect_ratio = 3.5
morph_kernel_size = 5
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
hybrid_riss_faktor = 1.175
hybrid_sichel_faktor = 1.05
hybrid_discard_faktor = 2.5
# Für Methode C: Begrenzungen für den Hough-Algorithmus (Faktor bezogen auf caliber_radius)
hough_min_faktor = 0.85
hough_max_faktor = 1.15
hough_param1 = 25
hough_param2 = 4
# Mindestfläche in Pixeln, die eine Farb/Helligkeitsänderung haben muss, um als Loch zu gelten.
min_hole_area = 28
# Anzahl veränderter Pixel im Bild, ab der eine Bewegung (Vibration/Fahrt) erkannt wird.
motion_threshold = 2000
# Farb/Helligkeits-Toleranz für die Bewegungserkennung.
motion_tolerance = 40
# Empfindlichkeit für Löcher (Referenz vs. Live).
hit_tolerance = 20
# Notbremse gegen Standbild/Ruckler in Prozent.
max_image_change_percent = 5.0
# 200-Punkte-Score-Ratio
gesamt_anteil_am_200score = 0.667
# Speichert bei JEDEM erkannten Treffer die Bilder separat ab (für Entwicklungszwecke)
debug_alle_bilder_speichern = yes
caliber_durchmesser = 4.5
abriss_max_edge_percent = 0.75
abriss_base_bonus = 17.0
early_exit_min_score = 145.0
early_exit_perfect_score = 196.0
min_score_valid = 70.0
clipping_factor_history = 0.15
clipping_factor_current = 0.95
# 0 = alle Treffer; alle anderen Zahlenwerte = nur die ersten x Treffer mit der größten Fläche werden gewertet
max_treffer_je_frame = 0

[Timing]
# Bildwiederholrate/Haupttakt in Millisekunden (33 ms entspricht ca. 30 FPS).
poll_ms = 33
# Wie viele Frames am Stück absolute Ruhe herrschen muss, damit das Bild als "stabil" gilt.
stillness_frames = 20

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
# fenster_skalierung = 1.0
# Kiosk-Modus für den Schießstand (yes/no)
vollbild = no
# Hübscht das Bild für das Auge auf (mehr Farbe/Kontrast), ohne die Erkennung zu beeinflussen
darstellung_ohne_weissabgleich = yes
""")
            self.write_log("SYSTEM: 🆕 Standard config.ini erstellt.")

        # ---> NEU: Initialisierung des Spions (AuditedConfigParser) <---
        config = AuditedConfigParser(log_callback=self.write_log)
        config.read(self.CONFIG_FILE, encoding='utf-8')

        # --- AUTO-PATCH / MIGRATION ---
        needs_reload = False

# ALTE BEISPIELE:
#        if not config.has_option('Erkennung', 'ausloeser_durch_erschuetterung'):
#            print("🔧 Führe Auto-Patch aus: Füge 'ausloeser_durch_erschuetterung = yes' hinzu...")
#            self.update_ini_value('Erkennung', 'ausloeser_durch_erschuetterung', 'yes')
#            needs_reload = True
#        
#        if not config.has_option('Erkennung', 'hybrid_riss_faktor'):
#            print("🔧 Führe Auto-Patch aus: Füge 'hybrid_riss_faktor = 1.175' hinzu...")
#            self.update_ini_value('Erkennung', 'hybrid_riss_faktor', '1.175')
#            needs_reload = True
#            
#        if config.has_option('Erkennung', 'min_hole_area'):
#            try:
#                current_area = config.getint('Erkennung', 'min_hole_area')
#                if current_area < 28:
#                    print(f"🔧 Führe Auto-Patch aus: Erhöhe 'min_hole_area' von {current_area} auf 28...")
#                    self.update_ini_value('Erkennung', 'min_hole_area', '28')
#                    needs_reload = True
#            except ValueError:
#                pass 
#
#        if not config.has_section('Zielscheibe'):
#            print("🔧 Führe Auto-Patch aus: Füge Sektion '[Zielscheibe]' hinzu...")
#            config.add_section('Zielscheibe')
#            self.update_ini_value('Zielscheibe', 'aktive_scheibe', 'Luftgewehr_10m')
#            needs_reload = True
#            
#        if not config.has_option('Zielscheibe', 'ringwertung_aktiv'):
#            print("🔧 Führe Auto-Patch aus: Füge 'ringwertung_aktiv = no' hinzu...")
#            self.update_ini_value('Zielscheibe', 'ringwertung_aktiv', 'no')
#            needs_reload = True
#            
#        for seite in ['links', 'rechts']:
#            for achse in ['x', 'y']:
#                key = f'px_pro_mm_{achse}_{seite}'
#                if not config.has_option('Kameras', key):
#                    print(f"🔧 Führe Auto-Patch aus: Füge '{key} = 5.0' hinzu...")
#                    self.update_ini_value('Kameras', key, '5.0')
#                    needs_reload = True    
#        
#        if config.has_option('Anzeige', 'darstellung_ohne_weissabgleich'):
#            try:
#                current_value = config.get('Anzeige', 'darstellung_ohne_weissabgleich')
#                # Wir prüfen auf 'yes', 'true' etc., falls es jemand manuell eingetragen hat
#                if current_value.strip().lower() in ['yes', 'true', '1']:
#                    print(f"🔧 Führe Auto-Patch aus: Ändere 'darstellung_ohne_weissabgleich' von '{current_value}' auf 'no'...")
#                    self.update_ini_value('Anzeige', 'darstellung_ohne_weissabgleich', 'no')
#                    needs_reload = True
#            except ValueError:
#                pass 
#        
#   
#
#        if config.has_option('Erkennung', 'caliber_radius'):
#            try:
#                current_value = config.getint('Erkennung', 'caliber_radius')
#                if current_value != 10.5:
#                    print(f"🔧 Führe Auto-Patch aus: Setze 'caliber_radius' von {current_value} auf 10.5...")
#                    self.update_ini_value('Erkennung', 'caliber_radius', '10.5')
#                    needs_reload = True
#            except ValueError:
#                pass    
#        
#        # --- AUTO-PATCH: Veraltete Parameter aufräumen ---
#        if config.has_option('Anzeige', 'fenster_skalierung'):
#            print("🔧 Führe Auto-Patch aus: Entferne obsoleten Parameter 'fenster_skalierung'...")
#            self.remove_ini_value('Anzeige', 'fenster_skalierung')
#            needs_reload = True
#
#        # --- AUTO-PATCH: Veraltete Parameter aufräumen ---
#        if config.has_option('Erkennung', 'caliber_radius'):
#            print("🔧 Führe Auto-Patch aus: Entferne obsoleten Parameter 'caliber_radius'...")
#            self.remove_ini_value('Erkennung', 'caliber_radius')
#            needs_reload = True        
#            
#            
#        if not config.has_option('Erkennung', 'caliber_durchmesser'):
#            print("🔧 Führe Auto-Patch aus: Füge 'caliber_durchmesser = 4.50' hinzu...")
#            self.update_ini_value('Erkennung', 'caliber_durchmesser', '4.50')
#            needs_reload = True            
#        
#        if not config.has_option('Kameras', 'cam_width_links'):
#            print("🔧 Führe Auto-Patch aus: Füge Kamera-Auflösungen hinzu...")
#            self.update_ini_value('Kameras', 'cam_width_links', '1280')
#            self.update_ini_value('Kameras', 'cam_height_links', '720')
#            self.update_ini_value('Kameras', 'cam_width_rechts', '1280')
#            self.update_ini_value('Kameras', 'cam_height_rechts', '720')
#            needs_reload = True
#
#        # --- AUTO-PATCH: 720p Migration für Skalierung & Kaliber ---
#        for seite in ['links', 'rechts']:
#            for achse in ['x', 'y']:
#                key = f'px_pro_mm_{achse}_{seite}'
#                if config.has_option('Kameras', key):
#                    try:
#                        current_val = config.getfloat('Kameras', key)
#                        if current_val < 6.0:  # Fängt alte 480p-Werte (z.B. 5.0) ab
#                            print(f"🔧 Führe Auto-Patch aus: Aktualisiere '{key}' von {current_val} auf 9.5 (720p-Anpassung)...")
#                            self.update_ini_value('Kameras', key, '9.5')
#                            needs_reload = True
#                    except ValueError:
#                        pass
#
        #if config.has_option('Erkennung', 'caliber_radius'):
        #    try:
        #        current_radius = config.getfloat('Erkennung', 'caliber_radius')
        #        if current_radius < 13.0:  # Fängt alte 480p-Werte (10.0 / 10.5) ab, lässt 720p-Werte in Ruhe
        #            print(f"🔧 Führe Auto-Patch aus: Aktualisiere 'caliber_radius' von {current_radius} auf 20.0 (720p-Anpassung)...")
        #            self.update_ini_value('Erkennung', 'caliber_radius', '20.0')
        #            needs_reload = True
        #    except ValueError:
        #        pass


        # --- AUTO-PATCH: Magic Numbers (v1.5.3) in die Config migrieren ---
        neue_parameter = {
            'abriss_max_edge_percent': '0.75',
            'abriss_base_bonus': '17.0',
            'early_exit_min_score': '145.0',
            'early_exit_perfect_score': '196.0',
            'min_score_valid': '70.0',
            'clipping_factor_history': '0.15',
            'clipping_factor_current': '0.95'
        }
        for key, default_val in neue_parameter.items():
            if not config.has_option('Erkennung', key):
                print(f"🔧 Führe Auto-Patch aus: Füge '{key} = {default_val}' hinzu...")
                self.update_ini_value('Erkennung', key, default_val)
                needs_reload = True

        if config.has_option('Erkennung', 'abriss_base_bonus'):
            try:
                current_value = config.getfloat('Erkennung', 'abriss_base_bonus')
                if current_value < 11.0:  
                    print(f"🔧 Führe Auto-Patch aus: Aktualisiere 'abriss_base_bonus' von {current_value} auf 17.0...")
                    self.update_ini_value('Erkennung', 'abriss_base_bonus', '17.0')
                    needs_reload = True
            except ValueError:
                pass

        if not config.has_option('Erkennung', 'max_treffer_je_frame'):
            print("🔧 Führe Auto-Patch aus: Füge 'max_treffer_je_frame = 0' hinzu...")
            self.update_ini_value('Erkennung', 'max_treffer_je_frame', '0')
            needs_reload = True


        
        if needs_reload:
            config.read(self.CONFIG_FILE, encoding='utf-8')

        return config


    def clear_debug_images(self, side, keep_startmask=False):
        """
        Löscht alte Debug-Bilder einer spezifischen Kamera.
        Wenn keep_startmask=True, werden cumulative_startmask und referenz_bilder behalten.
        """
        try:
            ordner = self.DEBUG_FOLDER

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
            
            for bild in set(alte_bilder):
                if os.path.isfile(bild):
                    basename = os.path.basename(bild)
                    
                    # ---> NEU: cumulative_orig vor dem Löschen schützen! <---
                    if keep_startmask:
                        if basename.startswith("cumulative_startmask_") or basename.startswith("cumulative_orig_") or basename.startswith("referenz_"):
                            continue # Überspringen, nicht löschen!
                            
                    try:
                        os.remove(bild)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Fehler beim Aufräumen des Debug-Ordners: {e}")


    def import_match_package(self, filepath):
        """
        Liest ein ZIP-Paket und entpackt alle relevanten Daten direkt in den RAM.
        Gibt ein Dictionary zurück: {'match_data': dict, 'config': ConfigParser, 'images': dict}
        """
        result = {
            'match_data': None,
            'config': None, # <--- ELA: Hier wohnt jetzt ein fertiges Objekt!
            'images': {}
        }
        
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                for item in zf.infolist():
                    filename = item.filename
                    
                    if filename == "match.json":
                        result['match_data'] = json.loads(zf.read(filename).decode('utf-8'))
                    elif filename == "config.ini":
                        # Den String sofort in einen fertigen Parser umwandeln
                        config_str = zf.read(filename).decode('utf-8')
                        parser = configparser.ConfigParser()
                        parser.optionxform = str # WICHTIG: Verhindert, dass alles kleingeschrieben wird!
                        parser.read_file(io.StringIO(config_str))
                        result['config'] = parser
                    elif filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                        file_bytes = np.frombuffer(zf.read(filename), np.uint8)
                        result['images'][filename] = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
                        
            self.write_log(f"SYSTEM: 📦 Paket erfolgreich in den RAM geladen: {os.path.basename(filepath)}")
            return result
        except Exception as e:
            self.write_log(f"SYSTEM: ❌ Fehler beim Importieren von {filepath}: {e}")
            return None

    def export_match_package(self, filepath, match_data=None, config_string=None, source_folder=None, source_zip=None, apply_diet_filter=False):
        """
        Erstellt ein ZIP-Paket. Zieht die Bilder entweder aus einem Ordner (TargetVision Live-Betrieb) 
        oder kopiert sie aus einem bestehenden ZIP (Offline-Labor Zeitmaschine).
        """
        try:
            #ALT:
            #with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zf_out:
            
            # Wir nutzen ZIP_STORED statt ZIP_DEFLATED. Das packt die Dateien nur in 
            # den Container ohne Kompression -> Perfekt für Git Delta-Matching von PNGs!
            with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_STORED) as zf_out:
                
                # 1. Frische JSON (überschreibt alte Versionen)
                if match_data is not None:
                    zf_out.writestr("match.json", json.dumps(match_data, indent=4))
                    
                # 2. Config.ini (Entweder aus übergebenem String ODER von der Festplatte)
                if config_string is not None:
                    zf_out.writestr("config.ini", config_string)
                elif os.path.exists(self.CONFIG_FILE):
                    zf_out.write(self.CONFIG_FILE, os.path.basename(self.CONFIG_FILE))

                # 3. Log-Datei (Von der Festplatte, falls sie nicht herausgefiltert werden soll)
                if os.path.exists(self.LOG_FILE) and not apply_diet_filter:
                    zf_out.write(self.LOG_FILE, os.path.basename(self.LOG_FILE))

                # Hilfsfunktion für den Diät-Filter
                def should_skip(fname):
                    if not apply_diet_filter: return False
                    name_lower = fname.lower()
                    if "treffer_log.txt" in name_lower: return True
                    if "_diff" in name_lower: return True
                    if "letzte_aufnahme" in name_lower: return True
                    if "verworfene" in name_lower: return True
                    return False

                # 4A. Bilder aus einem existierenden ZIP kopieren (Für das Offline-Labor)
                if source_zip and os.path.exists(source_zip):
                    with zipfile.ZipFile(source_zip, 'r') as zf_in:
                        for item in zf_in.infolist():
                            fname = item.filename
                            # Wir überspringen config und json, weil die oben schon frisch geschrieben wurden!
                            if fname in ["match.json", "config.ini"] or should_skip(fname): 
                                continue
                            zf_out.writestr(item, zf_in.read(fname))
                            
                # 4B. Bilder von der Festplatte holen (Für den TargetVision Live-Betrieb)
                elif source_folder and os.path.exists(source_folder):
                    for fname in os.listdir(source_folder):
                        if should_skip(fname): 
                            continue
                        full_path = os.path.join(source_folder, fname)
                        if os.path.isfile(full_path):
                            # ---> DER FIX: Wir zwingen die Bilder wieder in den debug_bilder Ordner! <---
                            zip_internal_path = os.path.join(self.DEBUG_FOLDER, fname)
                            zf_out.write(full_path, zip_internal_path)
                            
            self.write_log(f"SYSTEM: 📦 ELA-Paket erfolgreich exportiert -> {filepath}")
            return True
        except Exception as e:
            self.write_log(f"SYSTEM: ❌ Fehler beim Exportieren von {filepath}: {e}")
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
            
            
    def remove_ini_value(self, target_section, target_key):
        """Entfernt einen veralteten Parameter restlos aus der config.ini."""
        if not os.path.exists(self.CONFIG_FILE):
            return

        with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        new_lines = []
        in_target_section = False
        removed = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('[') and stripped.endswith(']'):
                in_target_section = (stripped == f"[{target_section}]")
                new_lines.append(line)
            elif in_target_section and not stripped.startswith('#') and '=' in stripped:
                k, _ = line.split('=', 1)
                if k.strip() == target_key:
                    removed = True
                    continue  # Zeile gnadenlos überspringen (löschen)
                new_lines.append(line)
            else:
                new_lines.append(line)

        if removed:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            self.write_log(f"SYSTEM: 🧹 config.ini aufgeräumt: [{target_section}] {target_key} wurde entfernt.")