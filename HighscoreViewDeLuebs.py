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

class MatchDetailWindow(tk.Toplevel):
    """Ein eigenständiges Fenster für die interaktive Detail-Ansicht (Zoom & Pan)."""
    def __init__(self, parent, match_id, zip_path):
        super().__init__(parent)
        self.title(f"TargetVision Detailauswertung - MATCH {match_id}")
        self.geometry("1400x800")
        self.configure(bg="#2c3e50")
        
        # Lese den caliber_radius aus der config.ini 
        config = configparser.ConfigParser()
        config.read("config.ini")
        self.caliber_radius = config.getint('Erkennung', 'caliber_radius', fallback=11)
        
        self.zoom_factor = 1.0
        self.zip_path = zip_path
        
        self.orig_img_l = None
        self.orig_img_r = None
        self.timeline = []
        self.photo_l = None
        self.photo_r = None
        
        self.load_data()
        self.build_gui()
        self.update_images()

    def load_data(self):
        try:
            with zipfile.ZipFile(self.zip_path, 'r') as zipf:
                match_data = json.loads(zipf.read("match.json").decode('utf-8'))
                self.timeline = match_data.get("timeline", [])
                
                config = configparser.ConfigParser()
                try:
                    config_str = zipf.read("config.ini").decode('utf-8')
                    config.read_string(config_str)
                    self.caliber_radius = config.getint('Erkennung', 'caliber_radius', fallback=11)
                except KeyError:
                    config.read("config.ini")
                    self.caliber_radius = config.getint('Erkennung', 'caliber_radius', fallback=11)
                
                try:
                    self.orig_img_l = Image.open(io.BytesIO(zipf.read("debug_bilder/letzte_aufnahme_left.jpg")))
                except KeyError: pass
                
                try:
                    self.orig_img_r = Image.open(io.BytesIO(zipf.read("debug_bilder/letzte_aufnahme_right.jpg")))
                except KeyError: pass
                
        except Exception as e:
            messagebox.showerror("Fehler beim Lesen", f"Das ZIP konnte nicht gelesen werden:\n{e}")

    def build_gui(self):
        self.list_frame = tk.Frame(self, bg="#34495e", width=350)
        self.list_frame.pack(side="right", fill="y", padx=10, pady=10)
        self.list_frame.pack_propagate(False) 
        
        tk.Label(self.list_frame, text="Treffer-Liste", font=('Arial', 16, 'bold'), bg="#34495e", fg="white").pack(pady=10)
        
        cols = ("Nr", "Cam", "Ringe")
        self.tree = ttk.Treeview(self.list_frame, columns=cols, show="headings", height=25)
        self.tree.heading("Nr", text="#")
        self.tree.heading("Cam", text="Cam")
        self.tree.heading("Ringe", text="Ringe")
        
        self.tree.column("Nr", width=60, anchor="center")
        self.tree.column("Cam", width=80, anchor="center")
        self.tree.column("Ringe", width=120, anchor="center")
        
        self.tree.tag_configure("high_score", foreground="#00aa00") 
        self.tree.pack(fill="both", expand=True)
        
        # ---> NEU: Klick-Event für die Tabelle binden <---
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        
        total = 0.0
        for i, hit in enumerate(self.timeline):
            cam = "L" if hit['s'] == 'l' else "R"
            score = hit.get('score', 0.0)
            total += score
            tag = ("high_score",) if score >= 10.0 else ()
            self.tree.insert("", "end", values=(i+1, cam, f"{score:.1f}"), tags=tag)
            
        tk.Label(self.list_frame, text=f"Gesamt: {total:.1f}", font=('Arial', 18, 'bold'), bg="#34495e", fg="#00ff00").pack(pady=10)
        tk.Label(self.list_frame, text="Mausrad: Zoomen\nMausklick+Ziehen: Pannen\nZeile klicken: Treffer markieren", font=('Arial', 10), bg="#34495e", fg="#bdc3c7").pack(pady=5)

        self.img_frame = tk.Frame(self, bg="#2c3e50")
        self.img_frame.pack(side="left", fill="both", expand=True)

        if self.orig_img_l:
            self.canvas_l = tk.Canvas(self.img_frame, bg="#1a252f", highlightthickness=0, cursor="fleur")
            self.canvas_l.pack(side="left", fill="both", expand=True, padx=5, pady=5)
            self.setup_canvas_bindings(self.canvas_l)
            
        if self.orig_img_r:
            self.canvas_r = tk.Canvas(self.img_frame, bg="#1a252f", highlightthickness=0, cursor="fleur")
            self.canvas_r.pack(side="left", fill="both", expand=True, padx=5, pady=5)
            self.setup_canvas_bindings(self.canvas_r)

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
            font = ImageFont.truetype("arial.ttf", 15)
        except IOError:
            font = ImageFont.load_default()

        if self.orig_img_l:
            new_w = int(self.orig_img_l.width * self.zoom_factor)
            new_h = int(self.orig_img_l.height * self.zoom_factor)
            img_l = self.orig_img_l.resize((new_w, new_h), Image.LANCZOS)
            draw_l = ImageDraw.Draw(img_l)
            self.draw_hits(draw_l, 'l', font)
            
            self.photo_l = ImageTk.PhotoImage(img_l)
            self.canvas_l.delete("all")
            self.canvas_l.create_image(0, 0, anchor="nw", image=self.photo_l)
            self.canvas_l.config(scrollregion=self.canvas_l.bbox("all"))
            
        if self.orig_img_r:
            new_w = int(self.orig_img_r.width * self.zoom_factor)
            new_h = int(self.orig_img_r.height * self.zoom_factor)
            img_r = self.orig_img_r.resize((new_w, new_h), Image.LANCZOS)
            draw_r = ImageDraw.Draw(img_r)
            self.draw_hits(draw_r, 'r', font)
            
            self.photo_r = ImageTk.PhotoImage(img_r)
            self.canvas_r.delete("all")
            self.canvas_r.create_image(0, 0, anchor="nw", image=self.photo_r)
            self.canvas_r.config(scrollregion=self.canvas_r.bbox("all"))
            
        # ---> NEU: Nach dem Zoomen das Fadenkreuz direkt neu über das Bild zeichnen <---
        self.on_tree_select(None)

    def draw_hits(self, draw, side, font):
        for i, hit in enumerate(self.timeline):
            if hit['s'] == side:
                cx = hit['x'] * self.zoom_factor
                cy = hit['y'] * self.zoom_factor
                score = hit.get('score', 0.0)
                
                r = self.caliber_radius * self.zoom_factor 
                draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline="red", width=4)
                
                if score > 0.0:
                    score_str = f"{score:.1f}"
                    text_x, text_y = cx + r + 5, cy - 8 
                    draw.text((text_x + 1, text_y + 1), score_str, fill="black", font=font)
                    color = "#00ff00" if score >= 10.0 else "#ffff00"
                    draw.text((text_x, text_y), score_str, fill=color, font=font)

    # ---> NEU: Die exakte, dezentere (aber knallige) Markierung <---
    def on_tree_select(self, event):
        # 1. Alte Markierungen komplett von beiden Canvas-Flächen löschen
        if self.orig_img_l: self.canvas_l.delete("highlight")
        if self.orig_img_r: self.canvas_r.delete("highlight")

        selected = self.tree.selection()
        if not selected:
            return

        # 2. Ausgewählten Treffer aus der Timeline holen
        item = selected[0]
        values = self.tree.item(item, "values")
        try:
            # Zeilennummer (beginnt bei 1) in Index (beginnt bei 0) umrechnen
            shot_idx = int(values[0]) - 1 
        except ValueError:
            return

        if shot_idx < 0 or shot_idx >= len(self.timeline):
            return

        hit = self.timeline[shot_idx]
        side = hit['s']
        
        # 3. Position an den aktuellen Zoom anpassen
        cx = hit['x'] * self.zoom_factor
        cy = hit['y'] * self.zoom_factor
        r = self.caliber_radius * self.zoom_factor
        
        # Welches Canvas ist das richtige?
        canvas = self.canvas_l if side == 'l' else self.canvas_r
        
        if canvas:
            # 4. Exakt deckungsgleich zeichnen!
            # Gleicher Radius, gleiche Linienstärke (width=4), 
            # aber knalliges Cyan ("#00ffff")
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r, 
                               outline="#00ffff", width=7, tags="highlight")
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

    def sort_column(self, col, reverse):
        def convert_value(value):
            try:
                if col == "Datum":
                    return dt.datetime.strptime(value, "%d.%m.%y %H:%M:%S")
                elif col in ["ID", "Schüsse"]:
                    return int(value)
                elif col == "Ringe":
                    return float(value) if value != "-" else -1.0
                return value
            except ValueError:
                return value
                
        data = [(convert_value(self.tree.set(k, col)), k) for k in self.tree.get_children('')]
        data.sort(reverse=reverse, key=lambda t: t[0])
        
        for index, (_, k) in enumerate(data):
            self.tree.move(k, '', index)
            
        self.tree.heading(col, command=lambda: self.sort_column(col, not reverse))

    def load_and_display_data(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                self.data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = []

        self.update_treeview(self.data)
        self.sort_column("ID", True)

    def update_treeview(self, data):
        for row in self.tree.get_children():
            self.tree.delete(row)
            
        for hs in data:
            match_id = hs.get('match_id', 0)
            datum = hs.get("timestamp", "-")
            spieler = hs.get("spieler", "Unbekannt")
            kameras = hs.get("kameras", "Unbekannt")
            schuesse = hs.get("gesamtpunkte", 0)
            
            ringe = hs.get("gesamt_ringe", 0.0) 
            ringe_str = f"{ringe:.1f}" if ringe > 0.0 else "-"
            
            self.tree.insert("", "end", values=(match_id, datum, spieler, kameras, schuesse, ringe_str))

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
            self.tree.selection_set(item)
            context_menu = tk.Menu(self.root, tearoff=0)
            context_menu.add_command(label="🎯 Treffer-Bilder anzeigen", command=self.show_hit_images, font=('Arial', 14))
            context_menu.add_separator()
            context_menu.add_command(label="🗑️ Match löschen", command=self.delete_selected_entries, font=('Arial', 14))
            context_menu.post(event.x_root, event.y_root)

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
        selected = self.tree.selection()
        if not selected: return
        
        match_id = int(self.tree.item(selected[0], "values")[0])
        zip_path = os.path.join("savegames", "logs", f"MATCH{match_id:06d}.zip")
        
        if not os.path.exists(zip_path):
            messagebox.showerror("Fehler", f"Die Datei {zip_path} existiert nicht mehr auf der Festplatte.")
            return
            
        MatchDetailWindow(self.root, match_id, zip_path)

if __name__ == "__main__":
    root = tk.Tk()
    app = HighscoreViewer(root)
    root.mainloop()