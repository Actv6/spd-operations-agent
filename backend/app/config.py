from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / "data" / "scenario"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_url: str = f"sqlite:///{ROOT / 'var' / 'spd.db'}"
    llm_provider: Literal["mock", "deepseek"] = "deepseek"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_api_key: str = ""
    csrf_secret: str = Field(min_length=32)
    cookie_secure: bool = False
    allowed_origins: list[str] = ["http://127.0.0.1:4180", "http://localhost:4180"]
    session_ttl_seconds: int = 86400
    run_timeout_seconds: int = Field(default=45, ge=1, le=120)
    lease_seconds: int = 90
    max_tool_calls: int = Field(default=8, ge=1, le=8)
    max_input_chars: int = Field(default=32000, ge=4000, le=100000)
    max_run_tokens: int = Field(default=32000, ge=4000, le=200000)
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_workspace_id: str = ""
    langsmith_project: str = "spd-local-agent"
    langsmith_spool_dir: str = str(ROOT / "var" / "langsmith")
    rate_limit: int = 15
    rate_window_seconds: int = 60

    @model_validator(mode="after")
    def validate_lease(self):
        if self.database_url.startswith("sqlite:///"):
            path = self.database_url[len("sqlite:///"):]
            if path != ":memory:" and not Path(path).is_absolute():
                self.database_url = f"sqlite:///{(ROOT / path).resolve()}"
        if self.lease_seconds <= self.run_timeout_seconds + 5:
            raise ValueError("Lease must exceed the entire run timeout plus 5 seconds")
        return self
