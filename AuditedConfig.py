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
        for section, mapping in self.LEGACY_MAPPING.items():
            if self.has_section(section):
                for old_key, new_key in mapping.items():
                    if self.has_option(section, old_key):
                        val = self.get(section, old_key)
                        
                        # Unter neuem Namen speichern
                        if not self.has_option(section, new_key):
                            self.set(section, new_key, val)
                            
                        # Alten Eintrag restlos aus dem RAM löschen
                        self.remove_option(section, old_key)
                        
                        self.migrated_parameters.append((section, old_key, new_key, val))
                        
                        msg = f"🔧 LEGACY-MIGRATOR: Alter Parameter '{old_key}' in [{section}] wurde zu '{new_key}' übersetzt."
                        if self.log_callback:
                            self.log_callback(msg)
                        else:
                            print(msg)

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