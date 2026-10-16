import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["ADMIN_TOKEN"] = "test-admin"
