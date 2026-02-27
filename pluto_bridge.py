import os
import uuid
import requests
import time
from flask import Flask, send_from_directory
from datetime import datetime, timedelta
from threading import Thread
import xml.etree.ElementTree as ET

app = Flask(__name__)

# --- Configuration ---
PLUTO_USERNAME = os.getenv('PLUTO_USERNAME', 'votre_email@exemple.com')
PLUTO_PASSWORD = os.getenv('PLUTO_PASSWORD', 'votre_mot_de_passe')
START_CHNO = int(os.getenv('START', 0)) # Décalage des numéros de chaîne

auth_cache = {"token": None, "params": None, "expires": 0}

def authenticate():
    """Récupère le jeton JWT et les paramètres de session"""
    if auth_cache["token"] and time.time() < auth_cache["expires"]:
        return auth_cache

    device_id = str(uuid.uuid1())
    params = {
        'appName': 'web',
        'appVersion': '8.0.0',
        'deviceVersion': '122.0.0',
        'deviceType': 'web',
        'clientID': device_id,
        'username': PLUTO_USERNAME,
        'password': PLUTO_PASSWORD,
    }
    
    try:
        r = requests.get("https://boot.pluto.tv/v4/start", params=params)
        data = r.json()
        auth_cache["token"] = data['sessionToken']
        auth_cache["params"] = data.get('stitcherParams', '')
        auth_cache["expires"] = time.time() + 86400 # Valide 24h
        return auth_cache
    except Exception as e:
        print(f"Erreur d'authentification: {e}")
        return None

def generate_data():
    """Génère M3U, XMLTV et le fichier texte récapitulatif"""
    auth = authenticate()
    if not auth: return

    # Récupération EPG (fenêtre de 6h)
    start_dt = datetime.utcnow().strftime("%Y-%m-%d %H:00:00.000+0000")
    stop_dt = (datetime.utcnow() + timedelta(hours=6)).strftime("%Y-%m-%d %H:00:00.000+0000")
    
    url = f"https://api.pluto.tv/v2/channels?start={start_dt}&stop={stop_dt}"
    try:
        channels = requests.get(url).json()
    except:
        print("Erreur lors de la récupération des chaînes.")
        return

    m3u = "#EXTM3U\n"
    root = ET.Element("tv")
    txt_content = f"LISTE DES CHAINES PLUTO TV - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    txt_content += "="*60 + "\n"

    for ch in channels:
        if not ch.get('isStitched'): continue # Ignore les chaînes non diffusables

        ch_id = ch['_id']
        slug = ch['slug']
        ch_num = START_CHNO + int(ch.get('number', 0))
        logo = ch.get('colorLogoPNG', {}).get('path', '')
        
        # URL de flux avec jeton JWT pour authentification
        stream_url = f"https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv/v2/stitch/hls/channel/{ch_id}/master.m3u8?{auth['params']}&jwt={auth['token']}"
        
        # 1. Build M3U
        m3u += f'#EXTINF:0 channel-id="{slug}" tvg-chno="{ch_num}" tvg-logo="{logo}" group-title="{ch.get("category", "Pluto TV")}", {ch["name"]}\n{stream_url}\n\n'

        # 2. Build XMLTV
        channel_node = ET.SubElement(root, "channel", id=slug)
        ET.SubElement(channel_node, "display-name").text = ch['name']
        ET.SubElement(channel_node, "icon", src=logo)

        for prog in ch.get('timelines', []):
            s = datetime.strptime(prog['start'], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y%m%d%H%M%S +0000")
            e = datetime.strptime(prog['stop'], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y%m%d%H%M%S +0000")
            p_node = ET.SubElement(root, "programme", start=s, stop=e, channel=slug)
            ET.SubElement(p_node, "title", lang="fr").text = prog['title']
            ET.SubElement(p_node, "desc", lang="fr").text = prog['episode'].get('description', 'Pas de description.')

        # 3. Build TXT (Chaines avec flux)
        txt_content += f"NOM    : {ch['name']}\nCANAL  : {ch_num}\nFLUX   : {stream_url}\n" + "-"*60 + "\n"

    # Sauvegardes
    with open("playlist.m3u", "w", encoding="utf-8") as f: f.write(m3u)
    with open("chaines.txt", "w", encoding="utf-8") as f: f.write(txt_content)
    ET.ElementTree(root).write("epg.xml", encoding="utf-8", xml_declaration=True)
    
    print(f"[{datetime.now()}] Fichiers mis à jour (M3U, XML, TXT).")

def background_worker():
    """Mise à jour automatique toutes les 3 heures"""
    while True:
        generate_data()
        time.sleep(10800) # 3 heures

# --- Serveur Web ---
@app.route('/playlist.m3u')
def serve_m3u(): return send_from_directory('.', 'playlist.m3u', mimetype='text/plain')

@app.route('/epg.xml')
def serve_xml(): return send_from_directory('.', 'epg.xml', mimetype='text/xml')

@app.route('/chaines.txt')
def serve_txt(): return send_from_directory('.', 'chaines.txt', mimetype='text/plain')

if __name__ == '__main__':
    Thread(target=background_worker, daemon=True).start()
    app.run(host='0.0.0.0', port=8080)