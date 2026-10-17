from app.db import Base, make_engine
from app.ratelimit import PostgresRateLimiter, make_limiter


def _engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/rl.db")
    Base.metadata.create_all(engine)
    return engine


def test_two_replicas_share_one_count(tmp_path):
    engine = _engine(tmp_path)
    a, b = PostgresRateLimiter(3, engine), PostgresRateLimiter(3, engine)  # two API processes, one database
    t = 1_000_000.0
    assert [a.allow("t1", now=t), b.allow("t1", now=t), a.allow("t1", now=t)] == [True, True, True]
    assert b.allow("t1", now=t) is False  # shared count, not per process
    assert a.allow("t2", now=t) is True  # other tenants have their own count
    assert a.allow("t1", now=t + 61) is True  # next minute window


def test_backend_selection(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    monkeypatch.delenv("RATE_LIMIT_BACKEND", raising=False)
    assert type(make_limiter(5, None, engine)).__name__ == "RateLimiter"
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "postgres")
    assert isinstance(make_limiter(5, None, engine), PostgresRateLimiter)
