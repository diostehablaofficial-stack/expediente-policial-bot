import os
import re
import json

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
        if any(bad in l_str.lower() for bad in ["disclaimer", "patreon", "support us", "educational purposes only", "subscribe"]):
            continue
        cleaned_lines.append(l_str)
    return "\n".join(cleaned_lines)

def analyze_with_gemini(api_key, video_data):
    """
    Uses Gemini API to extract 100% Spanish high-impact True Crime script,
    with multiple narrator interventions across the timeline.
    """
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    clean_desc = clean_description(video_data.get("description", ""))
    duration = video_data.get("duration", 180)
    slice_dur = min(duration, 125)
    
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
3. La voz en off (narrador) DEBE hacer entre 4 y 5 intervenciones a lo largo del video para mantener al espectador enganchado sin silencios largos.
4. Genera títulos y textos para el banner visual superior (HUD Card).

Devuelve EXCLUSIVAMENTE un JSON válido (sin backticks de markdown ```json, solo las llaves):
{{
  "spanish_title": "Título impactante en mayúsculas para YouTube Shorts (máx 75 caracteres, con #Shorts)",
  "badge_sub": "Texto secundario del banner, ej: CASO REAL | POLICÍA DE GREENVILLE (máx 40 caracteres, 100% español)",
  "badge_title": "Titular principal del banner en mayúsculas, ej: OFICIAL HERIDO EN EMBOSCADA (máx 35 caracteres, 100% español)",
  "seo_description": "Descripción optimizada para YouTube con resumen del caso y hashtags (#Shorts #ExpedientePolicial #PoliceActivity #CasoReal #Policias)",
  "slice_start": 10,
  "slice_duration": {slice_dur},
  "narrations": [
    {{
      "id": "narr_01_hook",
      "target_time": 1.0,
      "text": "Frase de apertura de 1 o 2 oraciones para enganchar en los primeros 5 segundos."
    }},
    {{
      "id": "narr_02_context",
      "target_time": 25.0,
      "text": "Explicación del motivo del despacho policial y quién es el sospechoso."
    }},
    {{
      "id": "narr_03_tension",
      "target_time": 55.0,
      "text": "Descripción táctica del momento de mayor peligro o negativa a acatar órdenes."
    }},
    {{
      "id": "narr_04_action",
      "target_time": 85.0,
      "text": "Análisis del desenlace armado o la respuesta defensiva de los oficiales."
    }},
    {{
      "id": "narr_05_outro",
      "target_time": {slice_dur - 12},
      "text": "Resultado de la investigación oficial y llamado a suscribirse a Expediente Policial."
    }}
  ]
}}
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n", "", text)
            text = re.sub(r"\n```$", "", text)
        data = json.loads(text)
        return data
    except Exception as e:
        print(f"[Analyzer] Gemini analysis exception: {e}. Falling back to rule-based engine.")
        return None

def analyze_rule_based(video_data):
    """
    Robust fallback analyzer when Gemini is unavailable.
    """
    title = video_data.get("title", "Intervención Policial de Alto Riesgo")
    desc = clean_description(video_data.get("description", ""))
    duration = video_data.get("duration", 180)
    slice_dur = min(duration, 125)
    
    # Extract location
    loc_match = re.search(r"^([^\n—–\-]+(?:County|City|Department|Parish|Police|State|Town)?[^—–\-]*)", desc)
    location = loc_match.group(1).strip() if loc_match else "ESTADOS UNIDOS"
    location = re.sub(r"[\*\(\)\[\]]", "", location).strip()
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
            "id": "narr_02_context",
            "target_time": 25.0,
            "text": "Los oficiales respondieron a la alerta sin imaginar el nivel de amenaza que estaban a punto de encontrar."
        },
        {
            "id": "narr_03_tension",
            "target_time": 55.0,
            "text": "A pesar de las órdenes verbales repetidas, el sospechoso mantuvo una actitud desafiante."
        },
        {
            "id": "narr_04_action",
            "target_time": 85.0,
            "text": "Ante la agresión directa e inminente, los agentes tuvieron que recurrir a la fuerza defensiva."
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
        "slice_start": 10 if duration > 140 else 0,
        "slice_duration": slice_dur,
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
