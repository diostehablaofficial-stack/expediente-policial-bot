import os
import re
import json
import requests
import subprocess
import struct
import time

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

def find_optimal_action_window(video_data):
    """
    Intelligently identifies the exact tactical action window:
    1. Checks official YouTube chapters for gunfight/bodycam keywords.
    2. Checks description text for timestamps.
    3. If long video (>120s) with no timestamps, downloads low-bitrate audio in seconds
       and calculates transient peak + RMS density to pinpoint where the shooting/taser/confrontation begins.
    """
    duration = int(video_data.get("duration") or 180)
    chapters = video_data.get("chapters") or []
    
    # 1. Check official chapters
    climax_hint = None
    bodycam_offset = 0
    for ch in chapters:
        t = ch.get("title", "").lower()
        st = int(ch.get("start_time", 0))
        if bodycam_offset == 0 and any(k in t for k in ["bodycam", "dashcam", "officer"]):
            bodycam_offset = st
        if any(k in t for k in ["shoot", "fire", "shots", "attack", "confront", "taser", "k9", "lethal", "board"]):
            if climax_hint is None or st > climax_hint:
                climax_hint = st

    if climax_hint and climax_hint > 35:
        start = max(0.0, float(climax_hint - 35))
        dur = min(85.0, float(duration - start))
        return start, dur, 35.0

    # 2. Check description timestamps
    desc = video_data.get("description", "")
    pattern = re.compile(r'(?:\[|\b)(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\]|\b)\s*[-–—:]?\s*([^\n\r]+)')
    for line in desc.splitlines():
        m = pattern.search(line)
        if m:
            if m.group(1):
                st = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3))
            else:
                st = int(m.group(2))*60 + int(m.group(3))
            t = m.group(4).lower()
            if any(k in t for k in ["shoot", "fire", "shots", "attack", "confront", "taser", "k9", "bodycam"]):
                start = max(0.0, float(st - 35))
                dur = min(85.0, float(duration - start))
                return start, dur, 35.0

    # 3. Audio peak scan for long videos (> 120s)
    vid_id = video_data.get("id", "")
    video_url = video_data.get("url") or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else None)
    if duration > 120 and video_url:
        print("[ActionFinder] Video is long with no chapter markers. Running audio tactical peak analysis...")
        os.makedirs("work", exist_ok=True)
        tmp_audio = os.path.join("work", f"temp_scan_{int(time.time())}.webm")
        cmd = [
            "yt-dlp", "--no-check-certificates",
            "-f", "ba[abr<=64]/ba/worst",
            "-o", tmp_audio,
            video_url
        ]
        if os.path.exists("cookies.txt"):
            cmd.extend(["--cookies", "cookies.txt"])
        try:
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
            if r.returncode == 0 and os.path.exists(tmp_audio):
                proc = subprocess.Popen([
                    "ffmpeg", "-y", "-i", tmp_audio,
                    "-ar", "8000", "-ac", "1", "-f", "s16le", "pipe:1"
                ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                raw, _ = proc.communicate()
                samples = struct.unpack(f"<{len(raw)//2}h", raw)
                rate = 8000
                sec_stats = []
                for i in range(0, len(samples) - rate, rate):
                    chunk = samples[i:i+rate]
                    rms = (sum(s*s for s in chunk) / len(chunk)) ** 0.5
                    peaks = sum(1 for s in chunk if abs(s) > 20000)
                    sec_stats.append((rms, peaks))

                win_len = 75
                best_start = 0
                best_score = -1
                for s_idx in range(0, len(sec_stats) - win_len, 5):
                    sub = sec_stats[s_idx:s_idx+win_len]
                    trans = sum(x[1] for x in sub)
                    rms_avg = sum(x[0] for x in sub) / win_len
                    score = trans * 10 + rms_avg
                    if score > best_score:
                        best_score = score
                        best_start = s_idx

                # Find peak second inside winning window for teaser
                sub_win = sec_stats[best_start:best_start+win_len]
                max_bin = max(range(len(sub_win)), key=lambda i: sub_win[i][1])
                teaser_start = max(5.0, min(float(max_bin), 45.0))

                try:
                    os.remove(tmp_audio)
                except Exception:
                    pass

                slice_dur = min(85.0, float(duration - best_start))
                print(f"[ActionFinder] Pinpointed action: start={best_start}s, dur={slice_dur}s, teaser={teaser_start}s")
                return float(best_start), slice_dur, teaser_start
        except Exception as e:
            print(f"[ActionFinder] Audio scan notice: {e}")
        finally:
            if os.path.exists(tmp_audio):
                try:
                    os.remove(tmp_audio)
                except Exception:
                    pass

    # 4. Fallback for shorter videos
    start = float(bodycam_offset) if bodycam_offset > 0 else (0.0 if duration <= 120 else 25.0)
    dur = min(85.0, float(duration - start))
    return start, dur, 20.0

def build_prompt(video_data, optimal_window=None):
    clean_desc = clean_description(video_data.get("description", ""))
    duration = int(video_data.get("duration", 180))
    chapters = video_data.get("chapters") or []
    
    if optimal_window:
        suggested_start, slice_dur, teaser_start = optimal_window
    else:
        suggested_start, slice_dur, teaser_start = find_optimal_action_window(video_data)
        
    chapters_formatted = []
    for ch in chapters:
        t = ch.get("title", "")
        st = int(ch.get("start_time", 0))
        chapters_formatted.append(f"- {st}s ({st//60}:{st%60:02d}): {t}")
    chapters_text = "\n".join(chapters_formatted) if chapters_formatted else "Sin marcas de capítulo en el video original."

    prompt = f"""Eres el director audiovisual y guionista forense de 'Expediente Policial' (canal de documentales True Crime de alta producción en español).
Analiza este caso policial real de PoliceActivity:

Título original: {video_data.get('title')}
Duración total: {duration} segundos
Capítulos del video:
{chapters_text}

Descripción de los hechos:
{clean_desc[:3500]}

REGLAS DE ORO DEL MONTAJE:
1. SELECCIÓN DEL CORTE EXACTO ('slice_start' y 'slice_duration'):
   - Análisis acústico y táctico verificado: La confrontación real y los hechos críticos ocurren entre los segundos {suggested_start:.0f} y {suggested_start + slice_dur:.0f}.
   - Usa EXACTAMENTE: slice_start={suggested_start:.0f}, slice_duration={slice_dur:.0f}.
   - El objetivo es mostrar la acción directa con precisión absoluta, sin tomas vacías ni traslados previos.

2. GANCHO 'A CONTINUACIÓN...' ('teaser_start' y 'teaser_duration'):
   - 'teaser_start': {teaser_start:.1f} (segundo exacto relativo dentro del corte donde ocurre el momento más visual e impactante).
   - 'teaser_duration': 3.5.

3. NARRACIÓN MILIMÉTRICAMENTE SINCRONIZADA ('narrations'):
   - Exactamente 5 intervenciones concisas y periodísticas en español neutro.
   - 'start': segundo exacto dentro del corte donde la voz empieza (ej: 1.0, 14.0, 32.0, 52.0, 72.0).
   - Cada frase DEBE describir con total veracidad y exactitud lo que se está viendo en pantalla en ese momento preciso.

4. BANNERS Y TÍTULOS:
   - 'spanish_title': Título impactante en mayúsculas (máximo 80 caracteres), con #Shorts.
   - 'badge_sub': "CASO REAL | [DEPARTAMENTO POLICIAL / CIUDAD]" (máx 40 caracteres).
   - 'badge_title': Titular principal en mayúsculas (máx 35 caracteres, ej. "TIROS TRAS TASEO EN LA CERCA").
   - 'seo_description': Resumen forense completo con hashtags (#ExpedientePolicial #CasoReal #Dashcam #Bodycam #Shorts #Reels #Policias).

Devuelve ÚNICAMENTE un objeto JSON válido (sin backticks markdown ```json, solo las llaves {{...}}):
{{
  "spanish_title": "¡TÍTULO IMPACTANTE! | CASO REAL #Shorts",
  "badge_sub": "CASO REAL | POLICÍA DE...",
  "badge_title": "TITULAR DEL SUCESO",
  "seo_description": "Cámara corporal y de patrulla...\\n\\n#ExpedientePolicial #CasoReal #Bodycam #Shorts",
  "slice_start": {suggested_start:.0f},
  "slice_duration": {slice_dur:.0f},
  "teaser_start": {teaser_start:.1f},
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

def analyze_with_groq(api_key, video_data, optimal_window=None):
    """
    Uses Groq (ultra-fast Llama/OpenAI-compatible models) to generate metadata.
    """
    prompt, suggested_start, slice_dur = build_prompt(video_data, optimal_window)
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
                if "```" in raw_txt:
                    raw_txt = re.sub(r"^```(?:json)?\s*", "", raw_txt, flags=re.MULTILINE)
                    raw_txt = re.sub(r"\s*```$", "", raw_txt, flags=re.MULTILINE)
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

def analyze_with_gemini(api_key, video_data, optimal_window=None):
    """
    Uses Gemini API (1.5 Flash / 2.0 Flash) to generate metadata.
    """
    prompt, suggested_start, slice_dur = build_prompt(video_data, optimal_window)
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

def analyze_rule_based(video_data, optimal_window=None):
    title = video_data.get("title", "Intervención Policial de Alto Riesgo")
    desc = clean_description(video_data.get("description", ""))
    duration = int(video_data.get("duration", 180))
    
    if optimal_window:
        slice_start, slice_dur, teaser_start = optimal_window
    else:
        slice_start, slice_dur, teaser_start = find_optimal_action_window(video_data)

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
    elif "taser" in title.lower():
        badge_title = "TASEO Y ENFRENTAMIENTO ARMADO"
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
        "teaser_start": teaser_start,
        "teaser_duration": 3.5,
        "narrations": narrations
    }

def analyze_video(video_data, history_file):
    case_code = determine_case_code(history_file)
    print(f"[Analyzer] Processing case {case_code} for '{video_data.get('title')}'")
    
    # 1. Pre-calculate optimal tactical action window
    opt_start, opt_dur, opt_teaser = find_optimal_action_window(video_data)
    optimal_window = (opt_start, opt_dur, opt_teaser)
    
    result = None
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if groq_key:
        print("[Analyzer] GROQ_API_KEY detected. Running AI True Crime script generation...")
        result = analyze_with_groq(groq_key, video_data, optimal_window)
        
    if not result and gemini_key:
        print("[Analyzer] Running Gemini AI script generation...")
        result = analyze_with_gemini(gemini_key, video_data, optimal_window)
        
    if not result:
        print("[Analyzer] Falling back to intelligent rule-based engine...")
        result = analyze_rule_based(video_data, optimal_window)
        
    # Enforce verified tactical window so the final cut never shows empty highway driving
    result["slice_start"] = opt_start
    result["slice_duration"] = opt_dur
    if not result.get("teaser_start") or result["teaser_start"] < 5.0 or result["teaser_start"] > opt_dur - 4.0:
        result["teaser_start"] = opt_teaser

    result["case_code"] = case_code
    result["video_id"] = video_data.get("id")
    result["video_url"] = video_data.get("url") or f"https://www.youtube.com/watch?v={video_data.get('id')}"
    result["original_title"] = video_data.get("title")
    result["teaser_duration"] = 3.5

    print(f"[Analyzer] Ready: [{case_code}] {result['spanish_title']}")
    print(f"[Analyzer] Badge Sub: {result['badge_sub']} | Badge Title: {result['badge_title']}")
    print(f"[Analyzer] Slice: start={result['slice_start']}s, dur={result['slice_duration']}s | Teaser: {result['teaser_start']}s")
    return result
