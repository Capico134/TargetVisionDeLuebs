import configparser

class AuditedConfigParser(configparser.ConfigParser):
    def __init__(self, log_callback=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_callback = log_callback 
        self.healed_parameters = [] # Hier sammeln wir alle geretteten Keys!

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