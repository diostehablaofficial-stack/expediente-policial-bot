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
    with intelligent climax detection and visual-narrative synchronization.
    """
    clean_desc = clean_description(video_data.get("description", ""))
    duration = int(video_data.get("duration", 180))
    chapters = video_data.get("chapters", [])
    
    # Analyze chapters to locate bodycam and probable climax
    bodycam_offset = 0
    climax_hint = None
    chapters_formatted = []
    
    for ch in chapters:
        t = ch.get("title", "")
        st = int(ch.get("start_time", 0))
        chapters_formatted.append(f"- {st}s ({st//60}:{st%60:02d}): {t}")
        t_lower = t.lower()
        if bodycam_offset == 0 and any(k in t_lower for k in ["bodycam", "dashcam", "officer"]):
            bodycam_offset = st
        if any(k in t_lower for k in ["shoot", "fire", "shots", "attack", "confront", "k9", "flame", "lethal"]):
            if climax_hint is None or st > climax_hint:
                climax_hint = st
                
    chapters_text = "\n".join(chapters_formatted) if chapters_formatted else "Sin marcas de capítulo en el video original."
    
    # Calculate recommended slice
    if duration <= 125:
        suggested_start = bodycam_offset if bodycam_offset > 0 else 0
        slice_dur = min(duration - suggested_start, 115)
    else:
        # Long video: place the climax around second 70-85 of the slice
        if climax_hint and climax_hint > 45:
            suggested_start = max(0, climax_hint - 70)
        else:
            # Climax usually happens towards the second half of the incident
            suggested_start = max(bodycam_offset, duration - 125)
        slice_dur = min(115, duration - suggested_start)
    
    prompt = f"""
Eres el director y guionista principal de 'Expediente Policial' (canal de documentales True Crime forense en español).
Analiza los metadatos de esta grabación de cámara policial real (PoliceActivity):

Título original: {video_data.get('title')}
Duración total del video fuente: {duration} segundos
Capítulos del video:
{chapters_text}

Descripción de los hechos:
{clean_desc[:3000]}

REGLAS CRÍTICAS DE MONTAJE Y NARRACIÓN (EVITAR VIDEOS MOCHOS Y DESINCRONIZADOS):
1. SELECCIÓN DEL CORTE ('slice_start' y 'slice_duration'):
   - El Short final debe durar entre 95 y 118 segundos.
   - NUNCA cortes el video antes de que ocurra el desenlace o la acción principal ("video mocho"). Los videos policiales suelen tener minutos de diálogo o aproximación antes del enfrentamiento culminante.
   - Identifica en qué segundo exacto ocurre el CLÍMAX (el tiroteo, ataque armado, despliegue de fuerza o resolución crítica).
   - Ajusta 'slice_start' (segundo inicial del corte en el video fuente) de modo que el clímax quede situado aproximadamente entre el segundo 60 y 90 del corte, precedido por la tensión previa, y seguido por el desenlace y atención médica/esposamiento final.
   - 'slice_duration' debe ser máximo 118 segundos (para que sumado a los 3.5s del gancho inicial no supere los 120s reglamentarios).
   - Sugerencia calculada: slice_start={suggested_start}, slice_duration={slice_dur}.

2. SINCRONIZACIÓN VISUAL ESTRICTA ('narrations'):
   - Cada intervención de la voz en off DEBE coincidir con EXACTITUD con lo que la cámara está mostrando en la pantalla en ese segundo relativo del Short (target_time).
   - Entre 4 y 5 intervenciones concisas, dejando silencios tácticos para que se escuche el audio real (gritos, órdenes, sirenas, detonaciones).
   - target_time=1.0: Lo que se ve al inicio del corte (ej. oficiales rodeando el lugar, patrulla llegando).
   - target_time intermedio: La escalada o despliegue en ese segundo específico.
   - target_time en el clímax: La detonación, fuego o neutralización que la cámara capta en ese instante exacto.
   - target_time final: El aseguramiento de la escena y resolución.
   - PROHIBIDO narrar sucesos antes de que aparezcan en pantalla o que no ocurran en este corte.

3. ESTILO Y FORMATO:
   - 100% ESPAÑOL neutro, dramático y periodístico. Cero palabras en inglés, cero disclaimers o texto de Patreon.
   - 'teaser_start': Segundo relativo dentro del corte (ej. 75.0) donde ocurre el clímax más impactante para usarlo como gancho de 3.5 segundos con el banner 'A CONTINUACIÓN...'.

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
      "text": "Apertura concisa: ubicación y lo que la cámara muestra al inicio del corte."
    }},
    {{
      "id": "narr_02_conflict",
      "target_time": 18.0,
      "text": "Lo que la cámara enfoca en este segundo durante la aproximación."
    }},
    {{
      "id": "narr_03_action",
      "target_time": 50.0,
      "text": "El momento de tensión o ingreso que se visualiza aquí."
    }},
    {{
      "id": "narr_04_climax",
      "target_time": 80.0,
      "text": "El clímax, agresión o disparo que la cámara enfoca en este segundo."
    }},
    {{
      "id": "narr_05_resolution",
      "target_time": {max(95, slice_dur - 12)},
      "text": "Aseguramiento de la escena y llamado a suscribirse a Expediente Policial."
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
    Robust fallback analyzer with intelligent climax detection when Gemini is unavailable.
    """
    title = video_data.get("title", "Intervención Policial de Alto Riesgo")
    desc = clean_description(video_data.get("description", ""))
    duration = int(video_data.get("duration", 180))
    chapters = video_data.get("chapters", [])
    
    # Analyze chapters to locate bodycam and climax
    bodycam_offset = 0
    climax_hint = None
    for ch in chapters:
        t = ch.get("title", "").lower()
        st = int(ch.get("start_time", 0))
        if bodycam_offset == 0 and any(k in t for k in ["bodycam", "dashcam", "officer"]):
            bodycam_offset = st
        if any(k in t for k in ["shoot", "fire", "shots", "attack", "confront", "k9", "flame", "lethal"]):
            if climax_hint is None or st > climax_hint:
                climax_hint = st
                
    if duration <= 125:
        slice_start = bodycam_offset if bodycam_offset > 0 else 0
        slice_dur = min(duration - slice_start, 115)
    else:
        # Long video: place climax around second 70-85 of the slice
        if climax_hint and climax_hint > 45:
            slice_start = max(0, climax_hint - 70)
        else:
            slice_start = max(bodycam_offset, duration - 125)
        slice_dur = min(115, duration - slice_start)
    
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
