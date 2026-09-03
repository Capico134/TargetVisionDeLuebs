import os
import zipfile

# Pfad zu deinen Matches
ordner_pfad = os.path.join("..\savegames", "logs")
suchbegriff = "Abrisskante AKTIV!" # Oder "TEST-ABRISSKANTE"

print(f"🔍 Durchsuche alle ZIP-Archive nach '{suchbegriff}'...\n")

treffer_count = 0

# Alle Dateien im Ordner durchgehen
for dateiname in os.listdir(ordner_pfad):
    if dateiname.endswith(".zip"):
        zip_pfad = os.path.join(ordner_pfad, dateiname)
        
        try:
            with zipfile.ZipFile(zip_pfad, 'r') as zf:
                # Prüfen ob die Log-Datei im ZIP existiert
                if "treffer_log.txt" in zf.namelist():
                    # Datei direkt im RAM lesen und decodieren
                    log_text = zf.read("treffer_log.txt").decode('utf-8', errors='ignore')
                    
                    if suchbegriff in log_text:
                        print(f"🎯 TREFFER in Match: {dateiname}")
                        treffer_count += 1
                        
                        # Optional: Die konkrete Zeile ausgeben
                        for zeile in log_text.splitlines():
                            if suchbegriff in zeile:
                                print(f"   -> {zeile.strip()}")
                        print("-" * 50)
                        
        except Exception as e:
            print(f"⚠️ Konnte {dateiname} nicht lesen: {e}")

print(f"\n✅ Suche beendet. {treffer_count} Matches mit Abrisskanten gefunden.")