import os
import sys
import json
import time
import base64
import requests
import subprocess
import asyncio
import edge_tts

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

GEMINI_TTS_MODEL = "gemini-3.8-flash-tts"
GEMINI_VOICE = "Fenrir" # Deep, authoritative, human masculine voice

EDGE_VOICE = "es-MX-JorgeNeural"
EDGE_RATE = "+0%"
EDGE_PITCH = "-2Hz"

def sec_to_ass_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def get_audio_duration(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    out = subprocess.check_output(cmd).decode().strip()
    return float(out)

def synthesize_with_gemini(text, api_key, output_wav):
    """
    Uses Google Gemini 3.8 Flash TTS for ultra-realistic, human voice synthesis.
    Includes retry logic and rate-limit handling.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TTS_MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": GEMINI_VOICE
                    }
                }
            }
        }
    }
    
    for attempt in range(1, 4):
        try:
            r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=25)
            if r.status_code == 200:
                res = r.json()
                b64_data = res["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                raw_bytes = base64.b64decode(b64_data)
                
                # Write temporary raw file and convert with ffmpeg to standard 48kHz stereo WAV
                tmp_raw = output_wav + ".tmp"
                with open(tmp_raw, "wb") as f:
                    f.write(raw_bytes)
                    
                subprocess.run([
                    "ffmpeg", "-y", "-i", tmp_raw,
                    "-ar", "48000", "-ac", "2",
                    output_wav
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                
                if os.path.exists(tmp_raw):
                    os.remove(tmp_raw)
                    
                time.sleep(2.5) # Prevent RPM rate limits
                return True
            elif r.status_code == 429:
                wait_t = attempt * 4
                print(f"[Narrator] Gemini rate limit 429. Waiting {wait_t}s...")
                time.sleep(wait_t)
            else:
                print(f"[Narrator] Gemini error {r.status_code}: {r.text[:120]}")
                time.sleep(2)
        except Exception as e:
            print(f"[Narrator] Gemini exception: {e}")
            time.sleep(2)
            
    return False

async def synthesize_with_edge(text, output_wav):
    """
    Fallback to Microsoft neural voice (Jorge) if Gemini TTS is unavailable or rate-limited.
    """
    tmp_mp3 = output_wav + ".mp3"
    comm = edge_tts.Communicate(text, EDGE_VOICE, rate=EDGE_RATE, pitch=EDGE_PITCH)
    await comm.save(tmp_mp3)
    
    subprocess.run([
        "ffmpeg", "-y", "-i", tmp_mp3,
        "-ar", "48000", "-ac", "2",
        output_wav
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    
    if os.path.exists(tmp_mp3):
        os.remove(tmp_mp3)

def synthesize_clip(item, api_key, work_dir):
    wav_path = os.path.join(work_dir, f"{item['id']}.wav")
    success = False
    
    if api_key:
        print(f"[Narrator] Synthesizing '{item['id']}' with Google Gemini Human Voice ({GEMINI_VOICE})...")
        try:
            success = synthesize_with_gemini(item["text"], api_key, wav_path)
        except Exception as e:
            print(f"[Narrator] Gemini synthesis exception: {e}")
            
    if not success:
        print(f"[Narrator] Using Edge-TTS Neural Voice ({EDGE_VOICE}) for '{item['id']}'...")
        asyncio.run(synthesize_with_edge(item["text"], wav_path))
        
    dur = get_audio_duration(wav_path)
    item["wav"] = wav_path
    item["dur"] = dur
    return item

def build_ass_subtitles(events, output_ass):
    ass_content = [
        "[Script Info]",
        "Title: Expediente Policial Vertical Subtitles",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Narrator,Impact,48,&H0000FFFF,&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,0.8,0,1,3.5,2.0,2,40,40,390,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]
    
    for start_t, end_t, style, text in events:
        st_str = sec_to_ass_time(start_t)
        en_str = sec_to_ass_time(end_t)
        ass_content.append(f"Dialogue: 0,{st_str},{en_str},{style},,0,0,0,,{text}")
        
    with open(output_ass, "w", encoding="utf-8") as f:
        f.write("\n".join(ass_content) + "\n")
    print(f"[Narrator] ASS subtitles generated: {output_ass}")

def process_narration(metadata, work_dir):
    os.makedirs(work_dir, exist_ok=True)
    api_key = os.environ.get("GEMINI_API_KEY")
    slice_dur = metadata.get("slice_duration", 120)
    
    narr_list = metadata.get("narrations")
    if not narr_list:
        narr_list = [
            {"id": "narr_01_hook", "target_time": 1.0, "text": "Una intervención policial que se tornó de alto riesgo."},
            {"id": "narr_02_context", "target_time": 25.0, "text": "Los agentes recibieron una llamada de emergencia alertando sobre la presencia de un sospechoso armado."},
            {"id": "narr_03_tension", "target_time": 55.0, "text": "A pesar de las órdenes reiteradas de detenerse, la situación continuó escalando rápidamente."},
            {"id": "narr_04_action", "target_time": 85.0, "text": "Ante la amenaza directa a sus vidas, los oficiales se vieron forzados a actuar en legítima defensa."},
            {"id": "narr_05_outro", "target_time": slice_dur - 12.0, "text": "Las investigaciones oficiales determinaron el uso justificado de la fuerza. Suscríbete a Expediente Policial."}
        ]
        
    print(f"[Narrator] Processing {len(narr_list)} voiceover interventions...")
    processed_items = []
    
    for item in narr_list:
        p_item = synthesize_clip(item, api_key, work_dir)
        processed_items.append(p_item)
        
    # Check timings and avoid overlaps
    events = []
    current_time = 0.5
    for item in processed_items:
        target = item.get("target_time", current_time)
        actual_start = max(target, current_time + 1.0)
        # Ensure it doesn't exceed slice_dur
        if actual_start + item["dur"] > slice_dur:
            actual_start = max(1.0, slice_dur - item["dur"] - 1.0)
            
        actual_end = actual_start + item["dur"]
        current_time = actual_end
        item["actual_start"] = actual_start
        item["actual_end"] = actual_end
        
        words = item["text"].split()
        if len(words) > 9:
            half = len(words) // 2
            formatted_text = " ".join(words[:half]) + "\\N" + " ".join(words[half:])
        else:
            formatted_text = item["text"]
            
        events.append((actual_start, actual_end, "Narrator", formatted_text))
        print(f"[Narrator] [{item['id']}] {actual_start:.1f}s -> {actual_end:.1f}s ({item['dur']:.1f}s): {item['text'][:45]}...")
        
    ass_path = os.path.join(work_dir, "subtitles.ass")
    build_ass_subtitles(events, ass_path)
    
    # Mix all narration tracks
    narration_mixed_wav = os.path.join(work_dir, "narration_track.wav")
    delays = [int(item["actual_start"] * 1000) for item in processed_items]
    inputs = []
    filter_parts = []
    for i, item in enumerate(processed_items):
        inputs.extend(["-i", item["wav"]])
        filter_parts.append(f"[{i}:a]adelay={delays[i]}|{delays[i]}[a{i}]")
        
    mix_str = "".join(f"[a{i}]" for i in range(len(processed_items)))
    filter_complex = f"{';'.join(filter_parts)};{mix_str}amix=inputs={len(processed_items)}:normalize=0[aout]"
    
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-ar", "48000", "-ac", "2",
        narration_mixed_wav
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    print(f"[Narrator] All {len(processed_items)} interventions mixed into {narration_mixed_wav}")
    
    return {
        "ass_file": ass_path,
        "narration_wav": narration_mixed_wav,
        "items": processed_items
    }
