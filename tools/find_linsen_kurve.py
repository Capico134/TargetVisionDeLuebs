import os
import zipfile
import configparser
import io

ordner_pfad = os.path.join("savegames", "logs")

print("=" * 60)
print("🔍 ANALYSE: Linsen-Kurve in alten Matches")
print("=" * 60 + "\n")

total_zips = 0
zips_ohne_config = 0
matches_ohne_kurve = 0
matches_mit_kurve_2 = 0
matches_mit_kurve_andere = 0

abweichungen_details = []

for dateiname in os.listdir(ordner_pfad):
    if dateiname.endswith(".zip"):
        zip_pfad = os.path.join(ordner_pfad, dateiname)
        total_zips += 1
        
        try:
            with zipfile.ZipFile(zip_pfad, 'r') as zf:
                if "config.ini" in zf.namelist():
                    # Config direkt aus dem ZIP in den RAM lesen
                    config_str = zf.read("config.ini").decode('utf-8', errors='ignore')
                    
                    parser = configparser.ConfigParser()
                    parser.read_file(io.StringIO(config_str))
                    
                    if parser.has_section('Kameras'):
                        kurve_l = parser.get('Kameras', 'linsen_kurve_links', fallback=None)
                        kurve_r = parser.get('Kameras', 'linsen_kurve_rechts', fallback=None)
                        
                        # Fall 1: Parameter existiert überhaupt nicht (ganz alte Matches)
                        if kurve_l is None and kurve_r is None:
                            matches_ohne_kurve += 1
                            continue
                            
                        # Werte normalisieren (None zu String für den Vergleich)
                        val_l = str(kurve_l).strip() if kurve_l else "2.0"
                        val_r = str(kurve_r).strip() if kurve_r else "2.0"
                        
                        # Fall 2: Parameter existiert und ist strikt 2.0 (oder 2) auf BEIDEN aktiven Kameras
                        if val_l in ["2.0", "2", "2.00"] and val_r in ["2.0", "2", "2.00"]:
                            matches_mit_kurve_2 += 1
                        else:
                            # Fall 3: Parameter existiert, ist aber UNGLEICH 2.0
                            matches_mit_kurve_andere += 1
                            abweichungen_details.append(f"  {dateiname}: Links={val_l} | Rechts={val_r}")
                    else:
                        matches_ohne_kurve += 1
                else:
                    zips_ohne_config += 1
                    
        except Exception as e:
            print(f"⚠️ Warnung: Konnte {dateiname} nicht lesen: {e}")

print("📊 ERGEBNISSE:")
print(f"Geprüfte ZIP-Archive gesamt : {total_zips}")
if zips_ohne_config > 0:
    print(f"Archive ohne config.ini     : {zips_ohne_config}")
print("-" * 60)
print(f"Parameter fehlt komplett    : {matches_ohne_kurve} Matches (Nutzen intern Standard 2.0)")
print(f"Parameter ist exakt 2.0     : {matches_mit_kurve_2} Matches")
print(f"Parameter ist ABWEICHEND    : {matches_mit_kurve_andere} Matches")

if matches_mit_kurve_andere > 0:
    print("\n📝 DETAILS ZU ABWEICHUNGEN:")
    for detail in abweichungen_details:
        print(detail)
print("=" * 60)