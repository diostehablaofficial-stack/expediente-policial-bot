import os
import sys
import json
import time
import subprocess
import asyncio
import edge_tts

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

EDGE_VOICE = "es-MX-JorgeNeural"
EDGE_RATE = "+6%"
EDGE_PITCH = "-2Hz"

def sec_to_ass(s):
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"

def get_audio_duration(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    out = subprocess.check_output(cmd).decode().strip()
    return float(out)

async def synth_voice(txt, out_wav):
    if os.path.exists(out_wav) and os.path.getsize(out_wav) > 1000:
        return

    mp3 = out_wav + ".mp3"
    success = False
    for attempt in range(8):
        try:
            if os.path.exists(mp3):
                os.remove(mp3)
            comm = edge_tts.Communicate(txt, EDGE_VOICE, rate=EDGE_RATE, pitch=EDGE_PITCH)
            await comm.save(mp3)
            if os.path.exists(mp3) and os.path.getsize(mp3) > 1000:
                success = True
                break
        except Exception as e:
            wait_s = 2 + attempt * 1.5
            print(f"    [TTS Retry {attempt+1}/8] Error: {e}. Reintentando en {wait_s:.1f}s...")
            await asyncio.sleep(wait_s)
            
    if not success or not os.path.exists(mp3) or os.path.getsize(mp3) == 0:
        raise RuntimeError(f"Fallo crítico al sintetizar audio para: {txt}")

    subprocess.run(["ffmpeg", "-y", "-i", mp3, "-ar", "48000", "-ac", "2", out_wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    if os.path.exists(mp3):
        os.remove(mp3)

def process_narration(metadata, work_dir):
    os.makedirs(work_dir, exist_ok=True)
    narr_list = metadata.get("narrations", [])
    if not narr_list:
        narr_list = [
            {"id": "narr_01", "start": 1.0, "text": "Una intervención policial que se tornó de alto riesgo."},
            {"id": "narr_02", "start": 16.0, "text": "Los agentes avanzan para cercar al sospechoso armado."},
            {"id": "narr_03", "start": 35.0, "text": "¡De imprevisto el sujeto abre fuego contra los policías!"},
            {"id": "narr_04", "start": 55.0, "text": "Los agentes responden a la agresión y aseguran el área."},
            {"id": "narr_05", "start": 74.0, "text": "La situación fue controlada y el agresor detenido. Suscríbete a Expediente Policial."}
        ]
        
    print(f"[Narrator] Sintetizando {len(narr_list)} frases con voz neuronal mexicana ({EDGE_VOICE})...")
    dialogues = []
    processed_items = []
    
    for i, n in enumerate(narr_list):
        wav_path = os.path.join(work_dir, f"narr_{i}.wav")
        asyncio.run(synth_voice(n["text"], wav_path))
        dur = get_audio_duration(wav_path)
        
        start_t = float(n.get("start", n.get("target_time", 1.0 + i * 18.0)))
        end_t = start_t + dur
        
        # Subtitles (chunked into 5 words per subtitle event for clean safe-zone layout)
        words = n["text"].split()
        chunk_size = 5
        word_dur = dur / max(1, len(words))
        for c_idx in range(0, len(words), chunk_size):
            chunk_words = words[c_idx:c_idx+chunk_size]
            c_start = start_t + c_idx * word_dur
            c_end = min(end_t, c_start + len(chunk_words) * word_dur)
            txt = " ".join(chunk_words)
            dialogues.append(f"Dialogue: 0,{sec_to_ass(c_start)},{sec_to_ass(c_end)},PoliceSub,,0,0,0,,{txt}")
            
        processed_items.append({
            "wav": wav_path,
            "start": start_t,
            "dur": dur
        })
        print(f"    [Narrator {i+1}] {start_t:.1f}s -> {end_t:.1f}s: {n['text'][:45]}...")

    # Write ASS Subtitle File (MarginV=320, safe zone yellow Impact)
    ass_path = os.path.join(work_dir, "subtitles.ass")
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: PoliceSub,Impact,52,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1.2,0,1,3.5,2.0,2,40,40,320,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(dialogues) + "\n")
    print(f"[Narrator] Subtítulos ASS generados: {ass_path}")

    # Build mixed audio narration track with ffmpeg adelay + amix
    narration_mixed_wav = os.path.join(work_dir, "narration_full.wav")
    filter_inputs = []
    filter_parts = []
    for i, item in enumerate(processed_items):
        filter_inputs.extend(["-i", item["wav"]])
        delay_ms = int(item["start"] * 1000)
        filter_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}]")
        
    amix_in = "".join([f"[a{i}]" for i in range(len(processed_items))])
    filter_parts.append(f"{amix_in}amix=inputs={len(processed_items)}:dropout_transition=0:normalize=0[aout]")
    
    cmd = ["ffmpeg", "-y"] + filter_inputs + ["-filter_complex", ";".join(filter_parts), "-map", "[aout]", "-ar", "48000", "-ac", "2", narration_mixed_wav]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[Narrator] Pista de narración mezclada: {narration_mixed_wav}")

    return {
        "ass_file": ass_path,
        "narration_wav": narration_mixed_wav
    }
