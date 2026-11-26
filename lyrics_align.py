"""The machine learning behind lyrics.py: vocal separation, transcription, forced alignment.

Kept apart so lyrics.py (and its tests) import without torch.

- timeline_path: the sample decoded on rekordbox's timeline, which every later step uses (so a time found in it
  is a position rkbx_link reports).  rekordbox (like Ableton) ignores an MP3's LAME gapless header: it plays the
  encoder delay and the header frame itself as silence, where ffmpeg and libsndfile trim both.  Measured on
  a real library against Ableton warp markers (2026-11-24): gapless MP3s came out 52 ms early, plain MP3s and
  WAV/AIFF on time; the header frame (1152 samples) + the delay ffprobe reports (start_time, 1105 samples) is
  51.2 ms.  So MP3s are decoded once by ffmpeg with that silence put back; WAV / AIFF are used as they are.
- vocals_path: Demucs (htdemucs, two stems) vocals of that, cached by the sample's sha1 in
  ~/Library/Caches/djtools/lyrics/<sha1>/ (also what lyrics_server plays as "vocals only").
- transcribe: Whisper (large-v3-turbo on Apple's MLX) segments with word time stamps; these give the song's
  structure (which lines, how often, roughly when) but are only good to ~100-200 ms.
- Aligner: torchaudio's MMS_FA forced alignment (CTC, 20 ms frames): known words inside a time window to their
  start and end.  Words are romanized (unidecode) to the a-z and ' it knows; a word with none of those letters
  (a number) comes back untimed (t0 None) for lyrics.fill_untimed.
"""

import json
import os
import shutil
import subprocess
import tempfile
from typing import Any

import lyrics

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
CACHE_DIR = os.path.expanduser("~/Library/Caches/djtools/lyrics")
SAMPLE_RATE = 16000


def cache_dir(sample: str) -> str:
    return os.path.join(CACHE_DIR, lyrics.file_sha1(sample))


PLAIN = (".wav", ".aif", ".aiff")


def rekordbox_shift(ext: str, start_time: float, sample_rate: int) -> float:
    """Seconds rekordbox's timeline runs ahead of ffmpeg's decode of a file: for an MP3 with a gapless header
    (ffprobe start_time > 0), the trimmed delay plus the header frame (1152 samples; 576 for MPEG-2 rates)."""
    if ext.lower() != ".mp3" or start_time <= 0 or sample_rate <= 0:
        return 0.0
    frame = 1152 if sample_rate >= 32000 else 576
    return start_time + frame / sample_rate


def probe_audio(path: str) -> tuple[float, int]:
    """(start_time, sample_rate) of the first audio stream."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=start_time,sample_rate", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    st = (json.loads(out).get("streams") or [{}])[0]
    try:
        start = float(st.get("start_time") or 0)
    except ValueError:
        start = 0.0
    return start, int(st.get("sample_rate") or 0)


def sample_shift(sample: str) -> float:
    start, sr = probe_audio(sample)
    return rekordbox_shift(os.path.splitext(sample)[1], start, sr)


def timeline_path(sample: str) -> str:
    """The sample as rekordbox plays it, as a file every tool reads the same way (see the module notes)."""
    if sample.lower().endswith(PLAIN):
        return sample
    d = cache_dir(sample)
    out = os.path.join(d, "timeline.flac")
    if os.path.isfile(out):
        return out
    os.makedirs(d, exist_ok=True)
    start, sr = probe_audio(sample)
    pad = int(round(rekordbox_shift(os.path.splitext(sample)[1], start, sr) * sr))
    tmp = out + ".tmp.flac"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", sample, "-map", "0:a:0"]
    if pad:
        cmd += ["-af", "adelay={}S:all=1".format(pad)]
    subprocess.run(cmd + [tmp], check=True)
    os.replace(tmp, out)
    return out


def vocals_path(sample: str) -> str:
    """The vocal stem (Demucs) of the sample on rekordbox's timeline, made once and cached."""
    d = cache_dir(sample)
    out = os.path.join(d, "vocals-timeline.wav")
    if os.path.isfile(out):
        return out
    source = timeline_path(sample)
    os.makedirs(d, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=d) as tmp:
        cmd = ["demucs", "--two-stems", "vocals", "-n", "htdemucs", "-o", tmp, source]
        if _mps():
            cmd[1:1] = ["-d", "mps"]
        subprocess.run(cmd, check=True)
        stem = os.path.splitext(os.path.basename(source))[0]
        made = os.path.join(tmp, "htdemucs", stem, "vocals.wav")
        shutil.move(made, out)
    return out


def _mps() -> bool:
    try:
        import torch

        return bool(torch.backends.mps.is_available())
    except Exception:
        return False


def transcribe(audio: str, language: str | None = None) -> list[dict[str, Any]]:
    """Whisper's segments, cached beside the audio's other derived files (Whisper is not deterministic: its
    temperature fallback samples, so a rerun of the later steps should see the same transcript)."""
    d = cache_dir(audio)
    path = os.path.join(d, "whisper-{}-nc.json".format(language or "auto"))
    if os.path.isfile(path):
        with open(path, encoding="utf8") as f:
            cached = json.load(f)
        if cached.get("model") == WHISPER_MODEL:
            return cached["segments"]
    import mlx_whisper

    # Each 30 s window on its own (not conditioned on the text before it): over a long instrumental part Whisper
    # makes up "Thank you." and, conditioned on that, repeats it for the rest of the song (it took all of a 10-minute
    # Rufus remix). The made-up lines left over silence match no lyric and are dropped.
    r: dict[str, Any] = mlx_whisper.transcribe(audio, path_or_hf_repo=WHISPER_MODEL, word_timestamps=True,
                                               language=language, condition_on_previous_text=False)
    raw: list[dict[str, Any]] = r["segments"]
    segments = [{"start": s["start"], "end": s["end"], "text": s["text"], "words": s.get("words", [])} for s in raw]
    os.makedirs(d, exist_ok=True)
    lyrics.write_json_atomic(path, {"model": WHISPER_MODEL, "segments": segments})
    return segments


token_word = lyrics.token_word   # a word as MMS_FA's alphabet spells it


class Aligner:
    """Forced alignment on one audio file (loaded once, mono 16 kHz)."""

    def __init__(self, audio: str) -> None:
        import torch
        import torchaudio

        self.torch = torch
        wav, sr = torchaudio.load(audio)
        self.wav = torchaudio.functional.resample(wav.mean(0, keepdim=True), sr, SAMPLE_RATE)
        self.duration = self.wav.shape[1] / SAMPLE_RATE
        bundle = torchaudio.pipelines.MMS_FA
        self.model = bundle.get_model(with_star=False).eval()
        self.tokenizer: Any = bundle.get_tokenizer()
        self.aligner: Any = bundle.get_aligner()
        self.F = torchaudio.functional

    def _emission(self, a: float, b: float) -> tuple[Any, float]:
        a = max(0.0, a)
        b = min(self.duration, max(b, a + 0.1))
        chunk = self.wav[:, int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)]
        with self.torch.inference_mode():
            em, _ = self.model(chunk)
        sec_per_frame = chunk.shape[1] / em.shape[1] / SAMPLE_RATE
        return em, sec_per_frame

    def align_words(self, words: list[str], a: float, b: float) -> list[dict[str, Any]]:
        """Each word's {t0, t1, text, score} inside [a, b] (t0 None: no letters to align)."""
        a = max(0.0, a)
        toks = [token_word(w) for w in words]
        out: list[dict[str, Any]] = [{"t0": None, "t1": None, "text": w, "score": 0.0} for w in words]
        idx = [i for i, t in enumerate(toks) if t]
        if not idx:
            return out
        em, spf = self._emission(a, b)
        with self.torch.inference_mode():
            spans = self.aligner(em[0], self.tokenizer([toks[i] for i in idx]))
        for i, sp in zip(idx, spans):
            n = sum(len(x) for x in sp)
            out[i]["t0"] = round(a + sp[0].start * spf, 3)
            out[i]["t1"] = round(a + sp[-1].end * spf, 3)
            out[i]["score"] = round(float(sum(float(x.score) * len(x) for x in sp) / max(1, n)), 3)
        return out

    def path_score(self, words: list[str], a: float, b: float) -> float:
        """Log-likelihood of the whole window given these words (blanks included): compares texts of about the
        same length on the same window."""
        toks = [t for t in (token_word(w) for w in words) if t]
        if not toks:
            return float("-inf")
        em, _ = self._emission(a, b)
        with self.torch.inference_mode():
            lp = self.torch.log_softmax(em, -1)
            ids = [t for w in self.tokenizer(toks) for t in w]
            tg = self.torch.tensor([ids], dtype=self.torch.int32)
            if tg.shape[1] > lp.shape[1]:
                return float("-inf")
            _, sc = self.F.forced_align(lp, tg, blank=0)
        return float(sc.sum())
