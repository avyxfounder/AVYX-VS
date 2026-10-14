import asyncio
from pathlib import Path

from faster_whisper import WhisperModel

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model


async def transcribe(path: Path) -> str:
    def run():
        model = _get_model()
        segments, _ = model.transcribe(
            str(path),
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        parts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                parts.append(text)
        return "\n".join(parts).strip()

    result = await asyncio.to_thread(run)
    return result or "Речь не распознана."
