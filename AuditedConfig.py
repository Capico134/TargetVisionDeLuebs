import configparser

class AuditedConfigParser(configparser.ConfigParser):
    # =====================================================================
    # ---> NEU: DAS ZENTRALE LEGACY-WÖRTERBUCH (STRATEGIE C) <---
    # =====================================================================
    LEGACY_MAPPING = {
        'Erkennung': {
            'hybrid_discard_faktor': 'discard_big_hits',
            'debug_subpixel_export': 'detail_export_aktiv'
        }
    }
    
    def __init__(self, log_callback=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_callback = log_callback 
        self.healed_parameters = [] # Hier sammeln wir alle geretteten Keys!
        self.migrated_parameters = [] # <--- NEU: Merkliste für Übersetzungen

    def apply_legacy_mapping(self):
        """Übersetzt alte Parameternamen im RAM in die neuen, sauberen Namen."""
        
        # 1. Das normale Dictionary-Mapping
        for section, mapping in self.LEGACY_MAPPING.items():
            if self.has_section(section):
                for old_key, new_key in mapping.items():
                    if self.has_option(section, old_key):
                        val = self.get(section, old_key)
                        if not self.has_option(section, new_key):
                            self.set(section, new_key, val)
                        self.remove_option(section, old_key)
                        self.migrated_parameters.append((section, old_key, new_key, val))
                        msg = f"🔧 LEGACY-MIGRATOR: Alter Parameter '{old_key}' in [{section}] wurde zu '{new_key}' übersetzt."
                        if self.log_callback: self.log_callback(msg)
                        else: print(msg)

        # 2. SONDERFALL: Linsen-Verzerrung (Fischauge) mit mathematischer Umrechnung
        if self.has_section('Kameras'):
            for side in ['links', 'rechts']:
                old_k_key = f'fischaugenkorrektur_{side}'
                new_k_key = f'linsen_verzerrung_{side}'
                curve_key = f'linsen_kurve_{side}' # <--- NEU: Der Exponent
                
                if self.has_option('Kameras', old_k_key):
                    val_str = self.get('Kameras', old_k_key)
                    try:
                        val_float = float(val_str)
                        # Umrechnung von Linear (Exp=1) auf unsere neue Mitte (Exp=1.5)
                        # Schnittpunkt bei 45.5mm: k_neu = k_alt / (45.5 ** 0.5)
                        new_val = val_float / (45.5 ** 0.5)
                        
                        if not self.has_option('Kameras', new_k_key):
                            # Auf 8 Nachkommastellen runden
                            self.set('Kameras', new_k_key, str(round(new_val, 8)))
                            
                            # ---> NEU: ELA-Injection der 1.5 Standard-Kurve! <---
                            if not self.has_option('Kameras', curve_key):
                                self.set('Kameras', curve_key, "1.5")
                            
                            # =======================================================
                            # ---> NEU: ELA-Korrekturfaktor für px_pro_mm (Integral-Ausgleich)
                            # Perfekter Ausgleich zwischen linear (22.75) und Kurve 1.5 (18.2)
                            # =======================================================
                            faktor = (1.0 + (val_float * 22.75)) / (1.0 + (val_float * 18.2))
                            
                            px_key_x = f'px_pro_mm_x_{side}'
                            px_key_y = f'px_pro_mm_y_{side}'
                            
                            if self.has_option('Kameras', px_key_x):
                                old_px_x = self.getfloat('Kameras', px_key_x)
                                self.set('Kameras', px_key_x, str(round(old_px_x * faktor, 3)))
                            if self.has_option('Kameras', px_key_y):
                                old_px_y = self.getfloat('Kameras', px_key_y)
                                self.set('Kameras', px_key_y, str(round(old_px_y * faktor, 3)))
                            
                        self.remove_option('Kameras', old_k_key)
                        self.migrated_parameters.append(('Kameras', old_k_key, new_k_key, new_val))
                        
                        msg = f"🔧 LEGACY-MIGRATOR: '{old_k_key}' ({val_float}) konvertiert (Kurve 1.5). px_pro_mm um {(1-faktor)*100:.2f}% verkleinert."
                        if self.log_callback: self.log_callback(msg)
                        else: print(msg)
                    except ValueError:
                        pass

    def _check_fallback(self, section, option, kwargs):
        if 'fallback' in kwargs and not self.has_option(section, option):
            val = kwargs['fallback']
            
            # ---> DER KORRIGIERTE BUG <---
            if isinstance(val, bool):
                val_str = "yes" if val else "no"
            else:
                val_str = str(val)
                
            if not self.has_section(section):
                self.add_section(section)
            self.set(section, option, val_str)
            
            self.healed_parameters.append(f"[{section}] {option}")
            
            msg = f"SYSTEM-AUTO-HEILUNG: Parameter '{option}' in [{section}] fehlte. Wurde im RAM mit Fallback '{val_str}' ergänzt."
            if self.log_callback:
                self.log_callback(msg)
            else:
                print(msg) 

    def get(self, section, option, **kwargs):
        self._check_fallback(section, option, kwargs)
        return super().get(section, option, **kwargs)

    def getint(self, section, option, **kwargs):
        self._check_fallback(section, option, kwargs)
        return super().getint(section, option, **kwargs)

    def getfloat(self, section, option, **kwargs):
        self._check_fallback(section, option, kwargs)
        return super().getfloat(section, option, **kwargs)

    def getboolean(self, section, option, **kwargs):
        self._check_fallback(section, option, kwargs)
        return super().getboolean(section, option, **kwargs)