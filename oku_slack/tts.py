"""Gemini TTS: synth(persona_key, text) -> WAV path. Strict 1:1 persona->voice, no voice fallback."""
import base64, hashlib, logging, pathlib, wave, requests
from . import core

log = logging.getLogger("oku.tts")
GEMINI_URL = core.GEMINI_URL
DEFAULT_MODELS = ["gemini-3.8-flash-tts", "gemini-2.5-flash-preview-tts"]
RATE, WIDTH, CHANNELS = 24000, 2, 1

class TTSConfigError(ValueError): pass

def validate(cfg):
    """Every persona must have exactly one dedicated voice; no voice shared; no default voice."""
    t = cfg.get("tts", {}); voices = t.get("voices", {})
    if "default" in voices or "voice" in t: raise TTSConfigError("shared/default voice not allowed")
    missing = [k for k in cfg.get("personas", {}) if k not in voices or not voices[k].get("voice")]
    if missing: raise TTSConfigError(f"personas without dedicated voice: {missing}")
    seen = {}
    for k, v in voices.items():
        name = v.get("voice", "").strip().lower()
        if name in seen: raise TTSConfigError(f"voice {v['voice']!r} shared by {seen[name]} and {k}")
        seen[name] = k
    return voices

def write_wav(path, pcm):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(CHANNELS); w.setsampwidth(WIDTH); w.setframerate(RATE); w.writeframes(pcm)

def synth(persona_key, text, cfg=None, post=requests.post, cache_dir=None):
    cfg = cfg or core.load_config()
    voices = validate(cfg)
    v = voices[persona_key]  # KeyError for unknown persona: never substitute
    voice, style = v["voice"], v.get("style", "")
    models = cfg.get("tts", {}).get("models") or DEFAULT_MODELS
    cache = pathlib.Path(cache_dir or core.ROOT / "logs" / "tts"); cache.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(f"{voice}\0{style}\0{text}".encode()).hexdigest()[:24]
    out = cache / f"{persona_key}-{h}.wav"
    if out.exists(): return out
    prompt = f"{style}\n\n{text}" if style else text
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    keys, _ = core.gemini_settings()
    if not keys: raise RuntimeError("no GEMINI_API_KEY(S)")
    last = None
    for model in models:          # model fallback only; the voice is fixed
        for i, key in enumerate(keys):
            r = post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": key}, json=body, timeout=120)
            if r.status_code != 200:
                log.warning("tts %s key#%d -> %s", model, i, r.status_code); last = r.status_code; continue
            try:
                part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                pcm = base64.b64decode(part["data"])
            except (KeyError, IndexError, ValueError) as e:
                log.warning("tts %s bad response: %s", model, type(e).__name__); last = "bad"; continue
            write_wav(out, pcm); return out
    raise RuntimeError(f"tts failed for {persona_key} voice {voice} ({last})")
