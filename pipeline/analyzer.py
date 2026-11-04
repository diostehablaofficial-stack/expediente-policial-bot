import os
import re
import json
import requests
import subprocess
import struct
import time
import base64

ACTION_KEYWORDS = [
    "shoot", "fire", "shots", "gunfire", "gunshot", "shootout",
    "attack", "confront", "taser", "k9", "lethal", "pursuit",
    "chase", "crash", "ram", "breach", "standoff", "hostage",
    "stab", "knife", "armed", "draws", "unholster", "flee"
]

def determine_case_code(history_file):
    """
    Returns e.g. 'EXP_025' based on existing history count.
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
    1. Checks official YouTube chapters for explicit gunfight/tactical action keywords.
    2. Checks description text for timestamps matching action keywords.
    3. Scans low-bitrate audio for gunshot bursts and acoustic transients (crest factor).
    4. If multi-officer bodycam video, aligns window to the active confrontation camera.
    """
    duration = int(video_data.get("duration") or 180)
    chapters = video_data.get("chapters") or []

    def clamp_window(start, teaser, dur_total):
        dur_total = float(dur_total)
        if dur_total <= 60.0:
            return 0.0, dur_total, max(1.0, dur_total / 2.0)
        max_start = max(0.0, dur_total - 45.0)
        safe_start = max(0.0, min(float(start), max_start))
        safe_dur = max(45.0, min(75.0, dur_total - safe_start))
        safe_teaser = max(5.0, min(float(teaser), safe_dur - 4.0))
        return safe_start, safe_dur, safe_teaser
    
    # 1. Check official chapters for explicit action keywords
    climax_hint = None
    officer_chapters = []
    for ch in chapters:
        t = ch.get("title", "").lower()
        st = int(ch.get("start_time", 0))
        if st >= duration - 15:
            continue
        if any(k in t for k in ["officer", "bodycam", "dashcam"]) and not any(k in t for k in ["patreon", "support", "credit"]):
            officer_chapters.append((st, ch.get("title", "")))
        if any(k in t for k in ACTION_KEYWORDS):
            if climax_hint is None or st > climax_hint:
                climax_hint = st

    if climax_hint and climax_hint > 20:
        start = max(0.0, float(climax_hint - 20))
        teaser = min(20.0, float(climax_hint - start))
        return clamp_window(start, teaser, duration)

    # 2. Check description timestamps for explicit action keywords (NOT "bodycam" or "officer"!)
    desc = video_data.get("description", "")
    pattern = re.compile(r'^\s*(?:\[|\()?(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\]|\))?\s*[-–—:]?\s*(.+)$', re.IGNORECASE)
    for line in desc.splitlines():
        line_clean = line.strip()
        if re.search(r'\b(?:am|pm|a\.m\.|p\.m\.)\b', line_clean, re.IGNORECASE):
            continue
        m = pattern.match(line_clean)
        if m:
            if m.group(3):
                st = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3))
            else:
                st = int(m.group(1))*60 + int(m.group(2))
            if st >= duration - 15 or st < 0:
                continue
            t = m.group(4).lower()
            if any(k in t for k in ACTION_KEYWORDS):
                start = max(0.0, float(st - 20))
                teaser = min(20.0, float(st - start))
                return clamp_window(start, teaser, duration)

    # 3. Audio gunshot & transient burst scan for videos > 120s
    vid_id = video_data.get("id", "")
    video_url = video_data.get("url") or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else None)
    if duration > 120 and video_url:
        print("[ActionFinder] Scanning audio for tactical peak/gunshot burst analysis...")
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
        if os.name != "nt":
            cmd.extend([
                "--extractor-args", "youtube:player_client=mweb,tv,web",
                "--extractor-args", "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416"
            ])
        else:
            cmd.extend(["--extractor-args", "youtube:player_client=tv,android,web"])
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
                sec_scores = []
                for i in range(0, len(samples) - rate, rate):
                    chunk = samples[i:i+rate]
                    rms = (sum(s*s for s in chunk) / len(chunk)) ** 0.5
                    peak_max = max(abs(s) for s in chunk)
                    peaks_24k = sum(1 for s in chunk if abs(s) > 24000)
                    crest = peak_max / (rms + 1e-5)
                    # Transient burst score distinguishes brief gunshots from sustained sirens
                    burst_score = (peaks_24k ** 1.2) * (crest ** 1.5)
                    sec_scores.append((i // rate, burst_score, peaks_24k, peak_max, rms))

                # Priority 1: Multi-officer bodycam videos. In these videos, the confrontation
                # always occurs in Officer 1's camera right before Officer 2's chapter starts.
                if len(officer_chapters) >= 2:
                    ch2_st = officer_chapters[1][0]
                    search_min = max(0, ch2_st - 60)
                    search_max = min(duration, ch2_st + 10)
                    officer1_bursts = [x for x in sec_scores if search_min <= x[0] <= search_max]
                    if officer1_bursts:
                        best_burst = max(officer1_bursts, key=lambda x: x[1])
                        burst_peak_abs = best_burst[0]
                        best_start = max(0.0, float(burst_peak_abs - 30.0))
                        teaser_start = max(5.0, min(float(burst_peak_abs - best_start), 35.0))
                        print(f"[ActionFinder] Multi-officer confrontation pinpoint: burst at {burst_peak_abs}s, start={best_start}s, teaser={teaser_start}s")
                        return clamp_window(best_start, teaser_start, duration)

                # Priority 2: Standard single-officer video transient peak
                # Filter out sustained sirens (where rms > 7000 over many seconds) and find peak burst
                filtered_bursts = [x for x in sec_scores if x[4] < 7500 or x[1] > 300]
                if filtered_bursts:
                    top_burst = max(filtered_bursts, key=lambda x: x[1])
                    burst_peak_abs = top_burst[0]
                    best_start = max(0.0, float(burst_peak_abs - 25.0))
                    teaser_start = max(5.0, min(float(burst_peak_abs - best_start), 35.0))
                    print(f"[ActionFinder] Acoustic transient pinpoint: burst at {burst_peak_abs}s, start={best_start}s, teaser={teaser_start}s")
                    return clamp_window(best_start, teaser_start, duration)

                win_len = 75
                best_start = 0
                best_score = -1
                for s_idx in range(0, len(sec_scores) - win_len, 5):
                    sub = sec_scores[s_idx:s_idx+win_len]
                    w_score = sum(x[1] for x in sub)
                    if w_score > best_score:
                        best_score = w_score
                        best_start = s_idx

                sub_win = sec_scores[best_start:best_start+win_len]
                max_sub = max(sub_win, key=lambda x: x[1])
                burst_peak_abs = max_sub[0]
                teaser_start = max(5.0, min(float(burst_peak_abs - best_start), 40.0))
                print(f"[ActionFinder] Audio window pinpoint: start={best_start}s, teaser={teaser_start}s")
                return clamp_window(best_start, teaser_start, duration)
        except Exception as e:
            print(f"[ActionFinder] Audio scan notice: {e}")
        finally:
            if os.path.exists(tmp_audio):
                try:
                    os.remove(tmp_audio)
                except Exception:
                    pass

    # 4. Fallback for multi-officer chapters: pick the last active officer before credits
    if len(officer_chapters) >= 2:
        last_ch_st, last_ch_name = officer_chapters[-1]
        print(f"[ActionFinder] Chapter fallback: picking final active officer camera '{last_ch_name}' at {last_ch_st}s")
        return clamp_window(last_ch_st, 20.0, duration)

    # 5. Default fallback
    start = 0.0 if duration <= 90 else 25.0
    return clamp_window(start, 20.0, duration)

def extract_frame_base64(video_path, timestamp_sec):
    """
    Extracts a JPEG frame at timestamp_sec from video_path scaled to 640px and returns base64 string.
    """
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{timestamp_sec:.2f}",
        "-i", video_path,
        "-vframes", "1",
        "-vf", "scale=640:-1",
        "-q:v", "3",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "pipe:1"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    img_bytes, _ = proc.communicate()
    if img_bytes and len(img_bytes) > 500:
        return base64.b64encode(img_bytes).decode("utf-8")
    return None

def build_prompt(video_data, optimal_window=None, dynamic_timestamps=None):
    clean_desc = clean_description(video_data.get("description", ""))
    duration = int(video_data.get("duration", 180))
    chapters = video_data.get("chapters") or []
    
    if optimal_window:
        suggested_start, slice_dur, teaser_start = optimal_window
    else:
        suggested_start, slice_dur, teaser_start = find_optimal_action_window(video_data)

    if not dynamic_timestamps:
        t1 = 1.0
        t2 = max(8.0, teaser_start - 6.0)
        t3 = teaser_start
        t4 = min(teaser_start + 16.0, slice_dur - 14.0)
        t5 = slice_dur - 7.0
    else:
        t1, t2, t3, t4, t5 = dynamic_timestamps
        
    chapters_formatted = []
    for ch in chapters:
        t = ch.get("title", "")
        st = int(ch.get("start_time", 0))
        chapters_formatted.append(f"- {st}s ({st//60}:{st%60:02d}): {t}")
    chapters_text = "\n".join(chapters_formatted) if chapters_formatted else "Sin marcas de capítulo en el video original."

    prompt = f"""Eres el director audiovisual y guionista forense de 'Expediente Policial' (documentales True Crime policiales en español neutro).
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
   - 'teaser_start': {teaser_start:.1f} (momento exacto relativo dentro del corte donde ocurre el clímax visual de la acción).
   - 'teaser_duration': 3.5.

2. NARRACIÓN MILIMÉTRICAMENTE SINCRONIZADA CON LA PANTALLA:
   - Exactamente 5 intervenciones periodísticas concisas en español neutro (entre 12 y 18 palabras cada una).
   - Los timestamps de inicio DEBEN ser exactamente: [{t1:.1f}, {t2:.1f}, {t3:.1f}, {t4:.1f}, {t5:.1f}].
   - {t1:.1f}s: Aproximación táctica inicial de los oficiales al lugar de los hechos.
   - {t2:.1f}s: Despliegue de armas, órdenes policiales y preparación previa al contacto directo.
   - {t3:.1f}s: EL CLÍMAX VISUAL EXACTO (disparos, taseo, forcejeo, impacto o emboscada).
   - {t4:.1f}s: Respuesta policial inmediata, repliegue bajo fuego cruzado y cobertura.
   - {t5:.1f}s: Control de la amenaza, auxilio médico e invitación a suscribirse a Expediente Policial.

3. BANNERS Y TÍTULOS:
   - 'spanish_title': Título impactante en mayúsculas (máximo 80 caracteres), con #Shorts.
   - 'badge_sub': "CASO REAL | [DEPARTAMENTO POLICIAL / CIUDAD]" (máx 40 caracteres).
   - 'badge_title': Titular principal en mayúsculas (máx 35 caracteres, debe reflejar fielmente el suceso real, ej. "DISPAROS CONTRA LA PATRULLA", sin inventar datos).
   - 'seo_description': Resumen forense completo con hashtags (#ExpedientePolicial #CasoReal #Dashcam #Bodycam #Shorts).

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
    {{"id": "narr_01", "start": {t1:.1f}, "text": "Texto aproximación inicial..."}},
    {{"id": "narr_02", "start": {t2:.1f}, "text": "Texto desenfunde y órdenes policiales..."}},
    {{"id": "narr_03", "start": {t3:.1f}, "text": "Texto momento crítico de disparos o acción..."}},
    {{"id": "narr_04", "start": {t4:.1f}, "text": "Texto oficiales bajo fuego y repliegue..."}},
    {{"id": "narr_05", "start": {t5:.1f}, "text": "Resolución y llamado a suscribirse a Expediente Policial."}}
  ]
}}"""
    return prompt, suggested_start, slice_dur

def analyze_with_gemini_vision(api_key, video_data, optimal_window, frames_b64, timestamps):
    """
    Multimodal Vision script generator: Inspects the 5 actual video frames of the cut
    and writes 5 narrations describing exactly what is on screen at each timestamp.
    """
    suggested_start, slice_dur, teaser_start = optimal_window
    clean_desc = clean_description(video_data.get("description", ""))
    t1, t2, t3, t4, t5 = timestamps

    prompt = f"""Eres el director audiovisual y guionista forense de 'Expediente Policial' (documentales True Crime policiales en español neutro).
Analiza este caso policial real de PoliceActivity:
Título original: {video_data.get('title')}
Descripción del caso:
{clean_desc[:2500]}

Tienes adjuntos 5 FOTOGRAMAS REALES del video extraídos en los segundos exactos:
- Fotograma 1: {t1:.1f}s (Aproximación inicial)
- Fotograma 2: {t2:.1f}s (Llegada al punto crítico)
- Fotograma 3: {t3:.1f}s (Momento de máxima acción / disparos / confrontación)
- Fotograma 4: {t4:.1f}s (Reacción táctica / cobertura / heridos)
- Fotograma 5: {t5:.1f}s (Desenlace / control del área)

REGLAS DE SINCRONIZACIÓN VISUAL OBLIGATORIA:
1. CADA FRASE DEBE DESCRIBIR CON EXACTITUD LO QUE SE OBSERVA EN SU FOTOGRAMA CORRESPONDIENTE.
   - En la frase 1 ({t1:.1f}s), describe exactamente la acción del Fotograma 1.
   - En la frase 2 ({t2:.1f}s), describe exactamente lo que ocurre en el Fotograma 2.
   - En la frase 3 ({t3:.1f}s), narra la confrontación crítica visible en el Fotograma 3.
   - En la frase 4 ({t4:.1f}s), narra la situación visible en el Fotograma 4.
   - En la frase 5 ({t5:.1f}s), resume el desenlace visible en el Fotograma 5 e invita a suscribirse a Expediente Policial.
2. Cada frase debe tener entre 12 y 18 palabras en español neutro, tono periodístico y forense.
3. El arreglo 'narrations' DEBE tener exactamente 5 elementos con 'start' fijados en [{t1:.1f}, {t2:.1f}, {t3:.1f}, {t4:.1f}, {t5:.1f}].

Devuelve un JSON con:
- spanish_title (máx 80 caracteres con #Shorts)
- badge_sub (CASO REAL | [CIUDAD/POLICÍA])
- badge_title (titular en mayúsculas máx 35 caracteres)
- seo_description (resumen forense con hashtags)
- slice_start: {suggested_start:.0f}
- slice_duration: {slice_dur:.0f}
- teaser_start: {teaser_start:.1f}
- teaser_duration: 3.5
- narrations: lista de 5 objetos con id, start y text
"""
    parts = [{"text": prompt}]
    for b64 in frames_b64:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": b64
            }
        })

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.2,
            "response_mime_type": "application/json"
        }
    }

    models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
    for mod in models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={api_key}"
            r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=45)
            if r.status_code == 200:
                raw_json = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                data = json.loads(raw_json)
                print(f"[Analyzer] Gemini Vision ({mod}) generated perfectly vision-grounded script!")
                return data
            else:
                print(f"[Analyzer] Gemini Vision ({mod}) failed: {r.status_code} - {r.text[:120]}")
        except Exception as e:
            print(f"[Analyzer] Gemini Vision error with {mod}: {e}")

    return None

def analyze_with_groq(api_key, video_data, optimal_window=None, dynamic_timestamps=None):
    """
    Uses Groq (ultra-fast Llama/OpenAI-compatible models) to generate metadata.
    """
    prompt, suggested_start, slice_dur = build_prompt(video_data, optimal_window, dynamic_timestamps)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    
    for mod in models:
        try:
            payload = {
                "model": mod,
                "messages": [
                    {"role": "system", "content": "Eres un asistente que responde ÚNICAMENTE con código JSON válido y nada más."},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
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

def analyze_with_gemini(api_key, video_data, optimal_window=None, dynamic_timestamps=None):
    """
    Uses Gemini API (2.0 Flash / 1.5 Flash) text endpoint.
    """
    prompt, suggested_start, slice_dur = build_prompt(video_data, optimal_window, dynamic_timestamps)
    models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
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

def analyze_rule_based(video_data, optimal_window=None, dynamic_timestamps=None):
    title = video_data.get("title", "Intervención Policial de Alto Riesgo")
    desc = clean_description(video_data.get("description", ""))
    duration = int(video_data.get("duration", 180))
    
    if optimal_window:
        slice_start, slice_dur, teaser_start = optimal_window
    else:
        slice_start, slice_dur, teaser_start = find_optimal_action_window(video_data)

    if not dynamic_timestamps:
        t1 = 1.0
        t2 = max(8.0, teaser_start - 6.0)
        t3 = teaser_start
        t4 = min(teaser_start + 16.0, slice_dur - 14.0)
        t5 = slice_dur - 7.0
    else:
        t1, t2, t3, t4, t5 = dynamic_timestamps

    loc_match = re.search(r"^([^\n—–\-]+(?:County|City|Department|Parish|Police|State|Town)?[^—–\-]*)", desc)
    raw_loc = loc_match.group(1).strip() if loc_match else "ESTADOS UNIDOS"
    location = clean_location(raw_loc)
    if len(location) > 35:
        location = location[:35].strip()

    desc_low = desc.lower()
    title_low = title.lower()
    full_text = f"{title_low} {desc_low}"

    # Determine weapon and threat context dynamically
    is_rod = any(w in full_text for w in ["metal rod", "metal rods", "rod", "pipe", "metal pipe", "crowbar", "bat", "blunt object"])
    is_blade = any(w in full_text for w in ["knife", "machete", "axe", "blade", "stab", "edged weapon", "dagger"])
    is_vehicle = any(w in full_text for w in ["ram", "rammed", "vehicle", "car chase", "pursuit", "crash", "pond"])
    is_firearm = any(w in full_text for w in ["shoot", "shots", "shot", "gunfire", "handgun", "pistol", "revolver", "rifle", "firearm", "opened fire", "fired"])

    if "boat" in title_low or "sailboat" in title_low:
        badge_title = "ABORDAJE Y TIROTEO EN VELERO"
        action_text_3 = "¡Los oficiales abordan la embarcación y son recibidos con fuego letal inmediato!"
        action_text_4 = "Los agentes devuelven los disparos y toman cobertura en la cubierta del velero."
    elif is_rod:
        badge_title = "ATAQUE CON VARILLAS METÁLICAS"
        action_text_3 = "¡El sospechoso arremete armado con varillas metálicas amenazando la vida de los oficiales!"
        action_text_4 = "Los agentes despliegan medidas de fuerza defensiva retrocediendo para evitar ser golpeados."
    elif is_blade:
        badge_title = "AGRESIÓN CON ARMA BLANCA"
        action_text_3 = "¡El sospechoso se abalanza empuñando un arma blanca desafiando las órdenes letales!"
        action_text_4 = "Los oficiales abren fuego defensivo para neutralizar el avance inminente del agresor."
    elif is_vehicle:
        badge_title = "EMBESTIDA Y PERSECUCIÓN POLICIAL"
        action_text_3 = "¡El sospechoso acelera a fondo e impacta deliberadamente contra las patrullas policiales!"
        action_text_4 = "Las unidades cercan el vehículo accidentado y extraen al conductor bajo custodia táctica."
    elif is_firearm:
        badge_title = "TIROTEO CONTRA OFICIALES"
        action_text_3 = "¡De imprevisto el sospechoso desenfunda un arma de fuego y dispara a quemarropa!"
        action_text_4 = "Los oficiales responden de inmediato al fuego y toman cobertura tras sus patrullas."
    elif "taser" in title_low:
        badge_title = "DESPLIEGUE TÁCTICO Y TASEO"
        action_text_3 = "¡El sujeto desobedece las órdenes y los oficiales despliegan descargas de taser para frenarlo!"
        action_text_4 = "Los agentes aseguran al sospechoso en el suelo neutralizando la resistencia física."
    else:
        badge_title = "INTERVENCIÓN POLICIAL DE ALTO RIESGO"
        action_text_3 = "¡El individuo se resiste violentamente iniciando una confrontación directa contra los oficiales!"
        action_text_4 = "Los agentes intervienen con maniobras de control táctico para someter de inmediato al sujeto."
        
    badge_sub = f"CASO REAL | {location.upper()}"
    if len(badge_sub) > 40:
        badge_sub = badge_sub[:40]
        
    spanish_title = f"¡{badge_title}! | CASO REAL #Shorts"
    
    narrations = [
        {"id": "narr_01", "start": t1, "text": f"Oficiales intervienen en {location} tras recibir un reporte de emergencia."},
        {"id": "narr_02", "start": t2, "text": "Los agentes avanzan con armas listas exigiendo al sospechoso mostrar las manos."},
        {"id": "narr_03", "start": t3, "text": action_text_3},
        {"id": "narr_04", "start": t4, "text": action_text_4},
        {"id": "narr_05", "start": t5, "text": "El perímetro es asegurado y la situación controlada. Suscríbete a Expediente Policial."}
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

def analyze_video(video_data, history_file, raw_clip_mp4=None, optimal_window=None):
    case_code = determine_case_code(history_file)
    print(f"[Analyzer] Processing case {case_code} for '{video_data.get('title')}'")
    
    # 1. Pre-calculate optimal tactical action window if not provided
    if not optimal_window:
        opt_start, opt_dur, opt_teaser = find_optimal_action_window(video_data)
        optimal_window = (opt_start, opt_dur, opt_teaser)
    else:
        opt_start, opt_dur, opt_teaser = optimal_window

    # Dynamic narration timestamps aligned with action
    t1 = 1.0
    t2 = max(8.0, opt_teaser - 6.0)
    t3 = opt_teaser
    t4 = min(opt_teaser + 16.0, opt_dur - 14.0)
    t5 = opt_dur - 7.0
    timestamps = [t1, t2, t3, t4, t5]
    
    result = None
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    # If raw clip is provided, attempt Multimodal Vision grounding with Gemini
    if raw_clip_mp4 and os.path.exists(raw_clip_mp4) and gemini_key:
        print("[Analyzer] Extracting 5 slice keyframes for Multimodal Vision-Grounded AI Scripting...")
        frames_b64 = []
        for ts in timestamps:
            b64 = extract_frame_base64(raw_clip_mp4, ts)
            if b64:
                frames_b64.append(b64)
        if len(frames_b64) == 5:
            print("[Analyzer] Running Gemini Multimodal Vision analysis on extracted frames...")
            result = analyze_with_gemini_vision(gemini_key, video_data, optimal_window, frames_b64, timestamps)

    if not result and groq_key:
        print("[Analyzer] Running Groq AI True Crime script generation with dynamic timeline anchoring...")
        result = analyze_with_groq(groq_key, video_data, optimal_window, timestamps)
        
    if not result and gemini_key:
        print("[Analyzer] Running Gemini text AI script generation...")
        result = analyze_with_gemini(gemini_key, video_data, optimal_window, timestamps)
        
    if not result:
        print("[Analyzer] Falling back to intelligent rule-based engine...")
        result = analyze_rule_based(video_data, optimal_window, timestamps)
        
    # Enforce verified tactical window
    result["slice_start"] = opt_start
    result["slice_duration"] = opt_dur
    if not result.get("teaser_start") or result["teaser_start"] < 5.0 or result["teaser_start"] > opt_dur - 4.0:
        result["teaser_start"] = opt_teaser

    # Enforce synchronized narration timestamps
    for i, narr in enumerate(result.get("narrations", [])):
        if i < len(timestamps):
            narr["start"] = timestamps[i]

    result["case_code"] = case_code
    result["video_id"] = video_data.get("id")
    result["video_url"] = video_data.get("url") or f"https://www.youtube.com/watch?v={video_data.get('id')}"
    result["original_title"] = video_data.get("title")
    result["teaser_duration"] = 3.5

    print(f"[Analyzer] Ready: [{case_code}] {result['spanish_title']}")
    print(f"[Analyzer] Badge Sub: {result['badge_sub']} | Badge Title: {result['badge_title']}")
    print(f"[Analyzer] Slice: start={result['slice_start']}s, dur={result['slice_duration']}s | Teaser: {result['teaser_start']}s")
    for i, narr in enumerate(result.get("narrations", [])):
        print(f"    [Narration {i+1}] {narr.get('start', 0.0):.1f}s: {narr.get('text', '')[:50]}...")
    return result
