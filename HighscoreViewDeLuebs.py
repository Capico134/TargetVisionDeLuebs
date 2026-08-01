import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import re
import zipfile
import io
import datetime as dt
from PIL import Image, ImageTk, ImageDraw, ImageFont

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
        """Sortiert die Spalten intelligent (Datum, Zahlen, Text)."""
        def convert_value(value):
            try:
                if col == "Datum":
                    return dt.datetime.strptime(value, "%d.%m.%y %H:%M:%S")
                elif col in ["ID", "Schüsse"]:
                    return int(value)
                elif col == "Ringe":
                    # --- GEÄNDERT: Wenn ein Strich (-) im Feld steht, werten wir ihn zum Sortieren als -1 ---
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
        #self.sort_column("Ringe", True) 
        self.sort_column("ID", True)#Sortieren nach ID

    def update_treeview(self, data):
        for row in self.tree.get_children():
            self.tree.delete(row)
            
        for hs in data:
            match_id = hs.get('match_id', 0)
            datum = hs.get("timestamp", "-")
            spieler = hs.get("spieler", "Unbekannt")
            kameras = hs.get("kameras", "Unbekannt")
            schuesse = hs.get("gesamtpunkte", 0)
            
            # --- GEÄNDERT: Blendet 0.0 aus, wenn keine Ringe berechnet wurden ---
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
            
        try:
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                match_data = json.loads(zipf.read("match.json").decode('utf-8'))
                timeline = match_data.get("timeline", [])
                
                img_window = tk.Toplevel(self.root)
                img_window.title(f"Trefferbilder - MATCH {match_id}")
                img_window.configure(bg="#34495e")
                
                # --- GEÄNDERT: Schriftart verkleinert auf 15 ---
                try:
                    font = ImageFont.truetype("arial.ttf", 15)
                except IOError:
                    font = ImageFont.load_default()
                
                # Linkes Bild suchen und rendern
                try:
                    img_l_data = zipf.read("debug_bilder/letzte_aufnahme_left.jpg")
                    img_l = Image.open(io.BytesIO(img_l_data))
                    draw_l = ImageDraw.Draw(img_l)
                    
                    for hit in timeline:
                        if hit['s'] == 'l':
                            x, y = hit['x'], hit['y']
                            score = hit.get('score', 0.0) 
                            
                            # 1. Roter Kringel wird IMMER gezeichnet
                            draw_l.ellipse((x-14, y-14, x+14, y+14), outline="red", width=4)
                            
                            # 2. Text nur zeichnen, wenn es wirklich eine Wertung gibt (> 0.0)
                            if score > 0.0:
                                score_str = f"{score:.1f}"
                                text_x, text_y = x + 15, y - 8 # Etwas näher ans Fadenkreuz gerückt
                                
                                draw_l.text((text_x + 1, text_y + 1), score_str, fill="black", font=font)
                                color = "#00ff00" if score >= 10.0 else "#ffff00"
                                draw_l.text((text_x, text_y), score_str, fill=color, font=font)
                            
                    photo_l = ImageTk.PhotoImage(img_l)
                    lbl_l = tk.Label(img_window, image=photo_l, bg="#34495e")
                    lbl_l.image = photo_l
                    lbl_l.pack(side="left", padx=10, pady=10)
                except KeyError: pass
                
                # Rechtes Bild suchen und rendern
                try:
                    img_r_data = zipf.read("debug_bilder/letzte_aufnahme_right.jpg")
                    img_r = Image.open(io.BytesIO(img_r_data))
                    draw_r = ImageDraw.Draw(img_r)
                    
                    for hit in timeline:
                        if hit['s'] == 'r':
                            x, y = hit['x'], hit['y']
                            score = hit.get('score', 0.0)
                            
                            # 1. Roter Kringel wird IMMER gezeichnet
                            draw_r.ellipse((x-14, y-14, x+14, y+14), outline="red", width=4)
                            
                            # 2. Text nur zeichnen, wenn es wirklich eine Wertung gibt (> 0.0)
                            if score > 0.0:
                                score_str = f"{score:.1f}"
                                text_x, text_y = x + 15, y - 8 
                                
                                draw_r.text((text_x + 1, text_y + 1), score_str, fill="black", font=font)
                                color = "#00ff00" if score >= 10.0 else "#ffff00"
                                draw_r.text((text_x, text_y), score_str, fill=color, font=font)
                            
                    photo_r = ImageTk.PhotoImage(img_r)
                    lbl_r = tk.Label(img_window, image=photo_r, bg="#34495e")
                    lbl_r.image = photo_r
                    lbl_r.pack(side="right", padx=10, pady=10)
                except KeyError: pass
                
        except Exception as e:
            messagebox.showerror("Fehler beim Öffnen", f"Konnte das Archiv nicht laden:\n{e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = HighscoreViewer(root)
    root.mainloop()