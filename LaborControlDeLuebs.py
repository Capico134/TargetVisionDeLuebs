import time
import math
import tkinter as tk
from tkinter import ttk 
import cv2
from PIL import Image, ImageTk

class LaborNavigationController:
    """
    INSEL A: DAS KAMERA-STATIV
    Zuständig für: Panning, Zoom (Mausrad & Box), Zentrierung und Viewport-Berechnung.
    """
    def __init__(self, app):
        self.app = app

    def on_zoom_box_start(self, event):
        """Startet den Rahmen-Zoom (Strg / Shift)"""
        self.app.root.focus_set() 
        if getattr(self.app, 'color_picker_active', False):
            return "break"
            
        self.app.is_zoom_box_active = True
        self.app.zoom_box_start_x = event.x
        self.app.zoom_box_start_y = event.y
        return "break"
        
    def on_zoom_box_motion(self, event):
        """Berechnet die Koordinaten und weist den Renderer an, den Rahmen zu zeichnen"""
        if getattr(self.app, 'is_zoom_box_active', False):
            if self.app.zoom_factor >= self.app.max_zoom_factor - 0.01:
                return "break"
                
            current_time = time.time()
            if current_time - getattr(self.app, 'last_zoombox_update_time', 0) < 0.040:
                return
            self.app.last_zoombox_update_time = current_time
            
            self.app.renderer.draw_zoom_box(
                self.app.zoom_box_start_x, self.app.zoom_box_start_y, 
                event.x, event.y, 
                getattr(self.app, 'viewport_place_x', getattr(self.app, 'pan_x', 0)), getattr(self.app, 'viewport_place_y', getattr(self.app, 'pan_y', 0))
            )
        return "break"

    def on_zoom_box_stop(self, event):
        """Führt den Box-Zoom aus"""
        if getattr(self.app, 'is_zoom_box_active', False):
            self.app.is_zoom_box_active = False
            self.app.renderer.hide_zoom_box()
            self.apply_zoom_box(self.app.zoom_box_start_x, self.app.zoom_box_start_y, event.x, event.y)
        return "break"

    def abort_zoom_box(self, event=None):
        """Bricht das Aufziehen des Zoom-Rahmens ab, wenn ESC gedrückt wird."""
        if getattr(self.app, 'is_zoom_box_active', False):
            self.app.is_zoom_box_active = False
            self.app.zoom_box_start_x = None
            self.app.zoom_box_start_y = None
            self.app.renderer.hide_zoom_box()
            self.app.print_log("SYSTEM", "Zoom-Rahmen abgebrochen.")

    def apply_zoom_box(self, x1, y1, x2, y2):
        """Berechnet aus dem gezogenen Rahmen den neuen Zoom und zentriert den Ausschnitt."""
        min_x, max_x = min(x1, x2), max(x1, x2)
        min_y, max_y = min(y1, y2), max(y1, y2)
        
        box_w = max_x - min_x
        box_h = max_y - min_y
        
        if box_w < 15 or box_h < 15:
            self.app.identify_shot_at_click(x2, y2, jump_to_frame=True)
            return
            
        if self.app.zoom_factor >= self.app.max_zoom_factor - 0.01:
            self.app.print_log("SYSTEM", f"Maximaler Zoom ({self.app.max_zoom_factor}x) erreicht. Rahmen-Zoom gesperrt.")
            return 
            
        self.app.root.update_idletasks()
        container_w = self.app.img_container.winfo_width()
        container_h = self.app.img_container.winfo_height()
        
        old_scale = getattr(self.app, 'current_scale', 1.0)
        
        zoom_multiplier = min(container_w / box_w, container_h / box_h)
        zoom_multiplier = max(1.01, min(zoom_multiplier, 15.0))
        
        self.app.zoom_factor = max(0.2, min(self.app.zoom_factor * zoom_multiplier, self.app.max_zoom_factor))
        
        if hasattr(self.app, 'current_context') and self.app.current_context and self.app.current_context.live_img is not None:
            h, w = self.app.current_context.live_img.shape[:2]
        else:
            h, w = 720, 1280
            
        new_scale = (550.0 / h) * self.app.zoom_factor
        
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        
        abs_center_x = center_x + getattr(self.app, 'last_vp_x', 0)
        abs_center_y = center_y + getattr(self.app, 'last_vp_y', 0)
        
        self.app.pan_x = int((container_w / 2.0) - (abs_center_x / old_scale) * new_scale)
        self.app.pan_y = int((container_h / 2.0) - (abs_center_y / old_scale) * new_scale)
        
        self.app.renderer.update_image_display(push_to_gui=True)
        self.app.update_frame_title()

    def on_drag_start(self, event):
        """Normaler Linksklick (Verschieben, Kalibrieren, Pipette)"""
        self.app.root.focus_set() 
        
        if getattr(self.app, 'tk_image', None) is None or getattr(self.app, '_is_loading', False):
            self.app.drag_start_x = None
            self.app.drag_start_y = None
            return

        if getattr(self.app, 'calib_mode_active', False):
            if event.widget == self.app.lbl_image:
                 self.app.handle_calibration_click(event)
            return

        if getattr(self.app, 'color_picker_active', False):
            self.app.pick_color_from_event(event)
            self.app.toggle_color_picker() 
            return

        self.app.drag_start_x = event.x_root
        self.app.drag_start_y = event.y_root
        self.app.start_pan_x = self.app.pan_x
        self.app.start_pan_y = self.app.pan_y

    def on_drag_motion(self, event):
        """Verschiebt das Bild normal mit FPS-Drossel"""
        if getattr(self.app, 'is_zoom_box_active', False):
            return self.on_zoom_box_motion(event)

        if getattr(self.app, 'tk_image', None) is None: return
        
        if self.app.drag_start_x is None or self.app.drag_start_y is None: 
            return
            
        current_time = time.time()
        if current_time - getattr(self.app, 'last_pan_update_time', 0) < 0.040:
            return
        self.app.last_pan_update_time = current_time
        
        dx = event.x_root - self.app.drag_start_x
        dy = event.y_root - self.app.drag_start_y
        
        self.app.pan_x = self.app.start_pan_x + dx
        self.app.pan_y = self.app.start_pan_y + dy
        
        if getattr(self.app, 'zoom_factor', 1.0) > 4.0:
            self.app.renderer.update_image_display(full_rebuild=False, push_to_gui=True)
        else:
            self.app.lbl_image.place(x=self.app.pan_x, y=self.app.pan_y)

    def on_drag_stop(self, event):
        """Normales Loslassen (Verschieben beenden oder Röntgen-Klick)"""
        start_x = self.app.drag_start_x
        start_y = self.app.drag_start_y
        self.app.drag_start_x = None
        self.app.drag_start_y = None

        if getattr(self.app, 'is_zoom_box_active', False):
            return self.on_zoom_box_stop(event)

        if getattr(self.app, 'color_picker_active', False): return
        if getattr(self.app, 'tk_image', None) is None: return
        
        if start_x is None or start_y is None: 
            return

        dx = event.x_root - start_x
        dy = event.y_root - start_y
        dist = (dx**2 + dy**2)**0.5

        if dist < 5:  
            self.app.identify_shot_at_click(event.x, event.y)
        else:
            if self.app.package_data and self.app.package_data.get('config'):
                if self.app.package_data['config'].getboolean('Erkennung', 'detail_export_aktiv', fallback=False):
                    self.app.renderer.update_image_display(full_rebuild=False, push_to_gui=True)

    def reset_view(self, event=None):
        """Setzt Zoom und Position zurück (Auto-Fit bei Rechtsklick)"""
        if getattr(self.app, 'current_zip_path', None):
            self.auto_zoom_and_center()
        else:
            self.app.zoom_factor = 1.0
            self.app.pan_x = 0
            self.app.pan_y = 0
            self.app.lbl_image.place(x=0, y=0)
            
        self.app.renderer.update_image_display()
        self.app.update_frame_title()

    def center_on_last_shot(self, event=None):
        """Zentriert den letzten Schuss des aktuellen Bildes in der angeklickten Bildhälfte."""
        if getattr(self.app, 'current_engine_shots', None) is None or not hasattr(self.app, 'current_scale'):
            return
            
        side = self.app.active_camera_var.get()
        current_frame_num = self.app.current_index
        
        valid_shots = [s for s in self.app.current_engine_shots if s.get('side') == side and s.get('labor_frame_num') == current_frame_num]
        
        if not valid_shots:
            self.app.print_log("SYSTEM", f"Mittelklick: Kein neuer Treffer in Bild #{current_frame_num} gefunden, auf den zentriert werden könnte.")
            return
            
        latest_shot = valid_shots[-1]
        hx, hy = latest_shot['pos']
        
        self.app.print_log("SYSTEM", f"Mittelklick: Zentriere auf Treffer (X:{hx:.1f}, Y:{hy:.1f}) in Bild #{current_frame_num}")
        
        self.app.root.update_idletasks()
        container_w = self.app.img_container.winfo_width()
        container_h = self.app.img_container.winfo_height()
        
        abs_x = event.x + getattr(self.app, 'last_vp_x', 0)
        is_left = (abs_x < getattr(self.app, 'current_img_w', 0))
        
        if is_left:
            shot_img_x = hx * self.app.current_scale
            target_container_x = (container_w / 4.0) * 2.0
        else:
            shot_img_x = (hx * self.app.current_scale) + self.app.current_img_w
            target_container_x = (container_w / 4.0) * 2.0
            
        shot_img_y = hy * self.app.current_scale
        target_container_y = container_h / 2.0
        
        self.app.pan_x = int(target_container_x - shot_img_x)
        self.app.pan_y = int(target_container_y - shot_img_y)
        
        if getattr(self.app, 'zoom_factor', 1.0) > 4.0:
            self.app.renderer.update_image_display(full_rebuild=False, push_to_gui=True)
        else:
            self.app.lbl_image.place(x=self.app.pan_x, y=self.app.pan_y)
        
        self.app.on_mouse_move(event)

    def auto_zoom_and_center(self):
        """Berechnet den optimalen Zoom, sodass das Doppel-Bild exakt in den sichtbaren Bereich passt."""
        side = self.app.active_camera_var.get()
        
        h, w = 720, 1280
        ref_name = next((f for f in getattr(self.app, 'all_files', []) if f"referenz_{side}" in f), None)
        if ref_name:
            ref_img = self.app.get_img(ref_name)
            if ref_img is not None:
                h, w = ref_img.shape[:2]
                
        self.app.root.update_idletasks() 
        container_h = self.app.img_container.winfo_height()
        container_w = self.app.img_container.winfo_width()
        
        if container_h < 100: container_h = 800
        if container_w < 100: container_w = 1200
        
        target_scale_w = (container_w * 1.00) / (w * 2.0)
        target_scale_h = (container_h * 1.00) / float(h)
        target_scale = min(target_scale_w, target_scale_h)
        
        self.app.zoom_factor = target_scale * (h / 550.0)
        self.app.zoom_factor = max(0.2, min(self.app.zoom_factor, self.app.max_zoom_factor))
        
        echte_scale = (550.0 / h) * self.app.zoom_factor
        
        self.app.pan_x = int((container_w - (w * 2.0 * echte_scale)) / 2.0)
        self.app.pan_y = int((container_h - (h * echte_scale)) / 2.0)
        
        self.app.lbl_image.place(x=self.app.pan_x, y=self.app.pan_y)
    
    def on_mouse_scroll(self, event):
        if not getattr(self.app, '_is_scrolling', False):
            self.app._is_scrolling = True
            self.app._scroll_start_zoom = self.app.zoom_factor
            self.app._scroll_mouse_x = event.x
            self.app._scroll_mouse_y = event.y
            
        if event.num == 4 or getattr(event, 'delta', 0) > 0:
            self.app.zoom_factor *= 1.15 
        elif event.num == 5 or getattr(event, 'delta', 0) < 0:
            self.app.zoom_factor *= 0.85 
            
        self.app.zoom_factor = max(0.2, min(self.app.zoom_factor, self.app.max_zoom_factor))
        self.app.update_frame_title()
        
        if hasattr(self.app, '_scroll_timer') and self.app._scroll_timer is not None:
            self.app.root.after_cancel(self.app._scroll_timer)
            
        # ---> ELA-FIX: Hier rufen wir direkt unsere eigene Methode auf <---
        self.app._scroll_timer = self.app.root.after(100, lambda e=event: self._apply_scroll(e))

    def _apply_scroll(self, event):
        """Führt das tatsächliche, schwere Rendern nach Abschluss der Mausrad-Bewegung aus."""
        self.app._scroll_timer = None
        self.app._is_scrolling = False 
        
        old_zoom = getattr(self.app, '_scroll_start_zoom', self.app.zoom_factor)
        
        if self.app.zoom_factor != old_zoom:
            scale_change = self.app.zoom_factor / old_zoom
            
            mx = self.app._scroll_mouse_x
            my = self.app._scroll_mouse_y
            
            abs_mx = mx - self.app.pan_x
            abs_my = my - self.app.pan_y
            
            new_abs_mx = abs_mx * scale_change
            new_abs_my = abs_my * scale_change
            
            self.app.pan_x = int(mx - new_abs_mx)
            self.app.pan_y = int(my - new_abs_my)
            
        self.app.renderer.update_image_display(push_to_gui=True)
        self.app.on_mouse_move(event)


class LaborPlaybackController:
    """
    INSEL B: DER KASSETTENREKORDER
    Zuständig für: Vor, Zurück, Erster Schuss, Letzter Schuss, Direktsprung.
    """
    def __init__(self, app):
        self.app = app

    def prev_shot(self):
        if self.app.current_index > 0:
            self.app.current_index -= 1
            self.app.process_and_display()

    def next_shot(self):
        if self.app.current_index < len(self.app.get_current_side_origs()):
            self.app.current_index += 1
            self.app.process_and_display()

    def safe_prev_shot(self, event=None):
        # ELA-Schutz: Wenn wir in JEDWEDEM Textfeld/Dropdown sind, ignorieren wir die Pfeiltasten!
        if isinstance(self.app.root.focus_get(), (tk.Entry, ttk.Combobox)):
            return
        self.prev_shot()

    def safe_next_shot(self, event=None):
        if isinstance(self.app.root.focus_get(), (tk.Entry, ttk.Combobox)):
            return
        self.next_shot()

    def first_shot(self):
        if self.app.current_index > 0:
            self.app.current_index = 0
            self.app.process_and_display()

    def last_shot(self):
        max_idx = len(self.app.get_current_side_origs())
        if self.app.current_index < max_idx:
            self.app.current_index = max_idx
            self.app.process_and_display() 

    def jump_to_shot(self, event=None):
        max_idx = len(self.app.get_current_side_origs())
        try:
            target_shot = int(self.app.shot_jump_var.get().strip())
            target_shot = max(0, min(target_shot, max_idx))
            self.app.current_index = target_shot
            self.app.process_and_display()
        except ValueError:
            self.app.shot_jump_var.set(str(self.app.current_index))
            
class LaborToolController:
    """
    INSEL C: DER WERKZEUGKASTEN
    Zuständig für: Fadenkreuz (Radar), Röntgen-Klick, Battle-Royale VAR und Farbpipette.
    """
    def __init__(self, app):
        self.app = app

    def on_mouse_move(self, event):
        """Das Radar: Aktualisiert Koordinaten, liest Pixel-Werte und zeichnet das Fadenkreuz."""
        if getattr(self.app, 'base_combined_img', None) is None or not hasattr(self.app, 'current_scale'):
            return

        if self.app.is_interacting:
            return

        if getattr(self.app, '_is_rendering_crosshair', False):
            return 
            
        current_time = time.time()
        if current_time - getattr(self.app, 'last_mouse_update_time', 0) < 0.025:
            return
            
        self.app.last_mouse_update_time = current_time
        self.app._is_rendering_crosshair = True 
        
        try:
            self.app.last_mouse_x = event.x
            self.app.last_mouse_y = event.y
            
            x, y = event.x, event.y
            img_h, img_w = self.app.base_combined_img.shape[:2]
            
            if x < 0 or y < 0 or x >= img_w or y >= img_h:
                self.on_mouse_leave(event)
                return
                
            abs_x = x + getattr(self.app, 'last_vp_x', 0)
            abs_y = y + getattr(self.app, 'last_vp_y', 0)
            
            is_left = (abs_x < self.app.current_img_w)
            raw_x = abs_x if is_left else (abs_x - self.app.current_img_w)
            real_x = int(raw_x / self.app.current_scale)
            real_y = int(abs_y / self.app.current_scale)
            
            # ---> SEIDEN-MUSTER: Die Daten direkt aus dem perfekten Kontext-Paket holen! <---
            ctx = getattr(self.app, 'current_context', None)
            if ctx and ctx.live_img is not None:
                orig_h, orig_w = ctx.live_img.shape[:2]
                real_x = max(0, min(real_x, orig_w - 1))
                real_y = max(0, min(real_y, orig_h - 1))

            diff_val = ctx.raw_diff[real_y, real_x] if ctx and ctx.raw_diff is not None else 0
            
            if ctx and ctx.color_multiplier is not None:
                factor = ctx.color_multiplier[real_y, real_x]
                dist_c = ctx.color_dist[real_y, real_x] if ctx.color_dist is not None else 0
                bonus_str = f" | Dist: {dist_c:.0f} | F: {factor:.2f}"
            else:
                bonus_str = " | Filter Aus"
                
            side_name = "Live" if is_left else "Rechts"
            self.app.lbl_coords.config(text=f"{side_name} X:{real_x:04d} Y:{real_y:04d} | D:{diff_val:03d}{bonus_str}")
            
            if self.app.zoom_factor >= 5.0:
                if getattr(self.app, '_crosshair_active', False):
                    self.on_mouse_leave(event)
                    self.app._crosshair_active = False
                return 
                
            self.app._crosshair_active = True
            self.app.renderer.draw_crosshair(x, y)
            
        finally:
            self.app._is_rendering_crosshair = False

    def on_mouse_leave(self, event):
        """Putzt das Fadenkreuz weg, wenn die Maus das Bild verlässt."""
        if self.app.is_interacting:
            return
            
        self.app.lbl_coords.config(text="Maus nicht im Bild")
        self.app.last_mouse_x = None
        self.app.last_mouse_y = None
        
        if getattr(self.app, 'base_combined_img_rgb', None) is not None:
            img_pil = Image.fromarray(self.app.base_combined_img_rgb)
            self.app.tk_image = ImageTk.PhotoImage(img_pil)
            self.app.lbl_image.config(image=self.app.tk_image)
 
    def toggle_color_picker(self):
        """Schaltet den Modus um und ändert das Aussehen des Buttons/Mauszeigers"""
        self.app.color_picker_active = not getattr(self.app, 'color_picker_active', False)
        if self.app.color_picker_active:
            self.app.btn_pick_color.config(bg="#e74c3c", text="🔴 Klick ins Bild...")
            self.app.lbl_image.config(cursor="crosshair")
        else:
            self.app.btn_pick_color.config(bg="#f39c12", text="🎨 Wandfarbe picken")
            self.app.lbl_image.config(cursor="")

    def pick_color_from_event(self, event):
        """Holt den Farbwert unter der Maus und schreibt ihn in die Config"""
        if getattr(self.app, 'base_combined_img', None) is None or not hasattr(self.app, 'current_scale'):
            return
            
        x, y = event.x, event.y
        img_h, img_w = self.app.base_combined_img.shape[:2]
        if x < 0 or y < 0 or x >= img_w or y >= img_h: return
        abs_x = x + getattr(self.app, 'last_vp_x', 0)
        abs_y = y + getattr(self.app, 'last_vp_y', 0)
        
        is_left = (abs_x < self.app.current_img_w)
        raw_x = abs_x if is_left else (abs_x - self.app.current_img_w)
        real_x = int(raw_x / self.app.current_scale)
        real_y = int(abs_y / self.app.current_scale)

        ctx = getattr(self.app, 'current_context', None)
        if ctx and ctx.live_img is not None:
            orig_h, orig_w = ctx.live_img.shape[:2]
            real_x = max(0, min(real_x, orig_w - 1))
            real_y = max(0, min(real_y, orig_h - 1))
            
            b_val, g_val, r_val = ctx.live_img[real_y, real_x]
            
            if getattr(self.app, 'package_data', None) and self.app.package_data.get('config'):
                config_ram = self.app.package_data['config']
                side_str = "Hintergrund_Links" if self.app.current_side == 'left' else "Hintergrund_Rechts"
                
                if not config_ram.has_section(side_str):
                    config_ram.add_section(side_str)
                
                config_ram.set(side_str, 'rgb_r', str(r_val))
                config_ram.set(side_str, 'rgb_g', str(g_val))
                config_ram.set(side_str, 'rgb_b', str(b_val))
                
                self.app.print_log("SYSTEM", f"🎨 WANDFARBE GEUPDATET ({side_str}): RGB({r_val}, {g_val}, {b_val}) gepickt an Position X:{real_x}, Y:{real_y}")
                self.app.on_param_change(force=True)

    def identify_shot_at_click(self, x, y, jump_to_frame=False):
        """Sucht den Treffer unter der Maus und blendet die Frame-Info ein"""
        if getattr(self.app, 'base_combined_img', None) is None: return
            
        abs_x = x + getattr(self.app, 'last_vp_x', 0)
        abs_y = y + getattr(self.app, 'last_vp_y', 0)
        is_left = (abs_x < self.app.current_img_w)
        raw_x = abs_x if is_left else (abs_x - self.app.current_img_w)
        real_x = int(raw_x / self.app.current_scale)
        real_y = int(abs_y / self.app.current_scale)

        radius = getattr(self.app, 'current_radius_px', 15)
        best_shot = None
        best_dist = float('inf')

        for shot in getattr(self.app, 'current_engine_shots', []):
            sx, sy = shot['pos']
            d = ((sx - real_x)**2 + (sy - real_y)**2)**0.5
            if d <= radius and d < best_dist:
                best_shot = shot
                best_dist = d

        if best_shot:
            f_num = best_shot.get('labor_frame_num', '?')
            decimals = 1
            if getattr(self.app, 'package_data', None) and self.app.package_data.get('config'):
                decimals = self.app.package_data['config'].getint('Zielscheibe', 'ringwertung_nachkommastellen', fallback=1)
                
            self.app.print_log("SYSTEM", f"🎯 RÖNTGEN-SCAN: Dieser Treffer entstand in BILD #{f_num} (Score: {best_shot.get('score', 0.0):.{decimals}f})")
            
            self.app.highlighted_shot = {
                'pos': best_shot['pos'], 
                'frame': f_num, 
                'cal_radius': best_shot.get('cal_radius', radius), 
                'time': time.time()
            }
            
            if jump_to_frame and isinstance(f_num, int):
                self.app.print_log("SYSTEM", f"🚀 ZEITREISE: Springe direkt zu Bild #{f_num}...")
                self.app.current_index = f_num
                self.app.process_and_display()
            else:
                self.app.renderer.update_image_display(full_rebuild=False)
            
            if hasattr(self.app, '_highlight_timer') and self.app._highlight_timer is not None:
                self.app.root.after_cancel(self.app._highlight_timer)
            self.app._highlight_timer = self.app.root.after(5000, self.clear_highlight)

    def clear_highlight(self):
        """Löscht das orangene/lila Highlight nach Ablauf des Timers"""
        self.app.highlighted_shot = None
        self.app._highlight_timer = None 
        self.app.renderer.update_image_display(full_rebuild=False)
  
    def toggle_var_mode(self, step, event=None):
        """Aktiviert das Battle Royale VAR für ALLE neuen Schüsse im aktuellen Bild."""
        if isinstance(self.app.root.focus_get(), (tk.Entry, ttk.Combobox)): return
        if self.app.current_index == 0: return 
        
        side = getattr(self.app, 'current_side', self.app.active_camera_var.get())
        current_frame_num = self.app.current_index
        
        self.app.var_shots = []
        for s in getattr(self.app, 'current_engine_shots', []):
            if s.get('side') == side and s.get('labor_frame_num') == current_frame_num and s.get('is_new', False):
                details = s.get('score_export_details', {})
                if details and 'all_candidates' in details and details['all_candidates']:
                    self.app.var_shots.append(s)
                    
        if not self.app.var_shots:
            self.app.print_log("SYSTEM", "Keine Kandidaten-Daten im aktuellen Bild gefunden (Wurden ohne Subpixel-Export generiert).")
            return
            
        was_active = getattr(self.app, 'candidate_view_active', False)
        self.app.candidate_view_active = True
        
        max_candidates = len(self.app.var_shots[0]['score_export_details']['all_candidates'])
        
        if not was_active:
            self.app.candidate_idx = 0 if step > 0 else max_candidates - 1
        else:
            current_idx = getattr(self.app, 'candidate_idx', 0)
            self.app.candidate_idx = (current_idx + step) % max_candidates
        
        if hasattr(self.app, '_var_timer') and self.app._var_timer is not None:
            self.app.root.after_cancel(self.app._var_timer)
            self.app._var_timer = None                                      
        
        self.app.renderer.update_image_display(full_rebuild=False)

    def clear_var_mode(self, event=None):
        """Beendet den VAR-Modus und räumt auf."""
        if getattr(self.app, 'candidate_view_active', False):
            self.app.candidate_view_active = False
            self.app.candidate_idx = 0
            self.app.var_shots = []
            if hasattr(self.app, '_var_timer') and self.app._var_timer is not None:
                self.app.root.after_cancel(self.app._var_timer)
                self.app._var_timer = None
            self.app.renderer.update_image_display(full_rebuild=False)            