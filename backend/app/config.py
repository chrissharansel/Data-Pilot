from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "datapilot"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chroma_dir: str = "./storage/chroma"
    upload_dir: str = "./storage/uploads"
    projects_dir: str = "./storage/projects"  # NEW: project documents + codebase
    chunk_size: int = 1000
    chunk_overlap: int = 150
    rows_per_chunk: int = 40
    max_embedded_rows: int = 5000
    top_k: int = 5
    max_agent_steps: int = 5
    sensitive_policy: str = "ask"
    memory_top_k: int = 3
    memory_max_distance: float = 1.0
    cors_origins: str = "http://localhost:5173"


settings = Settings()
