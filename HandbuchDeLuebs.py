import tkinter as tk
from tkinter import ttk

# =========================================================================
# DATENBANK: HIER WOHNEN ALLE TEXTE (Getrennt von der GUI-Logik!)
# =========================================================================

ERSTE_SCHRITTE_TEXT = """Willkommen bei TargetVision DeLübs! 🎯

Dieses System erkennt Schüsse auf eine Zielscheibe vollautomatisch. Damit du direkt loslegen kannst, führt dich diese Anleitung durch die wichtigsten Schritte.

1. Wo finde ich die Einstellungen?
Im Hauptfenster (Live-System) findest du oben rechts den Button "Labor & Einstellungen". Klicke darauf. Im neuen Fenster klickst du dann unten rechts auf "⚙️ Alle Erweiterten Einstellungen". Hier kannst du das komplette System konfigurieren!

2. Kameras einrichten (Index & Crop)
Als Erstes müssen die Kameras das richtige Bild liefern.
- Kamera-Index: Unter "Kameras" trägst du bei "cam_left_index" (bzw. right) die ID deiner Kamera ein. (Meistens 0, 1, 2... je nachdem, wie Windows die Kameras durchnummeriert hat). Ein Neustart des Programms ist danach erforderlich!
- Bildausschnitt (Crop): Unter "Crop_Links" bzw. "Crop_Rechts" kannst du Ränder abschneiden. Schneide das Bild so zu, dass wirklich nur die Zielscheibe und die leere Wand dahinter zu sehen sind. Kabel, Tische oder Personen verwirren das System.

3. Starre Scheibe vs. Laufende Scheibe
Damit das System weiß, WANN es auswerten soll, gibt es unter "Erkennung" den extrem wichtigen Parameter "ausloeser_durch_erschuetterung":
- Häkchen aus (Standard): Für starre Ziele, Webcams oder Lasertraining. Das System scannt dauerhaft.
- Häkchen an: Für Seilzuganlagen / Laufende Scheiben. Das System ruht, bis sich die Scheibe bewegt, und wertet erst aus, wenn sie wieder absolut stillsteht. Das spart massiv PC-Leistung!

4. Wie das System funktioniert (Referenzbild & Nullpunkt)
Wenn die Kamera ruhig steht und die leere Wand (Hintergrund) von der Zielscheibe verdeckt ist, macht das System ein "Referenzbild". 
Dabei sucht es automatisch das exakte Zentrum der Scheibe (den weißen Punkt) und merkt sich diesen als "Nullpunkt". Ab jetzt vergleicht das System jedes Kamerabild mit dieser Referenz, um neue Löcher zu finden.

5. Ringwertung kalibrieren (px_pro_mm)
Damit die Zehntel-Ringe exakt berechnet werden, musst du das System optisch kalibrieren. So geht's am einfachsten:
- Sorge dafür, dass eine LEERE (unbeschossene) Zielscheibe im Bild ist.
- Drücke im Hauptfenster auf "Reset" für die jeweilige Kamera.
- Das System zeichnet nun einen grünen Kreis ins Zentrum.
- Öffne die Erweiterten Einstellungen und suche unter [Kameras] die Werte für "px_pro_mm_x" und "_y".
- Verändere die Werte (z.B. auf 5.0) und prüfe das Live-Bild, bis der grüne Kreis EXAKT den schwarzen Spiegel der Zielscheibe umrandet. 
- Wichtig: Kameralinsen verzerren! Es ist völlig normal, dass X (Breite) und Y (Höhe) unterschiedliche Werte brauchen (z. B. 5.0 und 5.8).

6. Schüsse werden nicht richtig erkannt?
Drücke im Live-System auf "Labor & Einstellungen". Die Kamera pausiert und du kannst in der rechten Seitenleiste mit den Reglern spielen (z. B. "hit_tolerance" verringern, um empfindlicher zu werden). Klicke auf Übernehmen, und das System lernt sofort dazu.
"""

# Dieses Dictionary kann später vom Offline-Labor importiert werden!
PARAMETER_LEXIKON = {
    "px_pro_mm_x / y": "Kalibrierungsfaktor. Bestimmt, wie Pixel in Ringwerte umgerechnet werden. Optische Kontrolle: Der grüne Kreis nach einem Reset muss exakt den schwarzen Spiegel der Zielscheibe abdecken.",
    "hit_tolerance": "Empfindlichkeit: Wie stark muss sich ein Pixel verändern (Referenz vs. Live), damit es ein Loch ist. Kleinere Werte = empfindlicher (erkennt auch blasse Löcher).",
    "min_hole_area": "Mindestfläche in Pixeln. Schützt vor winzigem Rauschen und verschobenen Rändern. Erst wenn so viele Pixel verändert sind, gilt es als potenzieller Schuss.",
    "caliber_radius": "Sperr-Radius in Pixeln. Verhindert, dass ein ausgefranstes Loch doppelt gezählt wird. Legt auch die Größe der gezeichneten Kreise auf dem Bildschirm fest.",
    "ausloeser_durch_erschuetterung": "Bei 'Aktiv' wartet das System auf Bewegung (z.B. Seilzuganlage) und scannt erst, wenn das Bild wieder stillsteht. Spart massiv PC-Ressourcen. Bei statischen Scheiben (z.B. Lasertraining) deaktivieren.",
    "motion_threshold": "Wie viele Pixel müssen sich bewegen, damit eine Erschütterung (Fahrt der Scheibe) überhaupt als solche erkannt wird?",
    "hybrid_riss_faktor": "Smart-Hybrid: Ab diesem Vergrößerungsfaktor (bezogen auf den Kaliberradius) wird ein unsauberer Riss an den speziellen Hough-Filter übergeben, um das eigentliche Loch zu finden.",
    "hough_param1": "Kanten-Erkennung für unsaubere Löcher. Höhere Werte ignorieren weiche Schatten besser.",
    "hough_param2": "Kreis-Strenge. Niedrigere Werte finden leichter Kreise, produzieren aber eventuell mehr Fehlalarme.",
    "morph_kernel_size": "Filter-Größe: Schließt kleine Lücken in stark ausgefransten Rissen künstlich, bevor die eigentliche Fläche berechnet wird.",
    "gesamt_anteil_am_200score": "Gewichtung der reinen Differenzfläche im Verhältnis zum mathematischen Kreis für den unsichtbaren Debug-Score."
}

DATENSTRUKTUR_TEXT = """Ein Blick unter die Haube: Wo speichert das System was?

Obwohl du fast alles bequem über die Programmoberfläche steuern kannst, ist es gut zu wissen, wie die Datenstruktur im Hintergrund arbeitet.

📄 config.ini
Die Hauptkonfigurationsdatei im Hauptordner. Hier speichert das System alle Einstellungen (Kameras, Erkennung, Anzeige). Wenn du im Menü "Erweiterte Einstellungen" etwas änderst, wird es direkt hier hineingeschrieben. 

📂 debug_bilder/ (Der Live-Puffer)
Das Kurzzeitgedächtnis des Live-Systems. Hier speichert TargetVision das aktuelle Referenzbild, die Startmasken und die Differenzbilder des *laufenden* Matches. Speichert man ein Match oder macht einen Reset, räumt das System diesen Ordner automatisch auf.

📄 zielscheiben.json
Die Datenbank für die Ring-Durchmesser (in Millimetern). Wenn dein Schützenverein eine völlig neue, exotische Scheibe nutzt, kannst du sie hier mit einem Texteditor anlegen. Sie erscheint dann automatisch in den Dropdown-Menüs.

📂 savegames/
Hier liegen alle deine gespeicherten Erfolge:
- highscore.json: Die "Bestenliste". Sie speichert nur die reinen Text-Daten (Namen, Ringe, Datum), damit die Highscore-Tabelle blitzschnell laden kann.
- logs/ (Die Match-Archive): Für jedes gespeicherte Match wird hier ein ZIP (z.B. MATCH000042.zip) abgelegt. Dieses ZIP enthält die Zeitlinie aller Schüsse (match.json), einen Snapshot der Einstellungen und alle Kamerabilder. Das ist die Datei, die du später im Offline-Labor analysieren kannst.

📂 labor_export/ (Die Transit-Zone)
Der Maschinenraum für das "Live-Tuning". Wenn du aus dem Live-System ins Offline-Labor wechselst, packt das System alle Live-Bilder in eine "Live_Tuning_Bridge.zip" und legt sie hier ab.
Klickst du im Labor auf "Übernehmen", generiert es die "Live_Tuning_Handover.zip". Das Live-System wacht auf, schluckt diese neue Datei, aktualisiert sich und löscht die Handover-Datei danach spurlos. Zudem findest du hier automatische Vorher/Nachher-Backups, falls du dich bei den Parametern verrannt hast.

📂 testcases/
Wenn du im Offline-Labor ein Match absolut perfektionierst und als "Golden Master" (Als Test-Case exportieren) abspeicherst, landet das fertige, unabhängige ZIP-Paket in diesem Ordner.
"""


# =========================================================================
# GUI: DAS HILFE-FENSTER
# =========================================================================

class HelpWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("TargetVision DeLübs - Hilfe & Handbuch")
        self.root.geometry("750x650")
        
        # Tabs erstellen
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.tab_erste_schritte = ttk.Frame(self.notebook)
        self.tab_lexikon = ttk.Frame(self.notebook)
        self.tab_datenstruktur = ttk.Frame(self.notebook) # <--- NEU
        
        self.notebook.add(self.tab_erste_schritte, text=" 📖 Erste Schritte ")
        self.notebook.add(self.tab_lexikon, text=" ⚙️ Parameter-Lexikon ")
        self.notebook.add(self.tab_datenstruktur, text=" 📁 Dateien & Ordner ")
        
        self.build_erste_schritte()
        self.build_lexikon()
        self.build_datenstruktur()
        
    def build_erste_schritte(self):
        # ---> FIX: Frame und Scrollbar für das Textfeld <---
        frame = tk.Frame(self.tab_erste_schritte)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        scrollbar = ttk.Scrollbar(frame, orient="vertical")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        txt = tk.Text(frame, wrap=tk.WORD, font=("Arial", 11), padx=15, pady=15, bg="#f9f9f9", yscrollcommand=scrollbar.set)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=txt.yview)
        
        txt.insert(tk.END, ERSTE_SCHRITTE_TEXT)
        txt.config(state=tk.DISABLED) # Nur lesen!
        
    def build_lexikon(self):
        # Scrollbarer Bereich für das Lexikon
        canvas = tk.Canvas(self.tab_lexikon, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.tab_lexikon, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # ---> NEU: Wir nutzen ein Grid (Tabelle) für perfekte Ausrichtung! <---
        tk.Label(scrollable_frame, text="Erklärung der wichtigsten Einstellungs-Werte:", 
                 font=("Arial", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(10, 15), padx=10)
        
        # Spalte 1 (die Erklärungen) darf sich ausdehnen
        scrollable_frame.grid_columnconfigure(1, weight=1)
        
        for i, (key, description) in enumerate(PARAMETER_LEXIKON.items(), start=1):
            # Spalte 0: Der Parameter-Name
            lbl_key = tk.Label(scrollable_frame, text=key, font=("Consolas", 11, "bold"), fg="#2980b9", anchor=tk.NW)
            lbl_key.grid(row=i, column=0, sticky=tk.NW, padx=(10, 15), pady=8)
            
            # Spalte 1: Die Erklärung
            lbl_desc = tk.Label(scrollable_frame, text=description, font=("Arial", 10), justify=tk.LEFT, wraplength=450, anchor=tk.NW)
            lbl_desc.grid(row=i, column=1, sticky=tk.NW, padx=(0, 10), pady=8)

        # ---> Globales Mausrad-Scrolling (Rekursives Binding) <---
        def _on_mousewheel(event):
            if event.num == 4 or getattr(event, 'delta', 0) > 0:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5 or getattr(event, 'delta', 0) < 0:
                canvas.yview_scroll(1, "units")

        def _bind_scroll_recursive(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            widget.bind("<Button-4>", _on_mousewheel)
            widget.bind("<Button-5>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_scroll_recursive(child)
                
        _bind_scroll_recursive(self.tab_lexikon)

    def build_datenstruktur(self):
        frame = tk.Frame(self.tab_datenstruktur)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        scrollbar = ttk.Scrollbar(frame, orient="vertical")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        txt = tk.Text(frame, wrap=tk.WORD, font=("Arial", 11), padx=15, pady=15, bg="#fdfdfd", yscrollcommand=scrollbar.set)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=txt.yview)
        
        txt.insert(tk.END, DATENSTRUKTUR_TEXT)
        txt.config(state=tk.DISABLED) # Nur lesen!

if __name__ == "__main__":
    root = tk.Tk()
    app = HelpWindow(root)
    root.mainloop()