#!/usr/bin/env python3
"""Genera oui.json.gz a partir de los registros públicos del IEEE (MA-L, MA-M, MA-S).

Uso: python3 scripts/build-oui.py [dir_con_csvs]
Descarga los CSV si no existen:
  https://standards-oui.ieee.org/oui/oui.csv
  https://standards-oui.ieee.org/oui28/mam.csv
  https://standards-oui.ieee.org/oui36/oui36.csv
"""
import csv
import gzip
import json
import os
import sys
import urllib.request

URLS = {
    "oui.csv": "https://standards-oui.ieee.org/oui/oui.csv",
    "mam.csv": "https://standards-oui.ieee.org/oui28/mam.csv",
    "oui36.csv": "https://standards-oui.ieee.org/oui36/oui36.csv",
}

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, ".devtest", "oui")
os.makedirs(src, exist_ok=True)

table: dict[str, str] = {}
for name, url in URLS.items():
    path = os.path.join(src, name)
    if not os.path.exists(path):
        print(f"Descargando {url}")
        urllib.request.urlretrieve(url, path)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            prefix = row["Assignment"].strip().upper()
            org = " ".join(row["Organization Name"].split())
            if prefix and org:
                table[prefix] = org

out = os.path.join(root, "oui.json.gz")
with gzip.open(out, "wt", encoding="utf-8", compresslevel=9) as f:
    json.dump(table, f, ensure_ascii=False, separators=(",", ":"))
print(f"{len(table)} prefijos -> {out} ({os.path.getsize(out) // 1024} KB)")
