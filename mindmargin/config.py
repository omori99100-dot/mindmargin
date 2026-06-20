import os
from pathlib import Path
from pydantic import BaseModel, Field
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


class LLMSettings(BaseModel):
    provider: str = "ollama"
    model: str = "llama3:70b"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 120


class PiperSettings(BaseModel):
    binary: str = "piper"
    voice_model: str = "en_US-lessac-medium"
    model_path: str = ""
    noise_scale: float = 0.667
    noise_w: float = 0.8
    length_scale: float = 1.0
    sample_rate: int = 22050


class VideoSettings(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    crf: int = 18
    preset: str = "medium"
    audio_bitrate: str = "192k"


class StorageSettings(BaseModel):
    output_root: str = str(ROOT / "output")
    temp_root: str = str(ROOT / "output" / "temp")


class YouTubeSettings(BaseModel):
    client_secrets_path: str = ""
    token_path: str = ""
    channel_id: str = ""
    default_privacy: str = "private"
    default_category: str = "27"
    upload_retries: int = 3


class Settings(BaseModel):
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    debug: bool = Field(default=False)

    redis_url: str = Field(default="redis://localhost:6379/0")
    database_url: str = Field(default="")

    llm: LLMSettings = LLMSettings()
    piper: PiperSettings = PiperSettings()
    video: VideoSettings = VideoSettings()
    storage: StorageSettings = StorageSettings()
    youtube: YouTubeSettings = YouTubeSettings()

    class Config:
        arbitrary_types_allowed = True


def load_settings() -> Settings:
    s = Settings()

    yaml_path = CONFIG_DIR / "settings.yaml"
    if yaml_path.exists():
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if raw:
            for section, values in raw.items():
                if hasattr(s, section) and isinstance(values, dict):
                    sub = getattr(s, section)
                    for k, v in values.items():
                        if hasattr(sub, k):
                            setattr(sub, k, v)
                else:
                    if hasattr(s, section):
                        setattr(s, section, values)

    env_map = {
        "OLLAMA_BASE_URL": ("llm", "base_url"),
        "LLM_MODEL": ("llm", "model"),
        "REDIS_URL": ("redis_url",),
        "DATABASE_URL": ("database_url",),
        "ENVIRONMENT": ("environment",),
        "LOG_LEVEL": ("log_level",),
    }
    for var, path in env_map.items():
        val = os.getenv(var)
        if val:
            target = s
            for attr in path[:-1]:
                target = getattr(target, attr)
            setattr(target, path[-1], val)

    return s


settings = load_settings()
