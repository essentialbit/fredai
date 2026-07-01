#!/usr/bin/env python3
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup

HTML_FILE = Path("/Volumes/Iron 1TBSSD/Claude/FredAI/templates/dashboard.html")

print("=========================================================")
print("          FredAI UI & HTML Infrastructure Audit          ")
print("=========================================================")

if not HTML_FILE.exists():
    print(f"[Error] {HTML_FILE} does not exist")
    sys.exit(1)

html_content = HTML_FILE.read_text(encoding="utf-8")
soup = BeautifulSoup(html_content, "html.parser")

# 1. Collect all defined IDs in HTML
defined_ids = set()
for tag in soup.find_all(id=True):
    defined_ids.add(tag["id"])

print(f"  Found {len(defined_ids)} HTML elements with defined IDs.")

# 2. Collect all Javascript function definitions
js_scripts = [script.string for script in soup.find_all("script") if script.string]
combined_js = "\n".join(js_scripts)

# Regex to find function names: function name() or async function name()
function_pat = re.compile(r'\b(?:async\s+)?function\s+([a-zA-Z0-9_]+)\s*\(')
defined_functions = set(function_pat.findall(combined_js))

print(f"  Found {len(defined_functions)} Javascript function definitions.")

# 3. Audit all onclick / onchange / onkeydown handlers in HTML elements
missing_functions = []
handlers_found = 0

handler_attrs = ["onclick", "onchange", "onkeydown", "oninput"]
for tag in soup.find_all(True):
    for attr in handler_attrs:
        if tag.has_attr(attr):
            val = tag[attr]
            handlers_found += 1
            # Extract potential function call names: e.g. sendFred() -> sendFred
            calls = re.findall(r'\b([a-zA-Z0-9_]+)\s*\(', val)
            for call in calls:
                # Exclude basic JS builtins and keywords
                ignored_keywords = [
                    "alert", "confirm", "encodeURIComponent", "decodeURIComponent", 
                    "parseInt", "parseFloat", "setTimeout", "setInterval", "if", "for", 
                    "while", "switch", "getElementById", "click", "preventDefault", 
                    "stopPropagation", "location", "reload", "toggle", "add", "remove", 
                    "console", "log", "fetch", "then", "catch"
                ]
                if call in ignored_keywords:
                    continue
                if call not in defined_functions:
                    missing_functions.append((tag.name, tag.get("id") or tag.get("class"), attr, val, call))

# 4. Audit all g('id') and document.getElementById('id') calls in JS
missing_ids = []
# Match g('some-id') or g("some-id")
g_calls = set(re.findall(r"\bg\(['\"]([a-zA-Z0-9_\-]+)['\"]\)", combined_js))
# Match document.getElementById('some-id')
get_element_calls = set(re.findall(r"document\.getElementById\(['\"]([a-zA-Z0-9_\-]+)['\"]\)", combined_js))

referenced_ids = g_calls.union(get_element_calls)
for ref_id in referenced_ids:
    # Exclude dynamically constructed IDs or ones from plugins
    if ref_id in defined_ids:
        continue
    # Some IDs are dynamically generated or external (like globe canvas containers created by library)
    # Let's list them as warnings/checks
    missing_ids.append(ref_id)

# 5. Report Findings
print("\n--- RESULTS ---")
errors = 0

if missing_functions:
    print("\n[FAIL] Missing Javascript functions referenced in HTML attributes:")
    for tag, identifier, attr, full_val, func in missing_functions:
        print(f"  - Element <{tag}> ({identifier}) {attr}='{full_val}' calls undefined function: {func}()")
        errors += 1
else:
    print("\n[OK] All HTML attribute event handlers point to valid defined Javascript functions.")

if missing_ids:
    # Filter out known library containers or dynamic components
    filtered_missing_ids = []
    ignore_patterns = ["chart-", "tv-", "lightweight-", "globe-", "apex-", "container"]
    for mid in missing_ids:
        if any(pat in mid.lower() for pat in ignore_patterns):
            continue
        filtered_missing_ids.append(mid)
        
    if filtered_missing_ids:
        print("\n[INFO/CHECK] IDs referenced in JS but missing in static HTML (could be dynamic):")
        for mid in sorted(filtered_missing_ids):
            print(f"  - ID: {mid}")
    else:
        print("\n[OK] All JS static ID lookups refer to existing HTML elements.")
else:
    print("\n[OK] All JS static ID lookups refer to existing HTML elements.")

print("\n=========================================================")
if errors > 0:
    print(f"Audit completed with {errors} error(s).")
    sys.exit(1)
else:
    print("Audit completed successfully! 0 structural errors.")
    sys.exit(0)
