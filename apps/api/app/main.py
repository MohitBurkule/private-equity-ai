from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import Base, make_engine, make_session_factory
from app.ingest import ingest_bytes
from app.models import Document, PageRow

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
        doc = ingest_bytes(db, data, file.filename or "upload.pdf")
    except Exception as e:  # corrupt / encrypted / empty PDFs are flagged, never skipped
        raise HTTPException(422, f"cannot parse PDF: {e}") from e
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
