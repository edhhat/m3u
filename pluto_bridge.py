import os
import uuid
import requests
import time
import urllib.parse
import socket  # Importé pour la gestion du hostname
from flask import Flask, send_from_directory, render_template_string
from datetime import datetime, timedelta, timezone
from threading import Thread
import xml.etree.ElementTree as ET

# --- Détection du Hostname et de l'IP ---
try:
    HOSTNAME = socket.gethostname()
    LOCAL_IP = socket.gethostbyname(HOSTNAME)
except Exception:
    HOSTNAME = "localhost"
    LOCAL_IP = "127.0.0.1"

"""
================================================================================
LIENS UTILES (Nom de la machine : {0})
================================================================================
Accueil  : http://{0}:8080/
Canada   : http://{0}:8080/canada/playlist.m3u
France   : http://{0}:8080/france/playlist.m3u

Alternative IP : http://{1}:8080/
================================================================================
""".format(HOSTNAME, LOCAL_IP)

app = Flask(__name__)

# --- Configuration ---
PLUTO_USERNAME = os.getenv('PLUTO_USERNAME', 'eddyhuart@outlook.com')
PLUTO_PASSWORD = os.getenv('PLUTO_PASSWORD', 'J@cksoneddy1979')
START_CHNO = int(os.getenv('START', 0))

auth_cache = {"token": None, "params": None, "expires": 0}

def authenticate():
    """Authentification pour obtenir le JWT (Jeton de session)"""
    global auth_cache
    if auth_cache["token"] and time.time() < auth_cache["expires"]:
        return auth_cache
    
    device_id = str(uuid.uuid1())
    boot_params = {
        'appName': 'web', 'appVersion': '8.0.0-111b2b9dc00bd0bea9030b30662159ed9e7c8bc6',
        'deviceVersion': '122.0.0', 'deviceModel': 'web', 'deviceMake': 'chrome',
        'deviceType': 'web', 'clientID': device_id, 'clientModelNumber': '1.0.0',
        'serverSideAds': 'false', 'drmCapabilities': 'widevine:L3',
        'username': PLUTO_USERNAME, 'password': PLUTO_PASSWORD,
    }
    query_string = urllib.parse.urlencode(boot_params)
    boot_url = f"https://boot.pluto.tv/v4/start?{query_string}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'application/json', 'Origin': 'https://pluto.tv', 'Referer': 'https://pluto.tv/'
    }
    
    try:
        r_boot = requests.get(boot_url, headers=headers, timeout=15)
        if r_boot.status_code == 200:
            data = r_boot.json()
            auth_cache["token"] = data.get("sessionToken")
            auth_cache["params"] = data.get('stitcherParams', '')
            auth_cache["expires"] = time.time() + 86400 # Valide 24 heures
            print("Authentification Pluto TV réussie. JWT obtenu.")
            return auth_cache
    except Exception as e:
        print(f"Erreur d'authentification: {e}")
    return None

def write_files(channels, auth, prefix):
    """Génère les fichiers M3U et EPG à partir des données JSON"""
    m3u = "#EXTM3U\n"
    root = ET.Element("tv")
    
    for ch in channels:
        if not isinstance(ch, dict) or not ch.get('isStitched'): 
            continue
            
        if ch.get('slug', '').startswith('announcement') or ch.get('slug', '').startswith('privacy-policy'): 
            continue

        ch_id = ch.get('_id')
        slug = ch.get('slug', 'unknown')
        ch_num = START_CHNO + int(ch.get('number', 0))
        logo = ch.get('colorLogoPNG', {}).get('path', '')
        name = ch.get('name', 'Pluto TV')
        group = ch.get('category', 'Général')
        
        # Flux direct
        stream_url = (f"https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv/v2/stitch/hls/channel/{ch_id}/master.m3u8?"
                      f"{auth['params']}&jwt={auth['token']}&masterJWTPassthrough=true&includeExtendedEvents=true")
        
        m3u += f'#EXTINF:0 channel-id="{slug}" tvg-chno="{ch_num}" tvg-logo="{logo}" group-title="{group}", {name}\n{stream_url}\n\n'
        
        channel_node = ET.SubElement(root, "channel", id=slug)
        ET.SubElement(channel_node, "display-name").text = name
        ET.SubElement(channel_node, "icon", src=logo)

        timelines = ch.get('timelines', [])
        for prog in timelines:
            try:
                start_time = datetime.fromisoformat(prog.get('start').replace('Z', '+00:00')).strftime('%Y%m%d%H%M%S %z')
                stop_time = datetime.fromisoformat(prog.get('stop').replace('Z', '+00:00')).strftime('%Y%m%d%H%M%S %z')
            except Exception:
                continue 
            
            prog_node = ET.SubElement(root, "programme", start=start_time, stop=stop_time, channel=slug)
            ET.SubElement(prog_node, "title", lang="fr").text = prog.get('title', 'Programme')
            
            episode = prog.get('episode', {})
            desc = episode.get('description')
            if desc and desc != "No information available":
                ET.SubElement(prog_node, "desc", lang="fr").text = desc

    with open(f"{prefix}_playlist.m3u", "w", encoding="utf-8") as f: 
        f.write(m3u)
        
    tree = ET.ElementTree(root)
    if hasattr(ET, "indent"):
        ET.indent(tree, space="  ", level=0)
    tree.write(f"{prefix}_epg.xml", encoding="utf-8", xml_declaration=True)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fichiers {prefix} mis à jour.")

def generate_data():
    """Récupère les données via l'API v2"""
    auth = authenticate()
    if not auth: return

    now = datetime.now(timezone.utc)
    start_str = urllib.parse.quote(now.strftime('%Y-%m-%d %H:00:00.000%z'))
    stop_str = urllib.parse.quote((now + timedelta(hours=12)).strftime('%Y-%m-%d %H:00:00.000%z'))

    url = f"https://api.pluto.tv/v2/channels?start={start_str}&stop={stop_str}"

    headers_base = {'User-Agent': 'Mozilla/5.0', 'Authorization': f'Bearer {auth["token"]}'}

    # 1. Canada
    try:
        res_ca = requests.get(url, headers=headers_base, timeout=20)
        if res_ca.status_code == 200:
            write_files(res_ca.json(), auth, "canada")
    except Exception as e:
        print(f"Erreur Canada: {e}")

    # 2. France (Simulée via X-Forwarded-For)
    headers_fr = headers_base.copy()
    headers_fr['X-Forwarded-For'] = '80.214.24.50' 
    try:
        res_fr = requests.get(url, headers=headers_fr, timeout=20)
        if res_fr.status_code == 200:
            write_files(res_fr.json(), auth, "france")
    except Exception as e:
        print(f"Erreur France: {e}")

def background_worker():
    while True:
        generate_data()
        time.sleep(10800)

@app.route('/')
def index():
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Bridge Pluto TV ({{ hostname }})</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background-color: #f4f4f9; }
                .container { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                table { border-collapse: collapse; width: 100%; margin-top: 20px; }
                th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
                th { background-color: #007bff; color: white; }
                a { color: #007bff; text-decoration: none; font-weight: bold; }
                .info { color: #666; font-size: 0.9em; margin-bottom: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Bridge Pluto TV</h1>
                <p class="info">Serveur : <strong>{{ hostname }}</strong> ({{ ip }})</p>
                <table>
                    <tr><th>Région</th><th>Playlist M3U</th><th>Guide EPG (XML)</th></tr>
                    <tr>
                        <td>Canada</td>
                        <td><a href="/canada/playlist.m3u">Télécharger M3U</a></td>
                        <td><a href="/canada/epg.xml">Télécharger EPG</a></td>
                    </tr>
                    <tr>
                        <td>France</td>
                        <td><a href="/france/playlist.m3u">Télécharger M3U</a></td>
                        <td><a href="/france/epg.xml">Télécharger EPG</a></td>
                    </tr>
                </table>
            </div>
        </body>
        </html>
    ''', hostname=HOSTNAME, ip=LOCAL_IP)

@app.route('/<region>/playlist.m3u')
def serve_m3u(region):
    return send_from_directory('.', f'{region}_playlist.m3u')

@app.route('/<region>/epg.xml')
def serve_xml(region):
    return send_from_directory('.', f'{region}_epg.xml')

if __name__ == '__main__':
    Thread(target=background_worker, daemon=True).start()
    print(f"Serveur actif : http://{HOSTNAME}:8080")
    print(f"Lien IP local : http://{LOCAL_IP}:8080")
    app.run(host='0.0.0.0', port=8080)