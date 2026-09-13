import os
import zipfile

# FIX 1: Pfad sauber getrennt, um den \s Fehler zu vermeiden
ordner_pfad = os.path.join("..", "savegames", "logs")

# FIX 2: Emojis und Umlaute entfernt, damit der .txt Export nicht crasht
print("Durchsuche alle ZIP-Archive nach 'Early-Exits' (uebersprungene Deep-Analysis)...\n")

total_matches_mit_exits = 0
gesamt_schuesse = 0
gesamt_exits_norm = 0
gesamt_exits_makellos = 0

for dateiname in os.listdir(ordner_pfad):
    if dateiname.endswith(".zip"):
        zip_pfad = os.path.join(ordner_pfad, dateiname)
        
        try:
            with zipfile.ZipFile(zip_pfad, 'r') as zf:
                if "treffer_log.txt" in zf.namelist():
                    log_text = zf.read("treffer_log.txt").decode('utf-8', errors='ignore')
                    
                    match_schuesse = 0
                    match_exits_norm = 0
                    match_exits_makellos = 0
                    
                    for zeile in log_text.splitlines():
                        if "NEUES LOCH BESTÄTIGT" in zeile:
                            match_schuesse += 1
                            gesamt_schuesse += 1
                        
                        if "Überspringe Deep-Analysis!" in zeile:
                            if "Loch ist in der Norm" in zeile:
                                match_exits_norm += 1
                                gesamt_exits_norm += 1
                            elif "Form ist makellos" in zeile:
                                match_exits_makellos += 1
                                gesamt_exits_makellos += 1
                                
                    match_exits_gesamt = match_exits_norm + match_exits_makellos
                    
                    if match_exits_gesamt > 0:
                        quote = (match_exits_gesamt / match_schuesse) * 100 if match_schuesse > 0 else 0
                        print(f"Match: {dateiname}")
                        print(f"   -> {match_exits_gesamt} von {match_schuesse} Treffern uebersprungen ({quote:.1f}%)")
                        if match_exits_norm > 0: print(f"      - {match_exits_norm}x wegen 'In der Norm' (Sichel/Riss-Grenzen)")
                        if match_exits_makellos > 0: print(f"      - {match_exits_makellos}x wegen 'Form ist makellos' (Score > early_exit_perfect_score)")
                        print("-" * 50)
                        total_matches_mit_exits += 1
                        
        except Exception as e:
            print(f"Warnung: Konnte {dateiname} nicht lesen: {e}")

gesamt_exits = gesamt_exits_norm + gesamt_exits_makellos

print("\n" + "=" * 60)
print(f"Suche beendet. {total_matches_mit_exits} Matches mit uebersprungener Analyse gefunden.")

if gesamt_schuesse > 0:
    gesamt_quote = (gesamt_exits / gesamt_schuesse) * 100
    print(f"GESAMT-STATISTIK:")
    print(f"   {gesamt_exits} von {gesamt_schuesse} Treffern ({gesamt_quote:.1f}%) liefen durch den Early-Exit.")
    print(f"   Davon {gesamt_exits_norm}x Norm-Limits und {gesamt_exits_makellos}x Makellos-Limit.")
else:
    print("Keine Treffer in den Logs gefunden.")
print("=" * 60)