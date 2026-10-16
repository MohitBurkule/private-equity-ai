from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import Base, make_engine, make_session_factory
from app.facts import CitationError, add_verified_fact
from app.ingest import ingest_upload
from app.memo import build_memo
from app.models import Document, PageRow
from app.search import PageIndex

engine = make_engine()
SessionLocal = make_session_factory(engine)
Base.metadata.create_all(engine)

app = FastAPI(title="PE Platform API", version="0.0.1")


def get_db():
    with SessionLocal() as s:
        yield s


Db = Annotated[Session, Depends(get_db)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/documents")
async def upload(file: Annotated[UploadFile, File()], db: Db):
    data = await file.read()
    try:
        doc = ingest_upload(db, data, file.filename or "upload.pdf")
    except Exception as e:  # corrupt / encrypted / empty PDFs are flagged, never skipped
        raise HTTPException(422, f"cannot parse file: {e}") from e
    return {"id": doc.id, "filename": doc.filename, "n_pages": doc.n_pages}


@app.get("/documents/{doc_id}/pages/{number}")
def get_page(doc_id: str, number: int, db: Db):
    row = (db.query(PageRow).filter_by(document_id=doc_id, number=number).one_or_none())
    if row is None:
        raise HTTPException(404, "page not found")
    return {"document_id": doc_id, "page": number, "text": row.text}


@app.get("/documents")
def list_documents(db: Db):
    return [{"id": d.id, "filename": d.filename, "n_pages": d.n_pages}
            for d in db.query(Document).all()]


class FactIn(BaseModel):
    entity: str
    metric: str
    period: str
    value: Decimal
    unit: str
    document_id: str
    page: int
    quote: str
    scale: Decimal = Decimal(1)
    basis: str = "GAAP"


@app.post("/facts", status_code=201)
def create_fact(body: FactIn, db: Db):
    try:
        f = add_verified_fact(db, **body.model_dump())
    except CitationError as e:
        raise HTTPException(422, str(e)) from e
    return {"id": f.id, "status": f.status}


@app.get("/memo")
def memo(entity: str, db: Db):
    return {"entity": entity, "markdown": build_memo(db, entity)}


@app.get("/search")
def search(q: str, db: Db, doc_id: str | None = None, k: int = 5):
    query = db.query(PageRow)
    if doc_id:
        query = query.filter_by(document_id=doc_id)
    rows = query.all()
    index = PageIndex([(r.document_id, r.number, r.text) for r in rows])
    text = {(r.document_id, r.number): r.text for r in rows}
    return [{"document_id": h.doc_id, "page": h.page, "score": round(h.score, 3),
             "snippet": text[(h.doc_id, h.page)][:300]}
            for h in index.search(q, k=k, doc_ids={doc_id} if doc_id else None)]
