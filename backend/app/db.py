from pymongo import AsyncMongoClient

from .config import settings

client = AsyncMongoClient(settings.mongo_uri)
db = client[settings.mongo_db]

# Existing collections
files = db["files"]          # uploaded file metadata + dataset profile
messages = db["messages"]    # chat / investigation memory
reports = db["reports"]      # generated reports
memories = db["memories"]    # verified findings remembered across sessions

# New project workspace collections
projects = db["projects"]
documents = db["documents"]
code_branches = db["code_branches"]
code_commits = db["code_commits"]
