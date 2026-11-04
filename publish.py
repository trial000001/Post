#!/usr/bin/env python3
"""Envoie la vidéo (URL publique + titre + légende) au webhook Make/Zapier/n8n,
qui se charge de la publier sur YouTube, TikTok et Instagram."""
import json
import os
import pathlib

import requests

meta = json.loads((pathlib.Path(__file__).resolve().parent / "output" / "meta.json").read_text())
payload = {**meta, "video_url": os.environ["VIDEO_URL"]}
r = requests.post(os.environ["WEBHOOK_URL"], json=payload, timeout=60)
print(r.status_code, r.text[:200])
r.raise_for_status()
