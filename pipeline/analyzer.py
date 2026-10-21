import os
import re
import json

def determine_case_code(history_file):
    """
    Returns e.g. 'EXP_008' based on existing history count.
    """
    count = 7
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                count = len(data)
        except Exception:
            pass
    return f"EXP_{count+1:03d}"

def analyze_with_gemini(api_key, video_data):
    """
    Uses Gemini API to extract high-impact True Crime Spanish script and metadata.
    """
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    prompt = f"""
Eres el guionista y productor principal del canal 'Expediente Policial' (True Crime en español, estilo dramático, documental y forense).
Analiza los siguientes metadatos de un video real de cámara corporal de la policía (PoliceActivity):

Título en inglés: {video_data.get('title')}
Duración total: {video_data.get('duration')} segundos
Capítulos disponibles: {json.dumps(video_data.get('chapters', []))}
Descripción original de la policía:
{video_data.get('description', '')[:2500]}

Devuelve EXCLUSIVAMENTE un objeto JSON válido con la siguiente estructura (sin formato Markdown adicional, solo el JSON):
{{
  "spanish_title": "Título llamativo en español para YouTube Shorts y TikTok (máx 75 caracteres, con mayúsculas de impacto y #Shorts)",
  "badge_sub": "Texto secundario del banner superior, ej: CASO REAL | POLICÍA DE GREENVILLE (máx 45 caracteres)",
  "badge_title": "Titular principal del banner superior en mayúsculas, ej: OFICIAL HERIDO EN EMBOSCADA (máx 35 caracteres)",
  "narration_hook": "Frase de enganche para los primeros 3 a 5 segundos dicha por el narrador (en español neutro dramático)",
  "narration_context": "Explicación breve de 1 o 2 oraciones sobre quién es el sospechoso y por qué los agentes intervienen (en español)",
  "narration_outro": "Frase de cierre y llamado a la acción, ej: 'El oficial sobrevivió gracias a su equipo táctico. Suscríbete a Expediente Policial.'",
  "seo_description": "Descripción completa optimizada para YouTube y Meta, con resumen del caso forense y hashtags (#Shorts #ExpedientePolicial #PoliceActivity #CasoReal #Policias)",
  "slice_start": 0,
  "slice_duration": 120
}}
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n", "", text)
            text = re.sub(r"\n```$", "", text)
        return json.loads(text)
    except Exception as e:
        print(f"[Analyzer] Gemini analysis failed: {e}. Falling back to rule-based analyzer.")
        return None

def analyze_rule_based(video_data):
    """
    Robust rule-based analyzer that extracts facts from PoliceActivity title and description.
    """
    title = video_data.get("title", "Intervención Policial de Alto Riesgo")
    desc = video_data.get("description", "")
    duration = video_data.get("duration", 180)
    chapters = video_data.get("chapters", [])
    
    # Location regex: e.g. "Greenville County, South Carolina — On September..."
    loc_match = re.search(r"^([^\n—–\-]+(?:County|City|Department|Parish|Police|State|Town)?[^—–\-]*)", desc)
    location = loc_match.group(1).strip() if loc_match else "ESTADOS UNIDOS"
    # Clean location
    location = re.sub(r"[\*\(\)]", "", location).strip()
    if len(location) > 40:
        location = location[:40].strip()
        
    # Translate / format title to exciting Spanish
    es_title = title
    translations = [
        ("Deputy Gets Shot", "OFICIAL CAE HERIDO"),
        ("Officer Shoots Suspect", "OFICIAL DISPARA A SOSPECHOSO"),
        ("Shootout", "INTENSO TIROTEO"),
        ("During Shootout", "EN PLENO TIROTEO"),
        ("Suspect Opens Fire", "SOSPECHOSO ABRE FUEGO"),
        ("PIT Maneuver", "MANIOBRA PIT A ALTA VELOCIDAD"),
        ("Evades Multiple PIT", "PELIGROSA PERSECUCIÓN Y FUGA"),
        ("Door Breach", "ASALTO TÁCTICO SWAT"),
        ("Aims Flames", "ATAQUE CON FUEGO"),
        ("Hostages", "TOMA DE REHENES"),
        ("Holding Hostages", "REHENES EN PELIGRO"),
    ]
    for en, es in translations:
        if en.lower() in title.lower():
            es_title = title.replace(en, es)
            break
            
    badge_title = "TIROTEO Y RESPUESTA POLICIAL"
    for en, es in translations:
        if en.lower() in title.lower():
            badge_title = es
            break

    badge_sub = f"CASO REAL | {location.upper()}"
    if len(badge_sub) > 45:
        badge_sub = badge_sub[:45]
        
    spanish_title = f"¡{badge_title}! | CASO REAL #Shorts"
    if len(spanish_title) > 90:
        spanish_title = spanish_title[:90]

    # Chapter slice calculation
    # Ignore "Patreon" or "Outro" or "Drone" if other chapters exist
    valid_chapters = [
        c for c in chapters 
        if not any(k in c.get("title", "").lower() for k in ["patreon", "supporter", "outro"])
    ]
    
    slice_start = 0
    slice_duration = min(duration, 125)
    
    if valid_chapters:
        c0 = valid_chapters[0]
        c_dur = c0.get("end_time", duration) - c0.get("start_time", 0)
        if c_dur > 130:
            slice_start = c0.get("start_time", 0) + 5 # Skip intro title card
            slice_duration = 120
        else:
            slice_start = c0.get("start_time", 0)
            slice_duration = min(c_dur, 125)
    else:
        if duration > 140:
            slice_start = 10
            slice_duration = 120
        else:
            slice_start = 0
            slice_duration = duration

    narration_hook = f"Una intervención de rutina que cambió de un segundo a otro en {location}."
    narration_context = "Las cámaras policiales registraron el instante exacto en que los oficiales tuvieron que reaccionar bajo fuego directo."
    narration_outro = "Las investigaciones forenses oficiales determinaron el uso justificado de la fuerza. Suscríbete a Expediente Policial para más casos reales."

    seo_description = f"""Cámara corporal y análisis táctico oficial de los hechos ocurridos en {location}.

📌 Caso: {badge_title}
⚖️ Documentación forense y material de archivo policial de dominio público con fines informativos y educativos.

Suscríbete a Expediente Policial para seguir descubriendo los procedimientos, investigaciones y grabaciones oficiales más impactantes.

#Shorts #ExpedientePolicial #PoliceActivity #CasoReal #Bodycam #Policias #TrueCrime
"""

    return {
        "spanish_title": spanish_title,
        "badge_sub": badge_sub,
        "badge_title": badge_title,
        "narration_hook": narration_hook,
        "narration_context": narration_context,
        "narration_outro": narration_outro,
        "seo_description": seo_description,
        "slice_start": slice_start,
        "slice_duration": slice_duration
    }

def analyze_video(video_data, history_file):
    case_code = determine_case_code(history_file)
    print(f"[Analyzer] Processing case {case_code} for video '{video_data.get('title')}'")
    
    gemini_key = os.environ.get("GEMINI_API_KEY")
    result = None
    if gemini_key:
        print("[Analyzer] GEMINI_API_KEY detected. Requesting AI True Crime generation...")
        result = analyze_with_gemini(gemini_key, video_data)
        
    if not result:
        print("[Analyzer] Generating structured metadata via rule-based engine...")
        result = analyze_rule_based(video_data)
        
    result["case_code"] = case_code
    result["video_id"] = video_data.get("id")
    result["video_url"] = video_data.get("url")
    result["original_title"] = video_data.get("title")
    
    print(f"[Analyzer] Ready: [{case_code}] {result['spanish_title']}")
    print(f"[Analyzer] Target slice: {result['slice_start']}s to {result['slice_start'] + result['slice_duration']}s ({result['slice_duration']}s)")
    return result

if __name__ == "__main__":
    from detector import find_next_candidate
    hist = os.path.join(os.path.dirname(__file__), "..", "data", "processed_history.json")
    cand = find_next_candidate(hist)
    if cand:
        meta = analyze_video(cand, hist)
        print(json.dumps(meta, indent=2, ensure_ascii=False))
