import base64, copy, wave, pytest
from oku_slack import tts, core

CFG = core.load_config()

class R:
    def __init__(s, code, data=None): s.status_code, s._d = code, data
    def json(s): return s._d

def ok(pcm=b"\x01\x00" * 2400):
    return R(200, {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]})

@pytest.fixture(autouse=True)
def keys(monkeypatch): monkeypatch.setattr(core, "gemini_settings", lambda: (["k1", "k2"], ["x"]))

def test_config_voices_unique_and_complete():
    v = tts.validate(CFG)
    assert set(v) == set(CFG["personas"])
    names = [x["voice"].lower() for x in v.values()]
    assert len(names) == len(set(names))

def test_duplicate_voice_rejected():
    c = copy.deepcopy(CFG); c["tts"]["voices"]["peta"]["voice"] = c["tts"]["voices"]["babis"]["voice"]
    with pytest.raises(tts.TTSConfigError): tts.validate(c)

def test_missing_and_default_rejected():
    c = copy.deepcopy(CFG); del c["tts"]["voices"]["marty"]
    with pytest.raises(tts.TTSConfigError): tts.validate(c)
    c = copy.deepcopy(CFG); c["tts"]["voices"]["default"] = {"voice": "Kore"}
    with pytest.raises(tts.TTSConfigError): tts.validate(c)

def test_synth_writes_wav_and_uses_persona_voice(tmp_path):
    calls = []
    def post(url, headers, json, timeout): calls.append((url, json)); return ok()
    p = tts.synth("babis", "Ahoj", cfg=CFG, post=post, cache_dir=tmp_path)
    with wave.open(str(p)) as w: assert (w.getframerate(), w.getsampwidth(), w.getnchannels(), w.getnframes()) == (24000, 2, 1, 2400)
    vc = calls[0][1]["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]
    assert vc["voiceName"] == CFG["tts"]["voices"]["babis"]["voice"]
    tts.synth("babis", "Ahoj", cfg=CFG, post=post, cache_dir=tmp_path); assert len(calls) == 1  # cached

def test_rotation_keeps_voice_and_raises_without_substitute(tmp_path):
    seen = []
    def post(url, headers, json, timeout):
        seen.append(json["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"]); return R(429)
    with pytest.raises(RuntimeError): tts.synth("kalousek", "Ne.", cfg=CFG, post=post, cache_dir=tmp_path)
    assert set(seen) == {CFG["tts"]["voices"]["kalousek"]["voice"]} and len(seen) == 2 * len(CFG["tts"]["models"])

def test_unknown_persona_raises(tmp_path):
    with pytest.raises(KeyError): tts.synth("nobody", "x", cfg=CFG, post=lambda **k: ok(), cache_dir=tmp_path)
