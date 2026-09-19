import configparser

class AuditedConfigParser(configparser.ConfigParser):
    def __init__(self, log_callback=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hier speichern wir die Funktion, die ins treffer_log.txt schreibt!
        self.log_callback = log_callback 

    def _check_fallback(self, section, option, kwargs):
        # Wenn ein Fallback übergeben wurde UND der Wert nicht in der INI steht:
        if 'fallback' in kwargs and not self.has_option(section, option):
            # 1. Den Typ des Fallbacks herausfinden und als sauberen String verpacken
            val = kwargs['fallback']
            if isinstance(val, bool):
                val_str = "yes" if val else "no"
            else:
                val_str = str(val)
                
            # 2. Den Wert sofort, still und leise ins RAM-Dictionary injizieren!
            if not self.has_section(section):
                self.add_section(section)
            self.set(section, option, val_str)
            
            # 3. Nur EINMAL loggen!
            msg = f"SYSTEM-AUTO-HEILUNG: Parameter '{option}' in [{section}] fehlte. Wurde im RAM mit Fallback '{val_str}' ergänzt."
            if self.log_callback:
                self.log_callback(msg)
            else:
                print(msg) 

    # Wir kapern die Standard-Methoden, checken den Fallback und geben die Arbeit dann an die Original-Methoden (super()) zurück!
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