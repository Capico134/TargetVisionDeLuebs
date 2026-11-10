import os
import sys
import json
import shutil
import hashlib
import argparse
from datetime import datetime
import tkinter as tk
from tkinter import messagebox

HIGHSCORE_PATH = os.path.join("savegames", "highscore.json")
LOGS_DIR = os.path.join("savegames", "logs")


def compute_sha256(filepath):
    """Berechnet den SHA256-Hash einer Datei schnell und speicherschonend."""
    with open(filepath, "rb") as f:
        if hasattr(hashlib, "file_digest"):
            return hashlib.file_digest(f, "sha256").hexdigest()
        h = hashlib.sha256()
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
        return h.hexdigest()


def analyze_integrity(highscore_path=HIGHSCORE_PATH, logs_dir=LOGS_DIR):
    """
    Prüft die Konsistenz zwischen highscore.json und savegames/logs/ (100% Read-Only).
    Gibt ein Ergebnis-Dictionary zurück.
    """
    res = {
        "valid": [],           # ✅ Hash stimmt überein
        "missing_hash": [],    # 🔵 Hash fehlt noch in JSON (ZIP ist aber da)
        "mismatch": [],        # ❌ Hash-Konflikt (ZIP manipuliert oder korrupt)
        "missing_zip": [],     # ⚠️ In JSON gelistet, aber ZIP fehlt im Ordner
        "orphaned_zips": [],   # 👻 ZIP liegt im Ordner, steht aber nicht in JSON
        "json_error": None,
        "total_json": 0,
        "total_zips": 0
    }

    # 1. highscore.json lesen
    if not os.path.exists(highscore_path):
        res["json_error"] = f"Datei nicht gefunden: {highscore_path}"
        highscore_data = []
    else:
        try:
            with open(highscore_path, "r", encoding="utf-8") as f:
                highscore_data = json.load(f)
        except Exception as e:
            res["json_error"] = f"Fehler beim Lesen der {highscore_path}: {e}"
            return res

    res["total_json"] = len(highscore_data)

    # 2. Alle vorhandenen MATCH*.zip im Ordner erfassen
    existing_zips = {}
    if os.path.exists(logs_dir):
        for fname in sorted(os.listdir(logs_dir)):
            if fname.upper().startswith("MATCH") and fname.lower().endswith(".zip"):
                full_path = os.path.join(logs_dir, fname)
                if os.path.isfile(full_path):
                    existing_zips[fname] = full_path

    res["total_zips"] = len(existing_zips)
    referenced_zips = set()

    # 3. Jeden Eintrag der highscore.json abgleichen
    for idx, entry in enumerate(highscore_data):
        match_id = entry.get("match_id")
        if match_id is None:
            continue
        try:
            mid_int = int(match_id)
            zip_name = f"MATCH{mid_int:06d}.zip"
        except ValueError:
            continue

        referenced_zips.add(zip_name)
        zip_path = existing_zips.get(zip_name)
        recorded_hash = entry.get("zip_sha256")

        info = {
            "idx": idx,
            "match_id": mid_int,
            "zip_name": zip_name,
            "zip_path": zip_path,
            "spieler": entry.get("spieler", "Unbekannt"),
            "timestamp": entry.get("timestamp", entry.get("start_zeit", "-")),
            "ringe": entry.get("gesamt_ringe_anzeige", "-"),
            "schuesse": entry.get("gesamtpunkte_anzeige", str(entry.get("gesamtpunkte", "-"))),
            "recorded_hash": recorded_hash,
            "actual_hash": None
        }

        if not zip_path or not os.path.exists(zip_path):
            res["missing_zip"].append(info)
        else:
            try:
                actual_hash = compute_sha256(zip_path)
                info["actual_hash"] = actual_hash
            except Exception as e:
                info["actual_hash"] = f"READ_ERROR: {e}"
                res["mismatch"].append(info)
                continue

            if not recorded_hash:
                res["missing_hash"].append(info)
            elif recorded_hash.lower() == actual_hash.lower():
                res["valid"].append(info)
            else:
                res["mismatch"].append(info)

    # 4. Verwaiste ZIPs ermitteln (im Ordner vorhanden, aber nicht in highscore.json)
    for zip_name, zip_path in existing_zips.items():
        if zip_name not in referenced_zips:
            size_mb = os.path.getsize(zip_path) / (1024 * 1024)
            mtime = datetime.fromtimestamp(os.path.getmtime(zip_path)).strftime("%d.%m.%y %H:%M:%S")
            res["orphaned_zips"].append({
                "zip_name": zip_name,
                "zip_path": zip_path,
                "size_mb": size_mb,
                "mtime": mtime
            })

    return res


def backfill_missing_hashes(highscore_path=HIGHSCORE_PATH, logs_dir=LOGS_DIR):
    """
    Ergänzt NUR fehlende 'zip_sha256' in der highscore.json.
    Erstellt vorher ein Backup und speichert atomar über eine .tmp-Datei.
    Bereits vorhandene Hashes werden NIEMALS überschrieben!
    """
    if not os.path.exists(highscore_path):
        return 0, f"Datei nicht gefunden: {highscore_path}"

    try:
        with open(highscore_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return 0, f"Fehler beim Lesen der highscore.json: {e}"

    updated_count = 0
    for entry in data:
        if entry.get("zip_sha256"):
            continue  # Bereits vorhandener Hash wird niemals angefasst!

        match_id = entry.get("match_id")
        if match_id is None:
            continue
        try:
            zip_name = f"MATCH{int(match_id):06d}.zip"
        except ValueError:
            continue

        zip_path = os.path.join(logs_dir, zip_name)
        if os.path.isfile(zip_path):
            entry["zip_sha256"] = compute_sha256(zip_path)
            updated_count += 1

    if updated_count > 0:
        # 1. Sicherheits-Backup vor dem Schreiben anlegen
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = highscore_path.replace(".json", f"_backup_vor_backfill_{ts}.json")
        shutil.copy2(highscore_path, backup_path)

        # 2. Atomar über .tmp schreiben und mit os.replace austauschen
        temp_file = highscore_path + ".tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            os.replace(temp_file, highscore_path)
            return updated_count, f"{updated_count} Hash-Werte erfolgreich nachgetragen!\nBackup erstellt: {os.path.basename(backup_path)}"
        except Exception as e:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass
            return 0, f"Kritischer Fehler beim Speichern: {e}"

    return 0, "Keine fehlenden Hashes zum Nachtragen gefunden."


def format_report(res):
    """Formatiert das Analyse-Ergebnis als sauberen Monospace-Bericht."""
    lines = []
    lines.append("=" * 115)
    lines.append(f"🔍 MATCH-INTEGRITÄTS-BERICHT  (Stand: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')})")
    lines.append("=" * 115)

    if res.get("json_error"):
        lines.append(f"\n❌ KRITISCHER FEHLER: {res['json_error']}\n")
        return "\n".join(lines)

    lines.append(f"Einträge in highscore.json : {res['total_json']}")
    lines.append(f"MATCH-ZIPs in savegames/logs: {res['total_zips']}")
    lines.append("-" * 115)
    lines.append(f"  ✅ Synchron & Valide (Hash stimmt exakt)        : {len(res['valid']):>4}")
    lines.append(f"  🔵 Hash fehlt noch in JSON (Backfill möglich)   : {len(res['missing_hash']):>4}")
    lines.append(f"  ❌ HASH-KONFLIKT (ZIP verändert / korrupt!)     : {len(res['mismatch']):>4}")
    lines.append(f"  ⚠️ ZIP fehlt lokal (In JSON gelistet, Datei weg): {len(res['missing_zip']):>4}")
    lines.append(f"  👻 Verwaiste ZIPs (Im Ordner, nicht in JSON)    : {len(res['orphaned_zips']):>4}")
    lines.append("=" * 115)

    # 1. ❌ HASH-KONFLIKTE
    if res["mismatch"]:
        lines.append("\n❌ [ROT] HASH-KONFLIKTE (Lokale ZIP-Datei weicht von highscore.json ab!):")
        lines.append("-" * 115)
        for m in res["mismatch"]:
            lines.append(f"  • {m['zip_name']} | Datum: {m['timestamp']:<17} | Spieler: {m['spieler']:<22} | Ringe: {m['ringe']}")
            lines.append(f"      Soll-Hash (JSON): {m['recorded_hash']}")
            lines.append(f"      Ist-Hash  (ZIP) : {m['actual_hash']}")

    # 2. ⚠️ FEHLENDE ZIPS
    if res["missing_zip"]:
        lines.append("\n⚠️ [GELB] FEHLENDE ZIP-PAKETE (In highscore.json eingetragen, aber Datei fehlt lokal):")
        lines.append("-" * 115)
        for m in res["missing_zip"]:
            h_info = f"Hash: {m['recorded_hash'][:12]}..." if m["recorded_hash"] else "Kein Hash"
            lines.append(f"  • {m['zip_name']} | Datum: {m['timestamp']:<17} | Spieler: {m['spieler']:<22} | Ringe: {m['ringe']:<12} | ({h_info})")

    # 3. 👻 VERWAISTE ZIPS
    if res["orphaned_zips"]:
        lines.append("\n👻 [GELB] VERWAISTE ZIP-PAKETE (Liegen im Ordner, existieren aber NICHT in highscore.json):")
        lines.append("-" * 115)
        for o in res["orphaned_zips"]:
            lines.append(f"  • {o['zip_name']} | Geändert: {o['mtime']:<17} | Größe: {o['size_mb']:>6.2f} MB  (z.B. am Stand gelöscht)")

    # 4. 🔵 FEHLENDE HASHES (Altdaten)
    if res["missing_hash"]:
        lines.append("\n🔵 [BLAU] HASH FEHLT NOCH IN HIGHSCORE.JSON (ZIP ist vorhanden, Hash kann nachgetragen werden):")
        lines.append("-" * 115)
        for m in res["missing_hash"]:
            lines.append(f"  • {m['zip_name']} | Datum: {m['timestamp']:<17} | Spieler: {m['spieler']:<22} | Ringe: {m['ringe']:<12} | Berechneter SHA256: {m['actual_hash'][:16]}...")

    # 5. ✅ VALIDE MATCHES
    if res["valid"]:
        lines.append(f"\n✅ [GRÜN] SYNCHRONE & VALIDE MATCHES ({len(res['valid'])} Stück):")
        lines.append("-" * 115)
        for m in res["valid"]:
            lines.append(f"  • {m['zip_name']} | {m['timestamp']:<17} | {m['spieler']:<22} | Ringe: {m['ringe']:<12} | SHA256: {m['actual_hash'][:16]}... OK")

    lines.append("\n" + "=" * 115)
    return "\n".join(lines)


def start_ui(parent_root, app=None):
    """Öffnet das Diagnose-Fenster im Labor (analog zum Integrations-Check)."""
    win = tk.Toplevel(parent_root)
    win.title("🔍 Match-Integrität & Hash-Abgleich (highscore.json <-> ZIP-Archiv)")

    sf = parent_root.winfo_fpixels('1i') / 96.0
    w, h = int(1250 * sf), int(720 * sf)
    win.geometry(f"{w}x{h}")
    win.lift()
    win.focus_force()

    btn_frame = tk.Frame(win)
    btn_frame.pack(fill=tk.X, padx=10, pady=6)

    txt_frame = tk.Frame(win)
    txt_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

    scrollbar = tk.Scrollbar(txt_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    txt = tk.Text(txt_frame, font=("Consolas", 11), bg="#1e1e1e", fg="#00ff00",
                  padx=10, pady=10, yscrollcommand=scrollbar.set)
    txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.config(command=txt.yview)

    def copy_to_clipboard():
        full_log = txt.get("1.0", tk.END)
        parent_root.clipboard_clear()
        parent_root.clipboard_append(full_log)
        messagebox.showinfo("Kopiert", "Der Integritäts-Bericht wurde in die Zwischenablage kopiert!", parent=win)

    btn_copy = tk.Button(btn_frame, text="📋 In Zwischenablage kopieren", command=copy_to_clipboard,
                         bg="#3498db", fg="white", font=("Arial", 10, "bold"))
    btn_copy.pack(side=tk.LEFT, padx=(0, 10))

    btn_refresh = tk.Button(btn_frame, text="🔄 Neu prüfen", bg="#34495e", fg="white", font=("Arial", 10, "bold"))
    btn_refresh.pack(side=tk.LEFT, padx=(0, 10))

    btn_backfill = tk.Button(btn_frame, text="", bg="#e67e22", fg="white", font=("Arial", 10, "bold"))

    def run_check():
        txt.config(state=tk.NORMAL)
        txt.delete("1.0", tk.END)
        txt.insert(tk.END, "⏳ Berechne SHA256-Prüfsummen aller Match-ZIPs... Bitte kurz warten...\n")
        win.update()

        res = analyze_integrity()
        report = format_report(res)

        txt.delete("1.0", tk.END)
        txt.insert(tk.END, report)
        txt.config(state=tk.DISABLED)

        missing_count = len(res.get("missing_hash", []))
        if missing_count > 0:
            btn_backfill.config(
                text=f"🔧 Fehlende Hashes in highscore.json nachtragen ({missing_count} Stück)",
                command=lambda: on_backfill(missing_count)
            )
            btn_backfill.pack(side=tk.LEFT, padx=(10, 0))
        else:
            btn_backfill.pack_forget()

    def on_backfill(count):
        ask = messagebox.askyesno(
            "Fehlende Hashes nachtragen (Backfill)",
            f"Möchtest du für {count} bestehende Match-Pakete, denen noch ein Hash-Eintrag fehlt, "
            f"jetzt den SHA256-Wert in der 'highscore.json' ergänzen?\n\n"
            f"• Bereits vorhandene Hashes werden NIEMALS überschrieben.\n"
            f"• Es wird automatisch ein Backup der highscore.json angelegt.\n"
            f"• Das Speichern erfolgt absturzsicher über eine .tmp-Datei.",
            parent=win
        )
        if not ask:
            return
        updated, msg = backfill_missing_hashes()
        if updated > 0:
            messagebox.showinfo("Backfill abgeschlossen", msg, parent=win)
            if app and hasattr(app, "print_log"):
                app.print_log("SYSTEM", f"🔍 Match-Integrität: {updated} fehlende SHA256-Hashes in highscore.json ergänzt.")
            run_check()
        else:
            messagebox.showwarning("Hinweis", msg, parent=win)

    btn_refresh.config(command=run_check)
    win.after(50, run_check)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Match-Integrität & SHA256-Prüfwerkzeug für TargetVision")
    parser.add_argument("--backfill", action="store_true",
                        help="Trägt fehlende SHA256-Hashes in der highscore.json nach (mit Backup & .tmp-Schutz)")
    args = parser.parse_args()

    if args.backfill:
        count, message = backfill_missing_hashes()
        print(message)
        print()

    result = analyze_integrity()
    print(format_report(result))