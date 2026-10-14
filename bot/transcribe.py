import asyncio
from pathlib import Path

import av
from faster_whisper import WhisperModel

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model


def _has_audio_stream(path: Path) -> bool:
    try:
        with av.open(str(path)) as container:
            return len(container.streams.audio) > 0
    except Exception as exc:
        raise RuntimeError("Не удалось открыть аудио/видео файл.") from exc


async def transcribe(path: Path) -> str:
    def run():
        if not _has_audio_stream(path):
            return "🔇 В этом файле нет аудиодорожки — распознавать нечего."

        model = _get_model()
        try:
            segments, _ = model.transcribe(
                str(path),
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            parts = []
            for segment in segments:
                text = getattr(segment, "text", "").strip()
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()
        except IndexError as exc:
            if "tuple index out of range" in str(exc).lower():
                return "⚠️ Не удалось прочитать аудиодорожку. Возможно, файл повреждён или звук закодирован неподдерживаемым способом."
            raise

    result = await asyncio.to_thread(run)
    return result or "Речь не распознана."
