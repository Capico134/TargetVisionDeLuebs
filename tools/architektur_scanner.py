import os
import glob
import re
import ast

CONFIG_PATTERN = re.compile(
    r'\.get(?:int|float|boolean)?\s*\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]'
)
DUMB_PARSER_PATTERN = re.compile(r'configparser\.ConfigParser\(\)')
DIRECT_OPEN_PATTERN = re.compile(r'open\s*\(\s*[\'"][^\'"]*config\.ini[\'"]')

def scan_project():
    print("🔍 Starte Architektur- & Bypass-Scan...\n")
    
    py_files = glob.glob("..\*.py")
    
    report_lines = [
        "# 🏗️ TargetVision Architektur & Bypass-Scan",
        "Prüft Config-Zugriffe und sucht nach Vibe-Coding-Abkürzungen.",
        "---", ""
    ]
    
    total_classes = 0
    total_functions = 0
    total_config_calls = 0
    total_bypasses = 0
    
    for filepath in sorted(py_files):
        if os.path.basename(filepath) == os.path.basename(__file__):
            continue
            
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"⚠️ Konnte {filepath} nicht lesen: {e}")
            continue
            
        try:
            tree = ast.parse(content)
        except Exception:
            continue
            
        classes = []
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, ast.FunctionDef) and not node.name.startswith("__"):
                functions.append(node.name)

        config_calls = set()
        for match in CONFIG_PATTERN.finditer(content):
            config_calls.add(f"[{match.group(1)}] {match.group(2)}")

        bypasses = []
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if DUMB_PARSER_PATTERN.search(line) and "class AuditedConfigParser" not in content:
                bypasses.append(f"Zeile {i+1}: Standard 'configparser.ConfigParser()' statt AuditedConfigParser genutzt")
            if DIRECT_OPEN_PATTERN.search(line):
                bypasses.append(f"Zeile {i+1}: 'config.ini' wurde direkt mit open() geöffnet")

        if classes or functions or config_calls or bypasses:
            report_lines.append(f"## 📄 `{filepath}`")
            
            if bypasses:
                total_bypasses += len(bypasses)
                report_lines.append("### 🚨 ARCHITEKTUR-BYPASS GEFUNDEN!")
                for b in bypasses:
                    report_lines.append(f"- **{b}**")
                report_lines.append("")
            
            if classes:
                total_classes += len(classes)
                report_lines.append(f"**Klassen ({len(classes)}):** {', '.join(classes)}\n")
                
            if functions:
                total_functions += len(functions)
                preview = ", ".join(functions)#[:5])
                #if len(functions) > 5:
                #    preview += f" ... (*und {len(functions)-5} weitere*)"
                report_lines.append(f"**Methoden ({len(functions)}):** {preview}\n")
                
            if config_calls:
                total_config_calls += len(config_calls)
                report_lines.append(f"**Config-Zugriffe ({len(config_calls)}):**")
                for call in sorted(config_calls):#)[:5]:
                    report_lines.append(f"- `{call}`")
                #if len(config_calls) > 5:
                #    report_lines.append(f"- *... und {len(config_calls)-5} weitere*")
                report_lines.append("")
                
            report_lines.append("---\n")

    summary = [
        "## 📊 Zusammenfassung",
        f"- **Analysierte Dateien:** {len(py_files) - 1}",
        f"- **Gefundene Klassen:** {total_classes}",
        f"- **Gefundene Funktionen:** {total_functions}",
        f"- **Direkte Config-Aufrufe:** {total_config_calls}",
        f"- 🚨 **Gefundene Bypasses:** {total_bypasses}",
        "---\n"
    ]
    report_lines.insert(4, "\n".join(summary))

    with open("Architektur_Scan_Report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
        
    print(f"✅ Scan abgeschlossen! {total_bypasses} Bypasses gefunden.")
    print("📁 Bericht gespeichert in: Architektur_Scan_Report.md")

if __name__ == "__main__":
    scan_project()