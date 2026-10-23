from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, or_
from pathlib import Path
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import tempfile, os, json
from .database import Base, engine, get_db
from .models import DocumentVersion, SectionNode, SavedSelection, GenerationRecord
from .schemas import SelectionCreate, IngestResponse, GenerationResponse, TestCase
from .service import ingest_pdf, latest_version, node_to_dict, changed_status, create_selection, current_staleness, generate_for_selection

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Tri9T CT-200 Document QA API", version="1.0.0",
 description="Versioned PDF hierarchy, pinned selections, QA generation, and staleness detection.")
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def frontend():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

@app.get("/health")
def health():
    return {"status":"ok","service":"tri9t-ct200"}

@app.post("/documents/{document_key}/ingest", response_model=IngestResponse)
async def ingest(document_key: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted.")
    data = await file.read()
    if not data: raise HTTPException(400, "Uploaded PDF is empty.")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    try:
        tmp.write(data); tmp.close()
        version, counts, duplicate = ingest_pdf(db, tmp.name, document_key)
        return {"document_key":document_key,"version_id":version.id,"version_number":version.version_number,
                "node_count":len(version.nodes),"source_sha256":version.source_sha256,
                "changes":{**counts,"duplicate_upload":int(duplicate)}}
    except Exception as e:
        db.rollback()
        raise HTTPException(422, f"Ingestion failed visibly: {type(e).__name__}: {e}")
    finally:
        try: os.unlink(tmp.name)
        except OSError: pass

@app.post("/documents/{document_key}/ingest/sample-v1", response_model=IngestResponse)
def ingest_sample_v1(document_key: str = "ct200", db: Session = Depends(get_db)):
    path=Path(__file__).resolve().parents[1] / "data" / "ct200_manual.pdf"
    if not path.exists(): raise HTTPException(404, f"Sample PDF not found at {path.resolve()}")
    version, counts, duplicate=ingest_pdf(db,str(path),document_key)
    return {"document_key":document_key,"version_id":version.id,"version_number":version.version_number,
            "node_count":len(version.nodes),"source_sha256":version.source_sha256,
            "changes":{**counts,"duplicate_upload":int(duplicate)}}

@app.post("/documents/{document_key}/ingest/sample-v2", response_model=IngestResponse)
def ingest_sample_v2(document_key: str = "ct200", db: Session = Depends(get_db)):
    path=Path(__file__).resolve().parents[1] / "data" / "ct200_manual_v2.pdf"
    if not path.exists(): raise HTTPException(404, f"Sample PDF not found at {path.resolve()}")
    version, counts, duplicate=ingest_pdf(db,str(path),document_key)
    return {"document_key":document_key,"version_id":version.id,"version_number":version.version_number,
            "node_count":len(version.nodes),"source_sha256":version.source_sha256,
            "changes":{**counts,"duplicate_upload":int(duplicate)}}

@app.get("/documents/{document_key}/versions")
def versions(document_key: str, db: Session=Depends(get_db)):
    rows=db.scalars(select(DocumentVersion).where(DocumentVersion.document_key==document_key).order_by(DocumentVersion.version_number)).all()
    return [{"id":v.id,"version_number":v.version_number,"source_filename":v.source_filename,
             "source_sha256":v.source_sha256,"created_at":v.created_at} for v in rows]

@app.get("/documents/{document_key}/sections")
def top_sections(document_key: str, version: int | None=Query(default=None, description="Version number; defaults to latest"), db: Session=Depends(get_db)):
    ver = db.scalar(select(DocumentVersion).where(DocumentVersion.document_key==document_key,
        DocumentVersion.version_number==version)) if version is not None else latest_version(db,document_key)
    if not ver: raise HTTPException(404,"Document version not found.")
    roots=db.scalars(select(SectionNode).where(SectionNode.version_id==ver.id, SectionNode.parent_id==None).order_by(SectionNode.id)).all()
    return {"document_key":document_key,"version_number":ver.version_number,"sections":[node_to_dict(n,db) for n in roots]}

@app.get("/documents/{document_key}/compare")
def compare_versions(document_key: str, from_version: int = Query(1, ge=1),
                     to_version: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    versions = db.scalars(select(DocumentVersion).where(
        DocumentVersion.document_key == document_key).order_by(DocumentVersion.version_number)).all()
    target = to_version if to_version is not None else (versions[-1].version_number if versions else None)
    old_v = next((v for v in versions if v.version_number == from_version), None)
    new_v = next((v for v in versions if v.version_number == target), None)
    if not old_v or not new_v:
        raise HTTPException(404, "Requested source or target version does not exist.")
    old = {n.logical_key: n for n in old_v.nodes}
    new = {n.logical_key: n for n in new_v.nodes}
    changes = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a is None:
            status = "added"
        elif b is None:
            status = "removed"
        elif a.content_hash != b.content_hash:
            status = "changed"
        else:
            status = "unchanged"
        if status != "unchanged":
            import difflib
            changes.append({"logical_key": key, "status": status,
                "old_heading": a.heading if a else None, "new_heading": b.heading if b else None,
                "old_node_id": a.id if a else None, "new_node_id": b.id if b else None,
                "diff": list(difflib.unified_diff((a.body_text if a else "").splitlines(),
                    (b.body_text if b else "").splitlines(), fromfile=f"v{from_version}", tofile=f"v{target}",
                    lineterm=""))[:30]})
    return {"document_key": document_key, "from_version": from_version, "to_version": target,
            "summary": {"unchanged": sum(1 for k in set(old)&set(new) if old[k].content_hash == new[k].content_hash),
                        "changed": sum(1 for k in set(old)&set(new) if old[k].content_hash != new[k].content_hash),
                        "added": len(set(new)-set(old)), "removed": len(set(old)-set(new))},
            "changes": changes}

@app.get("/nodes/{node_id}")
def get_node(node_id:int, db:Session=Depends(get_db)):
    node=db.get(SectionNode,node_id)
    if not node: raise HTTPException(404,"Node not found.")
    return node_to_dict(node,db)

@app.get("/documents/{document_key}/search")
def search_nodes(document_key:str, q:str=Query(min_length=1), version:int|None=None, db:Session=Depends(get_db)):
    ver = db.scalar(select(DocumentVersion).where(DocumentVersion.document_key==document_key,
        DocumentVersion.version_number==version)) if version is not None else latest_version(db,document_key)
    if not ver: raise HTTPException(404,"Document version not found.")
    rows=db.scalars(select(SectionNode).where(SectionNode.version_id==ver.id,
       or_(SectionNode.heading.ilike(f"%{q}%"),SectionNode.body_text.ilike(f"%{q}%"))).order_by(SectionNode.id)).all()
    return {"version_number":ver.version_number,"query":q,"results":[node_to_dict(n,db,False) for n in rows]}

@app.get("/nodes/{node_id}/changes")
def node_changes(node_id:int, db:Session=Depends(get_db)):
    node=db.get(SectionNode,node_id)
    if not node: raise HTTPException(404,"Node not found.")
    return {"node_id":node_id,"logical_key":node.logical_key,**changed_status(db,node)}

@app.post("/selections")
def save_selection(body:SelectionCreate, db:Session=Depends(get_db)):
    try:
        selection=create_selection(db,body.name,body.node_ids)
        return {"selection_id":selection.id,"name":selection.name,"document_key":selection.document_key,
                "version_id":selection.version_id,"node_ids":[i.node_id for i in selection.items],
                "pinned":True}
    except ValueError as e: raise HTTPException(400,str(e))

@app.get("/selections")
def list_selections(db: Session = Depends(get_db)):
    rows = db.scalars(select(SavedSelection).order_by(desc(SavedSelection.id))).all()
    return [{"selection_id": s.id, "name": s.name, "document_key": s.document_key,
             "version_id": s.version_id, "node_ids": [i.node_id for i in s.items],
             "created_at": s.created_at} for s in rows]

@app.get("/selections/{selection_id}")
def get_selection(selection_id:int, db:Session=Depends(get_db)):
    selection=db.get(SavedSelection,selection_id)
    if not selection: raise HTTPException(404,"Selection not found.")
    return {"selection_id":selection.id,"name":selection.name,"version_id":selection.version_id,
       "items":[{"node_id":i.node_id,"logical_key":i.logical_key_snapshot,"heading":i.heading_snapshot,
                 "body_text":i.body_snapshot,"content_hash":i.content_hash_snapshot} for i in selection.items],
       "staleness":current_staleness(db,selection)}

@app.post("/selections/{selection_id}/generate", response_model=GenerationResponse)
def generate(selection_id:int, force:bool=False, db:Session=Depends(get_db)):
    selection=db.get(SavedSelection,selection_id)
    if not selection: raise HTTPException(404,"Selection not found.")
    record, reused=generate_for_selection(db,selection,force)
    payload=json.loads(record.result_json)
    return {"generation_id":record.id,"selection_id":selection_id,"provider":record.provider,
       "status":record.status,"test_cases":payload.get("test_cases",[]),
       "warnings":json.loads(record.validation_warnings_json)+([ "Existing generation reused (idempotency policy)." ] if reused else []),
       "staleness":current_staleness(db,selection)}

@app.get("/generations/{generation_id}")
def get_generation(generation_id:int, db:Session=Depends(get_db)):
    record=db.get(GenerationRecord,generation_id)
    if not record: raise HTTPException(404,"Generation not found.")
    selection=db.get(SavedSelection,record.selection_id)
    stored_hashes=json.loads(record.source_hashes_json)
    current=current_staleness(db,selection)
    return {"generation_id":record.id,"selection_id":record.selection_id,"created_at":record.created_at,
       "provider":record.provider,"status":record.status,"test_cases":json.loads(record.result_json).get("test_cases",[]),
       "source_hashes":stored_hashes,"staleness":current,
       "warnings":json.loads(record.validation_warnings_json)}

@app.get("/selections/{selection_id}/generations")
def list_generations(selection_id:int, db:Session=Depends(get_db)):
    if not db.get(SavedSelection,selection_id): raise HTTPException(404,"Selection not found.")
    rows=db.scalars(select(GenerationRecord).where(GenerationRecord.selection_id==selection_id).order_by(desc(GenerationRecord.id))).all()
    return [{"generation_id":r.id,"created_at":r.created_at,"provider":r.provider,"status":r.status,
             "staleness":current_staleness(db,db.get(SavedSelection,r.selection_id))} for r in rows]
