"""Local, network-free Vosk transcription support."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from threading import Lock
from typing import BinaryIO


DEFAULT_MODEL_ROOT = (
    Path.home() / ".local" / "share" / "smartassist" / "models" / "vosk"
)
MODEL_ENVIRONMENT_VARIABLE = "SMARTASSIST_VOSK_MODEL_DIR"
MODEL_DIRECTORIES = {
    "hi": Path("hindi/vosk-model-small-hi-0.22"),
    "te": Path("telugu/vosk-model-small-te-0.42"),
}
FFMPEG_TIMEOUT_SECONDS = 30
MAX_AUDIO_BYTES = 10 * 1024 * 1024
PCM_CHUNK_BYTES = 4000

_model_cache = {}
_model_lock = Lock()


class VoskTranscriptionError(Exception):
    """Base error for local Vosk transcription failures."""


class UnsupportedLanguageError(VoskTranscriptionError):
    """Raised when no local model is available for a language."""


class ModelUnavailableError(VoskTranscriptionError):
    """Raised when a configured local model cannot be used."""


class InvalidAudioError(VoskTranscriptionError):
    """Raised when audio cannot be converted to the required PCM format."""


class RecognitionError(VoskTranscriptionError):
    """Raised when Vosk cannot produce a transcript."""


def get_model_root() -> Path:
    """Return the configured external model directory without loading a model."""
    configured_root = os.getenv(MODEL_ENVIRONMENT_VARIABLE, "").strip()
    return Path(configured_root).expanduser() if configured_root else DEFAULT_MODEL_ROOT


def get_model_path(language: str) -> Path:
    """Return the model path for a supported language."""
    normalized_language = (language or "").strip().lower()
    try:
        relative_path = MODEL_DIRECTORIES[normalized_language]
    except KeyError as exc:
        raise UnsupportedLanguageError(
            f"Offline Vosk transcription is not available for language "
            f"{normalized_language or 'unknown'}."
        ) from exc
    return get_model_root() / relative_path


def _load_model(language: str):
    model_path = get_model_path(language)
    if not model_path.is_dir():
        raise ModelUnavailableError(
            f"The offline Vosk model for {language} is missing: {model_path}"
        )

    try:
        import vosk
    except ImportError as exc:
        raise ModelUnavailableError(
            "The Vosk package is not installed for offline transcription."
        ) from exc

    cache_key = str(model_path.resolve())
    with _model_lock:
        cached_model = _model_cache.get(cache_key)
        if cached_model is not None:
            return cached_model
        try:
            model = vosk.Model(str(model_path))
        except Exception as exc:
            raise ModelUnavailableError(
                f"Unable to load the offline Vosk model for {language}."
            ) from exc
        _model_cache[cache_key] = model
        return model


def _ffmpeg_binary() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def _copy_audio_to_file(audio_file: BinaryIO, suffix: str) -> str:
    temporary_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temporary_path = temporary_file.name
    completed = False
    try:
        total_bytes = 0
        while True:
            chunk = audio_file.read(1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_AUDIO_BYTES:
                raise InvalidAudioError(
                    "Audio recordings must be 10 MB or smaller."
                )
            temporary_file.write(chunk)
        temporary_file.flush()
        completed = True
        return temporary_path
    except InvalidAudioError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise InvalidAudioError("Unable to read the uploaded audio recording.") from exc
    finally:
        temporary_file.close()
        if not completed:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _convert_to_pcm_wav(input_path: str) -> str:
    output_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    output_path = output_file.name
    output_file.close()
    try:
        conversion = subprocess.run(
            [
                _ffmpeg_binary(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                input_path,
                "-map",
                "0:a:0",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-sample_fmt",
                "s16",
                "-f",
                "wav",
                output_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        try:
            os.unlink(output_path)
        except OSError:
            pass
        raise InvalidAudioError("Audio conversion took too long.") from exc
    except OSError as exc:
        try:
            os.unlink(output_path)
        except OSError:
            pass
        raise InvalidAudioError("The ffmpeg audio converter is unavailable.") from exc

    if conversion.returncode != 0:
        try:
            os.unlink(output_path)
        except OSError:
            pass
        raise InvalidAudioError("The uploaded file is not a valid audio recording.")
    return output_path


def _recognize_wav(wav_path: str, language: str) -> str:
    try:
        import vosk
        import wave

        model = _load_model(language)
        with wave.open(wav_path, "rb") as wav_file:
            if (
                wav_file.getnchannels() != 1
                or wav_file.getsampwidth() != 2
                or wav_file.getframerate() != 16000
            ):
                raise InvalidAudioError("Audio conversion did not produce PCM WAV.")
            recognizer = vosk.KaldiRecognizer(model, 16000)
            while True:
                chunk = wav_file.readframes(PCM_CHUNK_BYTES)
                if not chunk:
                    break
                recognizer.AcceptWaveform(chunk)
            result = json.loads(recognizer.FinalResult())
    except InvalidAudioError:
        raise
    except (OSError, EOFError, ValueError, json.JSONDecodeError) as exc:
        raise RecognitionError("Unable to recognize the converted audio.") from exc
    except Exception as exc:
        raise RecognitionError("Offline Vosk recognition failed.") from exc

    text = result.get("text", "").strip() if isinstance(result, dict) else ""
    if not text:
        raise RecognitionError("Offline Vosk recognition returned no transcript.")
    return text


def transcribe_audio(audio_file: BinaryIO, language: str = "hi") -> str:
    """Transcribe validated audio locally without making network requests."""
    normalized_language = (language or "").strip().lower()
    get_model_path(normalized_language)
    input_path = None
    wav_path = None
    try:
        try:
            audio_file.seek(0)
        except (AttributeError, OSError):
            pass
        suffix = Path(getattr(audio_file, "name", "voice.webm")).suffix or ".webm"
        input_path = _copy_audio_to_file(audio_file, suffix)
        wav_path = _convert_to_pcm_wav(input_path)
        return _recognize_wav(wav_path, normalized_language)
    finally:
        for path in (input_path, wav_path):
            if path:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
