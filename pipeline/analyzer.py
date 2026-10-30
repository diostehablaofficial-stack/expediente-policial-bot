import os
import re
import json
import requests

def determine_case_code(history_file):
    """
    Returns e.g. 'EXP_020' based on existing history count.
    """
    count = 19
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
        ("San Diego, California", "San Diego, California"),
        ("San Diego", "San Diego, California"),
        ("New York", "Nueva York"),
        ("New Mexico", "Nuevo México"),
        ("Michigan", "Michigan"),
        ("Connecticut", "Connecticut"),
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
        if any(bad in l_str.lower() for bad in ["disclaimer", "patreon", "support us", "educational", "informational", "purposes only", "subscribe", "youtube", "merch"]):
            continue
        cleaned_lines.append(l_str)
    return "\n".join(cleaned_lines)

def build_prompt(video_data):
    clean_desc = clean_description(video_data.get("description", ""))
    duration = int(video_data.get("duration", 180))
    chapters = video_data.get("chapters", [])
    
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
        if any(k in t_lower for k in ["shoot", "fire", "shots", "attack", "confront", "k9", "flame", "lethal", "board"]):
            if climax_hint is None or st > climax_hint:
                climax_hint = st
                
    chapters_text = "\n".join(chapters_formatted) if chapters_formatted else "Sin marcas de capítulo en el video original."
    
    if duration <= 120:
        suggested_start = bodycam_offset if bodycam_offset > 0 else 0
        slice_dur = min(duration - suggested_start, 95)
    else:
        if climax_hint and climax_hint > 35:
            suggested_start = max(0, climax_hint - 40)
        else:
            suggested_start = max(bodycam_offset, 25)
        slice_dur = min(92, max(75, duration - suggested_start))

    prompt = f"""Eres el director audiovisual y guionista forense de 'Expediente Policial' (canal de documentales True Crime de alta producción en español).
Analiza este caso policial real de PoliceActivity:

Título original: {video_data.get('title')}
Duración total: {duration} segundos
Capítulos del video:
{chapters_text}

Descripción de los hechos:
{clean_desc[:3500]}

REGLAS DE ORO DEL MONTAJE:
1. SELECCIÓN DEL CORTE ('slice_start' y 'slice_duration'):
   - El segmento principal debe durar entre 80 y 95 segundos continuos.
   - Debe abarcar toda la historia: aproximación inicial, escalada del conflicto, clímax de máxima acción (tiroteo/embestida/enfrentamiento armado) y resolución/arresto.
   - Sugerencia calculada: slice_start={suggested_start}, slice_duration={slice_dur}.

2. GANCHO 'A CONTINUACIÓN...' ('teaser_start' y 'teaser_duration'):
   - 'teaser_start': segundo exacto relativo dentro del corte (entre 5.0 y 45.0) donde ocurre la acción más impactante y visual (ej. el primer disparo o embestida).
   - 'teaser_duration': 3.5.

3. NARRACIÓN SINCRONIZADA ('narrations'):
   - Exactamente 5 intervenciones concisas y periodísticas en español neutro.
   - 'start': segundo exacto dentro del corte donde la voz empieza (ej: 1.0, 14.0, 32.0, 52.0, 72.0).
   - Cada frase describe estrictamente lo que se ve en pantalla en ese momento.

4. BANNERS Y TÍTULOS:
   - 'spanish_title': Título impactante en mayúsculas (máximo 80 caracteres), con #Shorts.
   - 'badge_sub': "CASO REAL | [DEPARTAMENTO POLICIAL / CIUDAD]" (máx 40 caracteres).
   - 'badge_title': Titular principal en mayúsculas (máx 35 caracteres, ej. "TIROTEO EN VELERO ROBADO").
   - 'seo_description': Resumen forense completo con hashtags (#ExpedientePolicial #CasoReal #Dashcam #Bodycam #Shorts #Reels #Policias).

Devuelve ÚNICAMENTE un objeto JSON válido (sin backticks markdown ```json, solo las llaves {{...}}):
{{
  "spanish_title": "¡TÍTULO IMPACTANTE! | CASO REAL #Shorts",
  "badge_sub": "CASO REAL | POLICÍA DE...",
  "badge_title": "TITULAR DEL SUCESO",
  "seo_description": "Cámara corporal y de patrulla...\\n\\n#ExpedientePolicial #CasoReal #Bodycam #Shorts",
  "slice_start": {suggested_start},
  "slice_duration": {slice_dur},
  "teaser_start": 20.0,
  "teaser_duration": 3.5,
  "narrations": [
    {{"id": "narr_01", "start": 1.0, "text": "Texto apertura..."}},
    {{"id": "narr_02", "start": 15.0, "text": "Texto conflicto..."}},
    {{"id": "narr_03", "start": 35.0, "text": "Texto acción..."}},
    {{"id": "narr_04", "start": 52.0, "text": "Texto clímax..."}},
    {{"id": "narr_05", "start": 72.0, "text": "Resolución y llamado a suscribirse a Expediente Policial."}}
  ]
}}"""
    return prompt, suggested_start, slice_dur

def analyze_with_groq(api_key, video_data):
    """
    Uses Groq (ultra-fast Llama/OpenAI-compatible models) to generate metadata.
    """
    prompt, suggested_start, slice_dur = build_prompt(video_data)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    models = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
    
    for mod in models:
        try:
            payload = {
                "model": mod,
                "messages": [
                    {"role": "system", "content": "Eres un asistente que responde ÚNICAMENTE con código JSON válido y nada más."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 1500
            }
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=25)
            if r.status_code == 200:
                raw_txt = r.json()["choices"][0]["message"]["content"].strip()
                # Clean possible markdown wrapping
                if "```" in raw_txt:
                    raw_txt = re.sub(r"^```(?:json)?\s*", "", raw_txt, flags=re.MULTILINE)
                    raw_txt = re.sub(r"\s*```$", "", raw_txt, flags=re.MULTILINE)
                # Parse JSON
                # Find outermost braces
                start_i = raw_txt.find("{")
                end_i = raw_txt.rfind("}")
                if start_i != -1 and end_i != -1:
                    data = json.loads(raw_txt[start_i:end_i+1])
                    print(f"[Analyzer] Groq ({mod}) successfully generated True Crime metadata!")
                    return data
            else:
                print(f"[Analyzer] Groq {mod} failed: {r.status_code} - {r.text[:120]}")
        except Exception as e:
            print(f"[Analyzer] Groq exception with {mod}: {e}")
            
    return None

def analyze_with_gemini(api_key, video_data):
    """
    Uses Gemini API (1.5 Flash / 2.0 Flash) to generate metadata.
    """
    prompt, suggested_start, slice_dur = build_prompt(video_data)
    models = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3}
    }
    for mod in models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={api_key}"
            r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                if "```" in text:
                    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
                    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
                start_i = text.find("{")
                end_i = text.rfind("}")
                if start_i != -1 and end_i != -1:
                    data = json.loads(text[start_i:end_i+1])
                    print(f"[Analyzer] Gemini ({mod}) successfully generated metadata!")
                    return data
        except Exception as e:
            print(f"[Analyzer] Gemini exception with {mod}: {e}")
            
    return None

def analyze_rule_based(video_data):
    title = video_data.get("title", "Intervención Policial de Alto Riesgo")
    desc = clean_description(video_data.get("description", ""))
    duration = int(video_data.get("duration", 180))
    
    slice_start = 25.0 if duration > 100 else 0.0
    slice_dur = min(92.0, max(75.0, duration - slice_start))
    
    loc_match = re.search(r"^([^\n—–\-]+(?:County|City|Department|Parish|Police|State|Town)?[^—–\-]*)", desc)
    raw_loc = loc_match.group(1).strip() if loc_match else "ESTADOS UNIDOS"
    location = clean_location(raw_loc)
    if len(location) > 35:
        location = location[:35].strip()

    badge_title = "INTERVENCIÓN ARMADA Y PERSECUCIÓN"
    if "boat" in title.lower() or "sailboat" in title.lower():
        badge_title = "ABORDAJE Y TIROTEO EN VELERO"
    elif "shot" in title.lower() or "fire" in title.lower():
        badge_title = "TIROTEO CONTRA OFICIALES"
    elif "ram" in title.lower() or "pond" in title.lower():
        badge_title = "EMBESTIDA Y VUELCO DE FUGITIVO"
        
    badge_sub = f"CASO REAL | {location.upper()}"
    if len(badge_sub) > 40:
        badge_sub = badge_sub[:40]
        
    spanish_title = f"¡{badge_title}! | CASO REAL #Shorts"
    
    narrations = [
        {"id": "narr_01", "start": 1.0, "text": f"Una peligrosa intervención táctica se desata en {location}."},
        {"id": "narr_02", "start": 14.0, "text": "Los oficiales avanzan para cercar al sospechoso y ordenan que se rinda."},
        {"id": "narr_03", "start": 34.0, "text": "¡De imprevisto el sujeto abre fuego contra los agentes a quemarropa!"},
        {"id": "narr_04", "start": 54.0, "text": "Los policías responden a los disparos y aseguran el perímetro bajo fuego cruzado."},
        {"id": "narr_05", "start": 74.0, "text": "La amenaza es neutralizada y el agresor puesto bajo custodia. Suscríbete a Expediente Policial."}
    ]

    seo_description = f"""Cámara corporal y análisis táctico oficial de los hechos ocurridos en {location}.
🚨 Caso Real: {badge_title}.
⚖️ Material de archivo policial oficial con fines informativos y educativos.

#ExpedientePolicial #CasoReal #Dashcam #Bodycam #Shorts #Reels #Policias #CasoPolicial
"""
    return {
        "spanish_title": spanish_title,
        "badge_sub": badge_sub,
        "badge_title": badge_title,
        "seo_description": seo_description,
        "slice_start": slice_start,
        "slice_duration": slice_dur,
        "teaser_start": 20.0,
        "teaser_duration": 3.5,
        "narrations": narrations
    }

def analyze_video(video_data, history_file):
    case_code = determine_case_code(history_file)
    print(f"[Analyzer] Processing case {case_code} for '{video_data.get('title')}'")
    
    result = None
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if groq_key:
        print("[Analyzer] GROQ_API_KEY detected. Running AI True Crime script generation...")
        result = analyze_with_groq(groq_key, video_data)
        
    if not result and gemini_key:
        print("[Analyzer] Running Gemini AI script generation...")
        result = analyze_with_gemini(gemini_key, video_data)
        
    if not result:
        print("[Analyzer] Falling back to intelligent rule-based engine...")
        result = analyze_rule_based(video_data)
        
    result["case_code"] = case_code
    result["video_id"] = video_data.get("id")
    result["video_url"] = video_data.get("url") or f"https://www.youtube.com/watch?v={video_data.get('id')}"
    result["original_title"] = video_data.get("title")
    
    # Ensure teaser_start is valid
    try:
        t_start = float(result.get("teaser_start", 20.0))
        s_dur = float(result.get("slice_duration", 92.0))
        if t_start > s_dur - 4.0 or t_start < 0:
            result["teaser_start"] = 20.0
    except Exception:
        result["teaser_start"] = 20.0
    result["teaser_duration"] = 3.5

    print(f"[Analyzer] Ready: [{case_code}] {result['spanish_title']}")
    print(f"[Analyzer] Badge Sub: {result['badge_sub']} | Badge Title: {result['badge_title']}")
    print(f"[Analyzer] Slice: start={result['slice_start']}s, dur={result['slice_duration']}s | Teaser: {result['teaser_start']}s")
    return result
