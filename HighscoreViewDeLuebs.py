import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import re
import zipfile
import io
import datetime as dt
from PIL import Image, ImageTk, ImageDraw, ImageFont
import configparser  

import LoggerDeLuebs
from DetectionDeLuebs import TargetDetector
from DateiManagerDeLuebs import DateiManager
from DateiManagerDeLuebs import DateiManager

class MatchDetailWindow(tk.Toplevel):
    def __init__(self, parent, match_id, zip_path):
        super().__init__(parent)
        self.match_id = match_id
        self.geometry("1400x800")
        self.configure(bg="#2c3e50")
        
        self.zoom_factor = 1.0
        self.zip_path = zip_path
        
        self.orig_img_l = None
        self.orig_img_r = None
        self.timeline = []
        self.match_metadata = {}
        self.match_config = None
        
        self.load_data()
        
        # ---> NEU: Aufgehübschter Titel (Muss nach load_data kommen, da wir die Metadaten brauchen) <---
        self.update_window_title()
        
        self.build_gui()
        self.update_images()

    def update_window_title(self):
        """Setzt den eleganten Fenstertitel aus den Metadaten der JSON zusammen."""
        version = self.match_metadata.get("version", "???")
        titel_teile = [
            f"TargetVision Detailauswertung  -  MATCH {self.match_id:06d}",
            f"v{version}"
        ]
        
        zeit = self.match_metadata.get("timestamp", self.match_metadata.get("start_zeit", ""))
        if zeit:
            zeit_ohne_sekunden = zeit[:-3] if len(zeit) > 10 else zeit
            titel_teile.append(f"🕒 {zeit_ohne_sekunden}")
            
        spieler = self.match_metadata.get("spieler", "")
        if spieler:
            titel_teile.append(f"👤 {spieler}")
            
        self.title("  |  ".join(titel_teile))

    def load_data(self):
        try:
            with zipfile.ZipFile(self.zip_path, 'r') as zipf:
                match_data = json.loads(zipf.read("match.json").decode('utf-8'))
                self.timeline = match_data.get("timeline", [])
                self.match_metadata = match_data.get("metadata", {}) # <--- NEU: Metadaten sichern!
                
                config = configparser.ConfigParser()
                config.optionxform = str
                try:
                    config_str = zipf.read("config.ini").decode('utf-8')
                    config.read_string(config_str)
                except KeyError:
                    config.read("config.ini")
                    
                self.match_config = config # <--- NEU: Config im RAM sichern!
                
                try:
                    targets = json.loads(zipf.read("zielscheiben.json").decode('utf-8'))
                except KeyError:
                    d_dm = DateiManager()
                    targets = d_dm.load_targets()
                
                ringwertung_aktiv = config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
                aktive_scheibe = config.get('Zielscheibe', 'aktive_scheibe', fallback='Luftpistole_10m')
                
                if ringwertung_aktiv and aktive_scheibe in targets:
                    offizielles_kaliber_mm = float(targets[aktive_scheibe].get('kaliber_mm', 4.5))
                else:
                    val = config.get('Erkennung', 'caliber_durchmesser', fallback='4.5')
                    if str(val).strip().lower() == 'auto':
                        offizielles_kaliber_mm = float(targets.get(aktive_scheibe, {}).get('kaliber_mm', 4.5))
                    else:
                        try: offizielles_kaliber_mm = float(val)
                        except ValueError: offizielles_kaliber_mm = 4.5
                
                px_x_l = config.getfloat('Kameras', 'px_pro_mm_x_links', fallback=5.0)
                px_y_l = config.getfloat('Kameras', 'px_pro_mm_y_links', fallback=5.0)
                avg_px_l = (px_x_l + px_y_l) / 2.0
                self.radius_left = (offizielles_kaliber_mm / 2.0) * avg_px_l
                
                px_x_r = config.getfloat('Kameras', 'px_pro_mm_x_rechts', fallback=5.0)
                px_y_r = config.getfloat('Kameras', 'px_pro_mm_y_rechts', fallback=5.0)
                avg_px_r = (px_x_r + px_y_r) / 2.0
                self.radius_right = (offizielles_kaliber_mm / 2.0) * avg_px_r
                
                try: self.orig_img_l = Image.open(io.BytesIO(zipf.read("debug_bilder/letzte_aufnahme_left.png")))
                except KeyError:
                    try: self.orig_img_l = Image.open(io.BytesIO(zipf.read("debug_bilder/letzte_aufnahme_left.jpg")))
                    except KeyError: pass
                
                try: self.orig_img_r = Image.open(io.BytesIO(zipf.read("debug_bilder/letzte_aufnahme_right.png")))
                except KeyError:
                    try: self.orig_img_r = Image.open(io.BytesIO(zipf.read("debug_bilder/letzte_aufnahme_right.jpg")))
                    except KeyError: pass
                
        except Exception as e:
            messagebox.showerror("Fehler beim Lesen", f"Das ZIP konnte nicht gelesen werden:\n{e}")

    def build_gui(self):
        main_container = tk.Frame(self, bg="#2c3e50")
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        has_l = self.orig_img_l is not None
        has_r = self.orig_img_r is not None

        # =====================================================================
        # ---> Die dynamische Layout-Weiche für 1 vs. 2 Kameras <---
        # =====================================================================
        if has_l and has_r:
            self.paned = tk.PanedWindow(main_container, orient=tk.HORIZONTAL, sashwidth=8, sashrelief=tk.RAISED, bg="#555555")
            self.paned.pack(fill=tk.BOTH, expand=True)
            parent_l = tk.Frame(self.paned, bg="#2c3e50")
            parent_r = tk.Frame(self.paned, bg="#2c3e50")
            self.paned.add(parent_l, stretch="always")
            self.paned.add(parent_r, stretch="always")
        elif has_l:
            parent_l = tk.Frame(main_container, bg="#2c3e50")
            parent_l.pack(fill=tk.BOTH, expand=True)
            parent_r = None
        elif has_r:
            parent_r = tk.Frame(main_container, bg="#2c3e50")
            parent_r.pack(fill=tk.BOTH, expand=True)
            parent_l = None
        else:
            tk.Label(main_container, text="Keine Bilder im ZIP gefunden.", font=('Arial', 14), fg="white", bg="#2c3e50").pack(pady=50)
            return

        # =====================================================================
        # ---> Schablonen-Funktion für das Bauen einer Seite <---
        # =====================================================================
        def build_side(parent, title_text):
            if not parent: return None, None, None, None

            # Rechts das schlanke Info-Panel (Wird zuerst gepackt, damit es an der Seite klebt)
            side_panel = tk.Frame(parent, bg="#34495e", width=200) 
            side_panel.pack(side=tk.RIGHT, fill=tk.Y)
            side_panel.pack_propagate(False)

            # Links der Hauptbereich für Bild (oben) UND Serien (unten)
            main_left_area = tk.Frame(parent, bg="#2c3e50")
            main_left_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

            # Container für die Serien unten im Bild-Bereich
            series_container = tk.Frame(main_left_area, bg="#1a252f")
            series_container.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))

            # Links das Canvas (Nimmt den restlichen Platz oben ein)
            canvas = tk.Canvas(main_left_area, bg="#1a252f", highlightthickness=0, cursor="fleur")
            canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            self.setup_canvas_bindings(canvas)

            # --- Das rechte Panel (Tabellen) befüllen ---
            tk.Label(side_panel, text=title_text, font=('Arial', 14, 'bold'), bg="#34495e", fg="white").pack(pady=(5,0))

            tree_frame = tk.Frame(side_panel)
            tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

            scrollbar = ttk.Scrollbar(tree_frame, orient="vertical")
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            tree = ttk.Treeview(tree_frame, columns=("Nr", "Ringe"), show="headings", yscrollcommand=scrollbar.set)
            scrollbar.config(command=tree.yview)

            tree.heading("Nr", text="#")
            tree.heading("Ringe", text="Ringe")
            tree.column("Nr", width=50, anchor="center")
            tree.column("Ringe", width=100, anchor="center")
            tree.tag_configure("high_score", foreground="#00aa00")
            tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            lbl_sum = tk.Label(side_panel, text="Gesamt: 0.0", font=('Arial', 14, 'bold'), bg="#34495e", fg="#00ff00")
            lbl_sum.pack(pady=(5, 5))

            return canvas, tree, lbl_sum, series_container

        self.canvas_l, self.tree_l, self.lbl_sum_l, self.series_cont_l = build_side(parent_l, "Treffer Links")
        self.canvas_r, self.tree_r, self.lbl_sum_r, self.series_cont_r = build_side(parent_r, "Treffer Rechts")

        if getattr(self, 'tree_l', None): self.tree_l.bind("<<TreeviewSelect>>", lambda e: self.on_tree_select(e, 'l'))
        if getattr(self, 'tree_r', None): self.tree_r.bind("<<TreeviewSelect>>", lambda e: self.on_tree_select(e, 'r'))

        tk.Label(self, text="Mausrad: Zoomen | Klick+Ziehen: Pannen", font=('Arial', 10), bg="#2c3e50", fg="#bdc3c7").pack(side=tk.BOTTOM, pady=5)

        self.populate_data()

    def populate_data(self):
        total_l, total_r = 0.0, 0.0
        idx_l, idx_r = 1, 1
        hits_l, hits_r = [], []

        for i, hit in enumerate(self.timeline):
            score = hit.get('score', 0.0)
            tag = ("high_score",) if score >= 10.0 else ()

            if hit['s'] == 'l' and getattr(self, 'tree_l', None):
                self.tree_l.insert("", "end", iid=str(i), values=(idx_l, f"{score:.1f}"), tags=tag)
                total_l += score
                idx_l += 1
                hits_l.append(score)
            elif hit['s'] == 'r' and getattr(self, 'tree_r', None):
                self.tree_r.insert("", "end", iid=str(i), values=(idx_r, f"{score:.1f}"), tags=tag)
                total_r += score
                idx_r += 1
                hits_r.append(score)

        if getattr(self, 'lbl_sum_l', None): self.lbl_sum_l.config(text=f"Gesamt: {total_l:.1f}")
        if getattr(self, 'lbl_sum_r', None): self.lbl_sum_r.config(text=f"Gesamt: {total_r:.1f}")

        # =====================================================================
        # ---> Serien-Auswertung einbinden <---
        # =====================================================================
        ringwertung_aktiv = self.match_config.getboolean('Zielscheibe', 'ringwertung_aktiv', fallback=False)
        serien_grp = self.match_config.getint('Anzeige', 'serien_gruppierung', fallback=0)

        if ringwertung_aktiv and serien_grp > 0:
            if getattr(self, 'series_cont_l', None) and hits_l:
                self.build_series(self.series_cont_l, hits_l, serien_grp)
            if getattr(self, 'series_cont_r', None) and hits_r:
                self.build_series(self.series_cont_r, hits_r, serien_grp)

    def build_series(self, series_container, hits, serien_grp):
        """Erzeugt ein flaches, einzeiliges Textfeld für die Serien unter dem Bild."""
        # Padding für eine schöne Optik setzen
        series_container.config(padx=10, pady=5)

        tk.Label(series_container, text="Serien:", font=('Arial', 12, 'bold'), bg="#1a252f", fg="white").pack(side=tk.LEFT, padx=(0, 10))

        txt_frame = tk.Frame(series_container, bg="#1a252f")
        txt_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        #scrollbar = ttk.Scrollbar(txt_frame, orient="horizontal")
        #scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        # ---> NEU: Einzeiliges Textfeld (height=1), wrap="none" für horizontale Scrollbar <---
        text_series = tk.Text(txt_frame, height=1, wrap="none", bg="#1e1e1e", fg="#00ff00", 
                              font=("Consolas", 12, "bold"), bd=0, highlightthickness=0, pady=4, padx=5)
#                              xscrollcommand=scrollbar.set, 
        text_series.pack(side=tk.TOP, fill=tk.X, expand=True)
        #scrollbar.config(command=text_series.xview)

        lines = []
        for i in range(0, len(hits), serien_grp):
            serie_hits = hits[i:i+serien_grp]
            serie_sum = sum(serie_hits)
            lines.append(f"{i+1:02d}-{i+len(serie_hits):02d}: {serie_sum:.1f}")

        # Horizontal mit Pipe-Symbolen aneinanderreihen
        text_series.insert(tk.END, "   |   ".join(lines))
        text_series.config(state=tk.DISABLED)

    def setup_canvas_bindings(self, canvas):
        canvas.bind("<MouseWheel>", self.on_zoom)      
        canvas.bind("<Button-4>", self.on_zoom)        
        canvas.bind("<Button-5>", self.on_zoom)        
        canvas.bind("<ButtonPress-1>", self.on_pan_start)
        canvas.bind("<B1-Motion>", self.on_pan_move)

    def on_pan_start(self, event):
        event.widget.scan_mark(event.x, event.y)

    def on_pan_move(self, event):
        event.widget.scan_dragto(event.x, event.y, gain=1)

    def on_zoom(self, event):
        if event.num == 4 or getattr(event, 'delta', 0) > 0:
            self.zoom_factor *= 1.15
        elif event.num == 5 or getattr(event, 'delta', 0) < 0:
            self.zoom_factor /= 1.15
            
        self.zoom_factor = max(0.5, min(self.zoom_factor, 5.0))
        self.update_images()

    def update_images(self):
        try:
            # Ein leicht fetterer Font liest sich im Kreis besser
            font = ImageFont.truetype("arialbd.ttf", int(14 * (self.zoom_factor * 0.7)))
        except IOError:
            try: font = ImageFont.truetype("arial.ttf", int(14 * (self.zoom_factor * 0.7)))
            except: font = ImageFont.load_default()

        if getattr(self, 'orig_img_l', None) and getattr(self, 'canvas_l', None):
            new_w = int(self.orig_img_l.width * self.zoom_factor)
            new_h = int(self.orig_img_l.height * self.zoom_factor)
            img_l = self.orig_img_l.resize((new_w, new_h), Image.LANCZOS)
            draw_l = ImageDraw.Draw(img_l)
            self.draw_hits(draw_l, 'l', font)
            
            self.photo_l = ImageTk.PhotoImage(img_l)
            self.canvas_l.delete("all")
            self.canvas_l.create_image(0, 0, anchor="nw", image=self.photo_l)
            self.canvas_l.config(scrollregion=self.canvas_l.bbox("all"))
            
        if getattr(self, 'orig_img_r', None) and getattr(self, 'canvas_r', None):
            new_w = int(self.orig_img_r.width * self.zoom_factor)
            new_h = int(self.orig_img_r.height * self.zoom_factor)
            img_r = self.orig_img_r.resize((new_w, new_h), Image.LANCZOS)
            draw_r = ImageDraw.Draw(img_r)
            self.draw_hits(draw_r, 'r', font)
            
            self.photo_r = ImageTk.PhotoImage(img_r)
            self.canvas_r.delete("all")
            self.canvas_r.create_image(0, 0, anchor="nw", image=self.photo_r)
            self.canvas_r.config(scrollregion=self.canvas_r.bbox("all"))
            
        self.on_tree_select(None, None)

    def draw_hits(self, draw, side, font):
        idx = 1
        # Wählt vollautomatisch den linsenkorrigierten Radius für links ('l') oder rechts ('r')
        base_r = self.radius_left if side == 'l' else self.radius_right
        
        for hit in self.timeline:
            if hit['s'] == side:
                # ---> DER FIX: Korrektes Runden vor der Integer-Wandlung für Subpixel-Präzision <---
                cx = int(round(hit['x'] * self.zoom_factor))
                cy = int(round(hit['y'] * self.zoom_factor))
                score = hit.get('score', 0.0)
                
                # Auch den Radius sauber runden
                r = int(round(base_r * self.zoom_factor))
                
                draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline="red", width=4)
                
                id_str = str(idx)
                
                # ---> NEU: Zentrierte Nummern IM Kreis <---
                try:
                    bbox = font.getbbox(id_str)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                except AttributeError:
                    tw, th = draw.textsize(id_str, font=font)
                
                # Exakt mittig setzen und auch hier korrekt runden
                text_x = int(round(cx - (tw / 2.0)))
                # Leichter optischer Ausgleich
                text_y = int(round(cy - (th / 2.0) - (2.0 * self.zoom_factor))) 
                
                # Schwarzer Outline-Schatten für Kontrast auf hellen UND dunklen Löchern
                outline_color = "black"
                draw.text((text_x-1, text_y-1), id_str, fill=outline_color, font=font)
                draw.text((text_x+1, text_y-1), id_str, fill=outline_color, font=font)
                draw.text((text_x-1, text_y+1), id_str, fill=outline_color, font=font)
                draw.text((text_x+1, text_y+1), id_str, fill=outline_color, font=font)
                
                color = "#00ff00" if score >= 10.0 else "#ffffff"
                draw.text((text_x, text_y), id_str, fill=color, font=font)
                
                idx += 1

    def on_tree_select(self, event, side):
        # 1. Dummy-Aufrufe abfangen
        if side not in ('l', 'r'):
            return
            
        tree = self.tree_l if side == 'l' else self.tree_r
        if not tree: 
            return # Sicherheitscheck, falls der Baum gar nicht existiert
        
        selected = tree.selection()
        if not selected: 
            return

        # Das zusätzliche Schutzschild gegen Endlosschleifen
        if getattr(self, '_ignore_selection', False):
            return

        if getattr(self, 'orig_img_l', None) and getattr(self, 'canvas_l', None): 
            self.canvas_l.delete("highlight")
        if getattr(self, 'orig_img_r', None) and getattr(self, 'canvas_r', None): 
            self.canvas_r.delete("highlight")

        self._ignore_selection = True
        try:
            # =====================================================================
            # ---> DER FIX: Vorher prüfen, ob die ANDERE Tabelle überhaupt existiert!
            # =====================================================================
            if side == 'l' and getattr(self, 'tree_r', None) and self.tree_r.selection():
                self.tree_r.selection_remove(self.tree_r.selection())
            elif side == 'r' and getattr(self, 'tree_l', None) and self.tree_l.selection():
                self.tree_l.selection_remove(self.tree_l.selection())
        finally:
            self._ignore_selection = False

        # Timeline-Index aus der versteckten IID auslesen!
        timeline_idx = int(selected[0])
        if timeline_idx < 0 or timeline_idx >= len(self.timeline): return

        hit = self.timeline[timeline_idx]
        
        # ---> KORREKTES RUNDEN FÜR SUBPIXEL-PRÄZISION <---
        cx = int(round(hit['x'] * self.zoom_factor))
        cy = int(round(hit['y'] * self.zoom_factor))
        
        base_r = self.radius_left if hit['s'] == 'l' else self.radius_right
        r = int(round(base_r * self.zoom_factor))
        
        canvas = self.canvas_l if hit['s'] == 'l' else self.canvas_r
        if canvas:
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#00ffff", width=7, tags="highlight")

class HighscoreViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("TargetVision - Highscore")
        self.root.geometry('1400x800')
        self.root['background'] = '#2c3e50'
        
        self.file_path = os.path.join("savegames", "highscore.json")
        self.data = []
        
        self.columns = ("ID", "Datum", "Spieler", "Kameras", "Schüsse", "Ringe")
        
        self.customize_style()
        self.build_gui()
        self.load_and_display_data()

    def customize_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", font=("Arial", 16), rowheight=35, background="#ecf0f1", fieldbackground="#ecf0f1")
        style.configure("Treeview.Heading", font=("Arial", 18, "bold"), background="#34495e", foreground="white")
        style.map("Treeview", background=[('selected', '#3498db')])

    def build_gui(self):
        top_frame = tk.Frame(self.root, bg='#2c3e50')
        top_frame.pack(fill="x", padx=20, pady=20)
        
        title_label = tk.Label(top_frame, text="🏆 TargetVision Match-Historie", font=('Arial', 24, 'bold'), bg='#2c3e50', fg='white')
        title_label.pack(side="left")
        
        refresh_btn = tk.Button(top_frame, text="↻ Aktualisieren", command=self.load_and_display_data, font=('Arial', 16), bg='#3498db', fg='white', relief="flat", padx=10)
        refresh_btn.pack(side="right", padx=10)

        frame = tk.Frame(self.root)
        frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        
        scrollbar = tk.Scrollbar(frame, width=25)
        scrollbar.pack(side="right", fill="y")
        
        self.tree = ttk.Treeview(frame, columns=self.columns, show="headings", yscrollcommand=scrollbar.set, selectmode="extended")
        
        for col in self.columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_column(c, True))
            
        self.tree.column("ID", width=60, anchor="center")
        self.tree.column("Datum", width=200, anchor="center")
        self.tree.column("Spieler", width=250)
        self.tree.column("Kameras", width=150, anchor="center")
        self.tree.column("Schüsse", width=100, anchor="center")
        self.tree.column("Ringe", width=120, anchor="center") 
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.tree.yview)

        filter_frame = tk.Frame(self.root, bg='#2c3e50')
        filter_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        self.filters = {}
        for col in self.columns:
            feld_breite = 5 if col == "ID" else 15 
            entry = tk.Entry(filter_frame, font=('Arial', 16), width=feld_breite)
            entry.pack(side="left", padx=2)
            self.filters[col] = entry
            entry.bind("<Return>", lambda event: self.apply_filters())

        filter_button = tk.Button(filter_frame, text="Filter anwenden", command=self.apply_filters, font=('Arial', 14))
        filter_button.pack(side="right", padx=(10, 0))

        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<Delete>", lambda event: self.delete_selected_entries())
        # ---> NEU: Doppelklick öffnet die Bildansicht direkt! <---
        self.tree.bind("<Double-1>", self.on_double_click)
    
    def on_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.show_hit_images()
    
    def load_and_display_data(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                self.data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = []

        self.update_treeview(self.data)
        self.sort_column("ID", True)

    def sort_column(self, col, reverse):
        def convert_value(value):
            try:
                if col == "Datum":
                    return dt.datetime.strptime(value, "%d.%m.%y %H:%M:%S")
                elif col == "ID":
                    return int(value)
                elif col == "Schüsse":
                    # Splittet z.B. "10 / 5" und addiert es (15), damit korrekt nach Summe sortiert wird
                    if "/" in str(value):
                        return sum(int(v.strip()) for v in str(value).split("/"))
                    return int(value) if str(value).isdigit() else 0
                elif col == "Ringe":
                    if "/" in str(value):
                        return sum(float(v.strip()) for v in str(value).split("/"))
                    return float(value) if value != "-" else -1.0
                return value
            except ValueError:
                return value
                
        data = [(convert_value(self.tree.set(k, col)), k) for k in self.tree.get_children('')]
        data.sort(reverse=reverse, key=lambda t: t[0])
        
        for index, (_, k) in enumerate(data):
            self.tree.move(k, '', index)
            
        self.tree.heading(col, command=lambda: self.sort_column(col, not reverse))

    def update_treeview(self, data):
        for row in self.tree.get_children():
            self.tree.delete(row)
            
        for hs in data:
            match_id = hs.get('match_id', 0)
            datum = hs.get("timestamp", "-")
            spieler = hs.get("spieler", "Unbekannt")
            kameras = hs.get("kameras", "Unbekannt")
            
            # ---> NEU: Schüsse formatiert anzeigen (mit Fallback für alte Savegames)
            schuesse_str = hs.get("gesamtpunkte_anzeige")
            if not schuesse_str:
                schuesse_str = str(hs.get("gesamtpunkte", 0))
            
            # Ringe holen
            ringe_str = hs.get("gesamt_ringe_anzeige")
            if not ringe_str:
                ringe = hs.get("gesamt_ringe", 0.0) 
                ringe_str = f"{ringe:.1f}" if ringe > 0.0 else "-"
            
            self.tree.insert("", "end", values=(match_id, datum, spieler, kameras, schuesse_str, ringe_str))
    def apply_filters(self):
        self.update_treeview(self.data)
        filtered_items = []
        
        for row_id in self.tree.get_children():
            values = self.tree.item(row_id, "values")
            match = True
    
            for i, col in enumerate(self.columns):
                val = self.filters[col].get().strip()
                if not val: continue
                
                cell_value = str(values[i])
                pattern = re.compile(val, re.IGNORECASE)
                if not pattern.search(cell_value): 
                    match = False
                    break
    
            if match: filtered_items.append(row_id)
    
        for row_id in self.tree.get_children():
            if row_id not in filtered_items:
                self.tree.delete(row_id)

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            # ---> DER FIX: Nur neu markieren, wenn die Zeile nicht schon Teil einer Mehrfachauswahl ist! <---
            if item not in self.tree.selection():
                self.tree.selection_set(item)
                
            context_menu = tk.Menu(self.root, tearoff=0)
            context_menu.add_command(label="🎯 Treffer-Bilder anzeigen", command=self.show_hit_images, font=('Arial', 14))
            context_menu.add_command(label="📋 Log & Config anzeigen", command=self.show_text_log, font=('Arial', 14))
            context_menu.add_command(label="🔬 Im Labor öffnen", command=self.open_in_labor, font=('Arial', 14))
            context_menu.add_separator()
            # ---> Dieser Befehl schnappt sich nun alle markierten Zeilen! <---
            context_menu.add_command(label="🗑️ Match löschen", command=self.delete_selected_entries, font=('Arial', 14))
            context_menu.post(event.x_root, event.y_root)

    def open_in_labor(self):
        """Öffnet das selektierte Match direkt in der Zeitmaschine (Labor)."""
        selected = self.tree.selection()
        if not selected: return
        
        match_id = int(self.tree.item(selected[0], "values")[0])
        zip_path = os.path.join("savegames", "logs", f"MATCH{match_id:06d}.zip")
        
        if not os.path.exists(zip_path):
            messagebox.showerror("Fehler", f"Die Datei {zip_path} existiert nicht mehr auf der Festplatte.")
            return

        import subprocess
        # Startet das Labor völlig autark und übergibt direkt den ZIP-Pfad
        subprocess.Popen(["python", "LaborDeLuebs.py", zip_path])

    def delete_selected_entries(self):
        selected_items = self.tree.selection()
        if not selected_items: return
        
        antwort = messagebox.askyesno("Bestätigung", f"Möchtest du {len(selected_items)} Match(es) wirklich unwiderruflich löschen?")
        if not antwort: return
        
        for item in selected_items:
            values = self.tree.item(item, "values")
            match_id_to_delete = int(values[0])
            
            self.data = [entry for entry in self.data if entry.get("match_id") != match_id_to_delete]
            
            zip_path = os.path.join("savegames", "logs", f"MATCH{match_id_to_delete:06d}.zip")
            if os.path.exists(zip_path):
                try: os.remove(zip_path)
                except OSError: pass

        with open(self.file_path, "w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=4)
            
        self.apply_filters()

    def show_hit_images(self):
        #print("HIT IMAGES")
        selected = self.tree.selection()
        if not selected: return
        
        match_id = int(self.tree.item(selected[0], "values")[0])
        zip_path = os.path.join("savegames", "logs", f"MATCH{match_id:06d}.zip")
        
        if not os.path.exists(zip_path):
            messagebox.showerror("Fehler", f"Die Datei {zip_path} existiert nicht mehr auf der Festplatte.")
            return
            
        MatchDetailWindow(self.root, match_id, zip_path)

    def show_text_log(self):
        selected = self.tree.selection()
        if not selected: return
        
        match_id = int(self.tree.item(selected[0], "values")[0])
        zip_path = os.path.join("savegames", "logs", f"MATCH{match_id:06d}.zip")
        
        if not os.path.exists(zip_path):
            messagebox.showerror("Fehler", f"Die Datei {zip_path} existiert nicht mehr.")
            return

        log_window = tk.Toplevel(self.root)
        log_window.title(f"Detail-Log & Config: MATCH {match_id:06d}")
        log_window.geometry("1150x800")
        
        info_lines = []
        try:
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                # 1. Match JSON auslesen
                match_data = json.loads(zipf.read("match.json").decode('utf-8'))
                meta = match_data.get("metadata", match_data)
                
                # ---> NEU: Zentren auslesen <---
                center_l = meta.get('center_l', [0, 0])
                center_r = meta.get('center_r', [0, 0])
                
                # 2. Config laden
                config = configparser.ConfigParser()
                try:
                    config_str = zipf.read("config.ini").decode('utf-8')
                    config.read_string(config_str)
                except KeyError:
                    pass 
                
                # ---> NEU: Umrechnungsfaktoren (px -> mm) auslesen <---
                px_x_l, px_y_l = 5.0, 5.8
                px_x_r, px_y_r = 5.0, 5.8
                
                if config.has_section('Kameras'):
                    cam_sec = config['Kameras']
                    px_x_l = cam_sec.getfloat('px_pro_mm_x_links', fallback=5.0)
                    px_y_l = cam_sec.getfloat('px_pro_mm_y_links', fallback=5.8)
                    px_x_r = cam_sec.getfloat('px_pro_mm_x_rechts', fallback=5.0)
                    px_y_r = cam_sec.getfloat('px_pro_mm_y_rechts', fallback=5.8)

                # --- HEADER & ALLE METADATEN ---
                info_lines.append(f"=== DETAIL-REPORT FÜR MATCH {match_id:06d} ===")
                info_lines.append(f"Generiert von: {meta.get('programm_name', 'TargetVision')} (v{meta.get('version', 'Unbekannt')})\n")
                
                info_lines.append("METADATEN (match.json):")
                # Wir iterieren über das gesamte Dictionary und geben jeden Key-Value-Pair aus
                for key, value in meta.items():
                    # Damit es sauber aussieht, füllen wir den Key auf 25 Zeichen auf
                    info_lines.append(f"  {key:<25}: {value}")
                
                info_lines.append("-" * 85)
                info_lines.append("WICHTIGSTE ERKENNUNGS-PARAMETER (Aus Config-Snapshot):")
                
                if config.has_section('Zielscheibe'):
                    zs = config['Zielscheibe']
                    info_lines.append(f"Scheibe: {zs.get('aktive_scheibe', '?')} | Ringwertung: {zs.get('ringwertung_aktiv', '?')}")
                
                if config.has_section('Erkennung'):
                    erk = config['Erkennung']
                    
                    # ---> NEU: Smarte Anzeige für alte (px) und neue (mm) Matches <---
                    if erk.get('caliber_durchmesser'):
                        cal_str = f"Durchmesser: {erk.get('caliber_durchmesser')} mm"
                    else:
                        cal_str = f"Radius: {erk.get('caliber_radius', '?')} px"
                        
                    info_lines.extend([
                        f"Methode: {erk.get('erkennungs_methode', 'C')} | Hit-Tolerance: {erk.get('hit_tolerance', '?')} | Min-Area: {erk.get('min_hole_area', '?')} | Kaliber: {cal_str}",
                        f"Hybrid-Sicheln: < {erk.get('hybrid_sichel_faktor', '?')}x | Hybrid-Risse: > {erk.get('hybrid_riss_faktor', '?')}x | Discard: > {erk.get('hybrid_discard_faktor', '?')}x",
                        f"Hough-Min: {erk.get('hough_min_faktor', '?')}x | Hough-Max: {erk.get('hough_max_faktor', '?')}x",
                        f"Morph-Kernel: {erk.get('morph_kernel_size', '?')} | Max-Aspect-Ratio: {erk.get('max_aspect_ratio', '?')}"
                    ])
                else:
                    info_lines.append("Keine Erkennungs-Sektion gefunden.")
                
                info_lines.append("-" * 85)
                info_lines.append("")

                # --- TIMELINE AUFBEREITEN ---
                timeline = match_data.get("timeline", [])
                first_t = timeline[0].get('t', 0.0) if timeline else 0.0
                
                hits_l = [h for h in timeline if h.get('s') == 'l']
                hits_r = [h for h in timeline if h.get('s') == 'r']
                
                def build_side_table(hits, side_name):
                    if not hits: return
                    
                    # Achsen und Zentren je nach Seite zuweisen
                    if side_name == "LINKS":
                        cx, cy = center_l[0], center_l[1]
                        px_x, px_y = px_x_l, px_y_l
                    else:
                        cx, cy = center_r[0], center_r[1]
                        px_x, px_y = px_x_r, px_y_r

                    # Tabellenkopf (mit Info zur Umrechnung)
                    info_lines.append(f"TREFFER-TIMELINE: {side_name} (Zentrum X:{cx}/Y:{cy} | px/mm X:{px_x}/Y:{px_y})")
                    header = f"{'Nr':>4} | {'Zeit':>8} | {'Ringe':>6} | {'X-Pos':>7} | {'Y-Pos':>7} | {'X (mm)':>8} | {'Y (mm)':>8} | {'Fläche':>8}"
                    info_lines.append(header)
                    info_lines.append("-" * len(header))
                    
                    summe = 0.0
                    for i, hit in enumerate(hits):
                        t_rel = hit.get('t', 0.0) - first_t
                        ringe = hit.get('score', 0.0)
                        x, y = hit.get('x', 0), hit.get('y', 0)
                        area = hit.get('a', hit.get('area', 0.0))
                        summe += ringe
                        
                        # ---> NEU: Umrechnung in Millimeter <---
                        # X-Achse: Normal (Treffer - Zentrum)
                        x_mm = (x - cx) / px_x if px_x != 0 else 0.0
                        # Y-Achse: Invertiert (Zentrum - Treffer), damit Oben = positiv
                        y_mm = (cy - y) / px_y if px_y != 0 else 0.0
                        
                        info_lines.append(f"{i+1:4d} | {t_rel:7.1f}s | {ringe:6.1f} | {x:7.1f} | {y:7.1f} | {x_mm:8.2f} | {y_mm:8.2f} | {area:8.1f}")
                    
                    info_lines.append("-" * len(header))
                    info_lines.append(f"GESAMTSUMME {side_name}: {summe:.1f} Ringe")
                    info_lines.append("\n" + "-" * 85 + "\n")

                build_side_table(hits_l, "LINKS")
                build_side_table(hits_r, "RECHTS")

                # --- ROH-LOG ---
                info_lines.append("SYSTEM-LOG FÜR DIESES MATCH (treffer_log.txt):")
                try:
                    raw_log = zipf.read("treffer_log.txt").decode('utf-8')
                    info_lines.append(raw_log)
                except KeyError:
                    info_lines.append("Keine treffer_log.txt im ZIP gefunden.")
                    
        except Exception as e:
            info_lines.append(f"\n[FEHLER BEIM LESEN DES ZIP-ARCHIVS: {e}]")
            
        full_text = "\n".join(info_lines)
        
        text_widget = tk.Text(log_window, wrap="none", width=125, height=35, font=("Consolas", 12), bg="#1e1e1e", fg="#00ff00")
        text_widget.insert("1.0", full_text)
        text_widget.configure(state="disabled")
        
        x_scroll = tk.Scrollbar(log_window, orient="horizontal", command=text_widget.xview)
        y_scroll = tk.Scrollbar(log_window, orient="vertical", command=text_widget.yview)
        text_widget.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        
        text_widget.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        
        log_window.grid_rowconfigure(0, weight=1)
        log_window.grid_columnconfigure(0, weight=1)

if __name__ == "__main__":
    root = tk.Tk()
    app = HighscoreViewer(root)
    root.mainloop()