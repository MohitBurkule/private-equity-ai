import io
import zipfile

from sqlalchemy.orm import Session

from app.db import Base, make_engine
from app.ingest import ingest_any


def _zip(names_and_bodies):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, body in names_and_bodies:
            z.writestr(n, body)
    return b.getvalue()


def test_archive_reports_each_member_before_it_is_read():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    seen = []
    data = _zip([("a.txt", "one"), ("b.txt", "two"), ("c.txt", "three")])
    with Session(engine) as s:
        ingest_any(s, "t", data, "room.zip", progress=lambda d, t, n: seen.append((d, t, n)))
    assert seen == [(0, 3, "a.txt"), (1, 3, "b.txt"), (2, 3, "c.txt")]


def test_nested_archive_does_not_report_its_members():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    seen = []
    inner = _zip([("x.txt", "x")])
    data = _zip([("inner.zip", inner), ("y.txt", "y")])
    with Session(engine) as s:
        ingest_any(s, "t", data, "room.zip", progress=lambda d, t, n: seen.append(n))
    assert seen == ["inner.zip", "y.txt"]
