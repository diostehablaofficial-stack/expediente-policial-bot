import os
import re
import json
import requests

def determine_case_code(history_file):
    """
    Returns e.g. 'EXP_009' based on existing history count.
    """
    count = 8
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                count = len(data)
        except Exception:
            pass
    return f"EXP_{count+1:03d}"

def clean_location(loc_raw):
    """
    Cleans up location string and ensures NO disclaimer or boilerplate is included.
    """
    l = re.sub(r"[\*\(\)\[\]\"\'\:\;]", "", loc_raw).strip()
    if any(b in l.lower() for b in ["disclaimer", "warning", "note", "content", "educational", "intended", "purposes"]):
        return "ESTADOS UNIDOS"
        
    translations = [
        ("Greenville County, South Carolina", "Greenville, Carolina del Sur"),
        ("South Carolina", "Carolina del Sur"),
        ("North Carolina", "Carolina del Norte"),
        ("New York", "Nueva York"),
        ("New Mexico", "Nuevo México"),
        ("County", "Condado de")
    ]
    for en, es in translations:
        if en in l:
            l = l.replace(en, es)
            break

    return l

def clean_description(raw_desc):
    """
    Strips disclaimers, patreon links, and boilerplate to extract real case facts.
    """
    lines = raw_desc.split("\n")
    cleaned_lines = []
    for l in lines:
        l_str = l.strip()
        if not l_str:
            continue
        if any(bad in l_str.lower() for bad in ["disclaimer", "patreon", "support us", "educational", "informational", "purposes only", "subscribe", "youtube"]):
            continue
        cleaned_lines.append(l_str)
    return "\n".join(cleaned_lines)


def analyze_with_gemini(api_key, video_data):
    """
    Uses Gemini API to extract 100% Spanish high-impact True Crime script,
    with multiple narrator interventions across the timeline.
    """
    clean_desc = clean_description(video_data.get("description", ""))
    duration = video_data.get("duration", 180)
    
    # Check if there is a 911 call or bodycam chapter offset
    chapters = video_data.get("chapters", [])
    bodycam_offset = 0
    for ch in chapters:
        t = ch.get("title", "").lower()
        if any(k in t for k in ["bodycam", "dashcam", "officer", "shooting", "chase"]):
            bodycam_offset = int(ch.get("start_time", 0))
            break
            
    rem_dur = duration - bodycam_offset
    slice_dur = min(rem_dur if rem_dur > 30 else duration, 120)
    suggested_start = bodycam_offset if bodycam_offset > 0 else (10 if duration > 140 else 0)
    
    prompt = f"""
Eres el director y guionista principal de 'Expediente Policial' (canal de documentales True Crime forense en español).
Analiza los metadatos de esta grabación de cámara policial real (PoliceActivity):

Título original: {video_data.get('title')}
Duración estimada del Short: {slice_dur} segundos
Descripción de los hechos:
{clean_desc[:3000]}

REQUISITOS ESTRICTOS:
1. TODO el texto debe estar en ESPAÑOL neutro, dramático y periodístico.
2. NUNCA incluyas palabras en inglés, avisos de disclaimer ni texto de Patreon.
3. La voz en off (narrador) DEBE hacer entre 4 y 5 intervenciones clave y concisas, sincronizadas rigurosamente con los sucesos visuales que aparecen en pantalla en ese segundo exacto. No satures con demasiadas intervenciones: deja silencios para que se escuche el audio real de la cámara policial (sirenas, disparos, radio).
4. Genera títulos y textos para el banner visual superior (HUD Card).
5. Determina el segundo exacto donde ocurre la parte más crítica, peligrosa o de mayor acción del video ('teaser_start', ej: 25.0) para mostrarlo al inicio como un gancho de 3.5 segundos con el banner 'A CONTINUACIÓN...'.
6. 'slice_start' debe ser el segundo donde comienza la acción visual en vivo de la cámara policial (mínimo {suggested_start}s para omitir llamadas de audio 911 o mapas iniciales).

Devuelve EXCLUSIVAMENTE un JSON válido (sin backticks de markdown ```json, solo las llaves):
{{
  "spanish_title": "Título impactante en mayúsculas para YouTube Shorts (máx 75 caracteres, con #Shorts)",
  "badge_sub": "Texto secundario del banner, ej: CASO REAL | POLICÍA DE GREENVILLE (máx 40 caracteres, 100% español)",
  "badge_title": "Titular principal del banner en mayúsculas, ej: OFICIAL HERIDO EN EMBOSCADA (máx 35 caracteres, 100% español)",
  "seo_description": "Descripción optimizada para YouTube con resumen del caso y hashtags (#Shorts #ExpedientePolicial #PoliceActivity #CasoReal #Policias)",
  "slice_start": {suggested_start},
  "slice_duration": {slice_dur},
  "teaser_start": 25.0,
  "teaser_duration": 3.5,
  "narrations": [
    {{
      "id": "narr_01_spot",
      "target_time": 1.0,
      "text": "Apertura concisa: ubicación, hora y lo que la cámara muestra al inicio."
    }},
    {{
      "id": "narr_02_conflict",
      "target_time": 8.5,
      "text": "El estallido del conflicto o agresión que ocurre en este segundo."
    }},
    {{
      "id": "narr_03_action",
      "target_time": 25.0,
      "text": "La maniobra táctica o escape que la cámara muestra en este momento."
    }},
    {{
      "id": "narr_04_radio",
      "target_time": 63.0,
      "text": "La situación de tensión, cobertura o llamada de auxilio por radio."
    }},
    {{
      "id": "narr_05_outro",
      "target_time": {max(105, slice_dur - 12)},
      "text": "Desenlace final de la supervivencia y llamado a suscribirse a Expediente Policial."
    }}
  ]
}}
"""
    models_to_try = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.8-flash"]
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4
        }
    }
    
    for mod in models_to_try:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={api_key}"
            r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
            if r.status_code == 200:
                res = r.json()
                text = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text.startswith("```"):
                    text = re.sub(r"^```(?:json)?\n", "", text)
                    text = re.sub(r"\n```$", "", text)
                data = json.loads(text)
                # Validate teaser and slice values
                try:
                    t_start = float(data.get("teaser_start", 25.0))
                    s_start = float(data.get("slice_start", suggested_start))
                    if t_start >= s_start and t_start < duration:
                        t_start = t_start - s_start
                    if t_start < 0 or t_start > slice_dur - 4.0:
                        t_start = max(5.0, min(slice_dur - 5.0, 25.0))
                    data["teaser_start"] = t_start
                except Exception:
                    data["teaser_start"] = 25.0
                data["teaser_duration"] = 3.5
                print(f"[Analyzer] Successfully generated metadata with {mod}!")
                return data
            else:
                print(f"[Analyzer] Model {mod} returned {r.status_code}. Trying next fallback...")
        except Exception as e:
            print(f"[Analyzer] Exception with {mod}: {e}. Trying next fallback...")

    print("[Analyzer] All Gemini models failed. Falling back to rule-based engine.")
    return None

def analyze_rule_based(video_data):
    """
    Robust fallback analyzer when Gemini is unavailable.
    """
    title = video_data.get("title", "Intervención Policial de Alto Riesgo")
    desc = clean_description(video_data.get("description", ""))
    duration = video_data.get("duration", 180)
    
    # Check if there is a 911 call or bodycam chapter offset
    chapters = video_data.get("chapters", [])
    bodycam_offset = 0
    for ch in chapters:
        t = ch.get("title", "").lower()
        if any(k in t for k in ["bodycam", "dashcam", "officer", "shooting", "chase"]):
            bodycam_offset = int(ch.get("start_time", 0))
            break
            
    rem_dur = duration - bodycam_offset
    slice_dur = min(rem_dur if rem_dur > 30 else duration, 120)
    slice_start = bodycam_offset if bodycam_offset > 0 else (10 if duration > 140 else 0)
    
    # Extract location
    loc_match = re.search(r"^([^\n—–\-]+(?:County|City|Department|Parish|Police|State|Town)?[^—–\-]*)", desc)
    raw_loc = loc_match.group(1).strip() if loc_match else "ESTADOS UNIDOS"
    location = clean_location(raw_loc)
    if len(location) > 35:
        location = location[:35].strip()

        
    badge_title = "INTERVENCIÓN POLICIAL DE ALTO RIESGO"
    if "shot" in title.lower() or "shootout" in title.lower():
        badge_title = "TIROTEO Y RESPUESTA ARMADA"
    elif "flames" in title.lower() or "fire" in title.lower():
        badge_title = "ATAQUE VIOLENTO CONTRA AGENTES"
    elif "pit" in title.lower() or "chase" in title.lower():
        badge_title = "PERSECUCIÓN A ALTA VELOCIDAD"
    elif "hostage" in title.lower():
        badge_title = "SITUACIÓN CON REHENES"
        
    badge_sub = f"CASO REAL | {location.upper()}"
    if len(badge_sub) > 40:
        badge_sub = badge_sub[:40]
        
    spanish_title = f"¡{badge_title}! | CASO REAL #Shorts"
    
    narrations = [
        {
            "id": "narr_01_hook",
            "target_time": 1.0,
            "text": f"Una intervención que cambió en segundos en {location}."
        },
        {
            "id": "narr_02_conflict",
            "target_time": 16.0,
            "text": "Los oficiales inician la persecución al ver que el sospechoso ignora las órdenes de detenerse."
        },
        {
            "id": "narr_03_action",
            "target_time": 38.0,
            "text": "De imprevisto, el sujeto se gira y despliega una amenaza letal directa contra los agentes."
        },
        {
            "id": "narr_04_tension",
            "target_time": 68.0,
            "text": "Bajo extrema presión, se despliega la maniobra táctica y se solicita respaldo urgente por radio."
        },
        {
            "id": "narr_05_outro",
            "target_time": max(100.0, slice_dur - 12.0),
            "text": "Las investigaciones oficiales determinaron el uso justificado de la fuerza. Suscríbete a Expediente Policial."
        }
    ]

    seo_description = f"""Cámara corporal y análisis táctico oficial de los hechos ocurridos en {location}.

📌 Caso: {badge_title}
⚖️ Grabaciones de archivo policial de dominio público con fines informativos, periodísticos y educativos.

Suscríbete a Expediente Policial para seguir descubriendo los procedimientos forenses y las intervenciones oficiales más impactantes.

#Shorts #ExpedientePolicial #PoliceActivity #CasoReal #Bodycam #Policias #TrueCrime
"""

    return {
        "spanish_title": spanish_title,
        "badge_sub": badge_sub,
        "badge_title": badge_title,
        "seo_description": seo_description,
        "slice_start": slice_start,
        "slice_duration": slice_dur,
        "teaser_start": 25.0 if slice_dur > 35 else 5.0,
        "teaser_duration": 3.5,
        "narrations": narrations
    }

def analyze_video(video_data, history_file):
    case_code = determine_case_code(history_file)
    print(f"[Analyzer] Processing case {case_code} for video '{video_data.get('title')}'")
    
    gemini_key = os.environ.get("GEMINI_API_KEY")
    result = None
    if gemini_key:
        print("[Analyzer] GEMINI_API_KEY detected. Requesting AI True Crime generation with multiple interventions...")
        result = analyze_with_gemini(gemini_key, video_data)
        
    if not result:
        print("[Analyzer] Generating structured metadata via rule-based engine...")
        result = analyze_rule_based(video_data)
        
    result["case_code"] = case_code
    result["video_id"] = video_data.get("id")
    result["video_url"] = video_data.get("url") or f"https://www.youtube.com/watch?v={video_data.get('id')}"
    result["original_title"] = video_data.get("title")
    
    print(f"[Analyzer] Ready: [{case_code}] {result['spanish_title']}")
    print(f"[Analyzer] Badge Sub: {result['badge_sub']} | Badge Title: {result['badge_title']}")
    print(f"[Analyzer] Total Voice Interventions: {len(result.get('narrations', []))}")
    return result

if __name__ == "__main__":
    from detector import find_next_candidate
    hist = os.path.join(os.path.dirname(__file__), "..", "data", "processed_history.json")
    cand = find_next_candidate(hist)
    if cand:
        meta = analyze_video(cand, hist)
        print(json.dumps(meta, indent=2, ensure_ascii=False))
