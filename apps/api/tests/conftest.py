import atexit
import os
import tempfile

# A file database, not ":memory:": the in-memory engine shares one connection between the request
# thread and background-job threads, so one thread's rollback can undo another's pending write.
if "DATABASE_URL" not in os.environ:
    _dir = tempfile.mkdtemp(prefix="pe-test-")
    os.environ["DATABASE_URL"] = f"sqlite:///{_dir}/app.db"
    atexit.register(lambda: __import__("shutil").rmtree(_dir, ignore_errors=True))
os.environ["ADMIN_TOKEN"] = "test-admin"
