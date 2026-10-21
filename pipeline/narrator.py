import asyncio
import edge_tts
import os
import subprocess
import json
import sys

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

VOICE = "es-MX-JorgeNeural"
RATE = "+0%"
PITCH = "-2Hz"

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

async def synthesize_speech(text, output_mp3):
    comm = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)
    await comm.save(output_mp3)

def convert_to_wav(input_mp3, output_wav):
    cmd = [
        "ffmpeg", "-y", "-i", input_mp3,
        "-ar", "48000", "-ac", "2",
        output_wav
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def build_ass_subtitles(events, output_ass):
    """
    Builds the ASS subtitle file with EXP 001-007 visual guidelines.
    Safe-zone MarginV=390, PlayRes 1080x1920, yellow text with thick black outline.
    """
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
        "Style: Radio,Arial,42,&H00FF80FF,&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,0.8,0,1,3.5,2.0,2,40,40,390,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]
    
    for start_t, end_t, style, text in events:
        st_str = sec_to_ass_time(start_t)
        en_str = sec_to_ass_time(end_t)
        # Split text into chunks if too long
        ass_content.append(f"Dialogue: 0,{st_str},{en_str},{style},,0,0,0,,{text}")
        
    with open(output_ass, "w", encoding="utf-8") as f:
        f.write("\n".join(ass_content) + "\n")
    print(f"[Narrator] Subtitle ASS file generated: {output_ass}")

def process_narration(metadata, work_dir):
    """
    Synthesizes hook, context, and outro; positions them on timeline; mixes audio and generates ASS.
    """
    os.makedirs(work_dir, exist_ok=True)
    slice_dur = metadata.get("slice_duration", 120)
    
    items = [
        {"id": "hook", "text": metadata.get("narration_hook", ""), "target": 1.0},
        {"id": "context", "text": metadata.get("narration_context", ""), "target": min(35.0, slice_dur * 0.3)},
        {"id": "outro", "text": metadata.get("narration_outro", ""), "target": None} # Set dynamically
    ]
    
    print("[Narrator] Synthesizing Spanish neural narration...")
    for item in items:
        mp3_path = os.path.join(work_dir, f"{item['id']}.mp3")
        wav_path = os.path.join(work_dir, f"{item['id']}.wav")
        asyncio.run(synthesize_speech(item["text"], mp3_path))
        convert_to_wav(mp3_path, wav_path)
        item["wav"] = wav_path
        item["dur"] = get_audio_duration(wav_path)
        
    # Calculate outro start
    outro_dur = items[2]["dur"]
    items[2]["target"] = max(items[1]["target"] + items[1]["dur"] + 2.0, slice_dur - outro_dur - 1.5)
    
    # Subtitle events
    events = []
    for item in items:
        st = item["target"]
        en = st + item["dur"]
        # Format text to wrap gracefully
        words = item["text"].split()
        if len(words) > 10:
            half = len(words) // 2
            formatted_text = " ".join(words[:half]) + "\\N" + " ".join(words[half:])
        else:
            formatted_text = item["text"]
            
        events.append((st, en, "Narrator", formatted_text))
        print(f"[Narrator] Voice segment '{item['id']}': {st:.1f}s -> {en:.1f}s ({item['dur']:.1f}s)")
        
    ass_path = os.path.join(work_dir, "subtitles.ass")
    build_ass_subtitles(events, ass_path)
    
    # Generate audio mixing arguments or combined narration track
    # We create an audio track with silence where there is no narration
    # using FFmpeg amix or adelay
    narration_mixed_wav = os.path.join(work_dir, "narration_track.wav")
    
    delays = [int(item["target"] * 1000) for item in items]
    inputs = []
    filter_parts = []
    for i, item in enumerate(items):
        inputs.extend(["-i", item["wav"]])
        filter_parts.append(f"[{i}:a]adelay={delays[i]}|{delays[i]}[a{i}]")
    
    mix_str = "".join(f"[a{i}]" for i in range(len(items)))
    filter_complex = f"{';'.join(filter_parts)};{mix_str}amix=inputs={len(items)}:normalize=0[aout]"
    
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-ar", "48000", "-ac", "2",
        narration_mixed_wav
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    print(f"[Narrator] Combined narration audio track ready: {narration_mixed_wav}")
    
    return {
        "ass_file": ass_path,
        "narration_wav": narration_mixed_wav,
        "items": items
    }

if __name__ == "__main__":
    sample_meta = {
        "narration_hook": "Una intervención de rutina que cambió de un segundo a otro en Greenville County.",
        "narration_context": "Las cámaras policiales registraron el instante exacto en que los oficiales tuvieron que reaccionar bajo fuego directo.",
        "narration_outro": "El oficial sobrevivió gracias a su chaleco táctico. Suscríbete a Expediente Policial.",
        "slice_duration": 120
    }
    work = os.path.join(os.path.dirname(__file__), "..", "work_test")
    res = process_narration(sample_meta, work)
    print("Narration done:", res)
