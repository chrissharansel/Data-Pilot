from pymongo import AsyncMongoClient

from .config import settings

client = AsyncMongoClient(settings.mongo_uri)
db = client[settings.mongo_db]

files = db["files"]          # uploaded file metadata + dataset profile
messages = db["messages"]    # chat / investigation memory
reports = db["reports"]        # generated reports (structured; PDF/Excel are rendered on download)
memories = db["memories"]      # verified findings remembered across sessions (embedded in Chroma too)
