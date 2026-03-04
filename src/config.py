"""
Central configuration module.
Loads settings from .env file using pydantic-settings.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Gemini ---
    GOOGLE_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # --- Firebase ---
    FIREBASE_PROJECT_ID: str = "agentic-tester-ded1d"
    FIREBASE_API_KEY: str = ""
    FIREBASE_CREDENTIALS_PATH: str = "./firebase-credentials.json"

    # --- Execution ---
    OUTPUT_DIR: str = "./outputs"
    MAX_RETRIES: int = 2
    BROWSER_TYPE: str = "chromium"

    # --- Target ---
    TARGET_URL: str = "https://www.wikipedia.org/"

    # --- Generator Agent ---
    MAX_CRAWL_PAGES: int = 5
    RAG_CHUNK_SIZE: int = 1000
    RAG_CHUNK_OVERLAP: int = 200
    RAG_TOP_K: int = 5

    def get_output_path(self) -> Path:
        """Return resolved output directory, creating it if needed."""
        path = Path(self.OUTPUT_DIR).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_screenshots_path(self) -> Path:
        """Return resolved screenshots directory."""
        path = self.get_output_path() / "screenshots"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_results_path(self) -> Path:
        """Return resolved results directory."""
        path = self.get_output_path() / "results"
        path.mkdir(parents=True, exist_ok=True)
        return path


def get_settings() -> Settings:
    """Factory function to create Settings instance."""
    return Settings()
