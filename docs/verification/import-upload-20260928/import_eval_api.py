from app.main import create_app
from app.config import Settings
from app.models import Base

def factory():
    app = create_app(Settings(_env_file=None, database_url='sqlite:////tmp/import-upload-eval-20260928.db', csrf_secret='import-upload-acceptance-secret-32-characters', allowed_origins=['http://127.0.0.1:4181'], llm_provider='deepseek'))
    Base.metadata.create_all(app.state.engine)
    return app
