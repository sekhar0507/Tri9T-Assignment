import os, json, hashlib, difflib, re
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from .models import DocumentVersion, SectionNode, SavedSelection, SelectionItem, GenerationRecord
from .parser import parse_pdf, digest
from .config import GENERATIONS_STORE
from .llm import call_llm, validate_cases

def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()

def latest_version(db, document_key="ct200"):
    return db.scalar(select(DocumentVersion).where(DocumentVersion.document_key == document_key).order_by(desc(DocumentVersion.version_number)))

def ingest_pdf(db: Session, path: str, document_key="ct200"):
    file_hash = sha_file(path)
    existing = db.scalar(select(DocumentVersion).where(DocumentVersion.document_key == document_key, DocumentVersion.source_sha256 == file_hash))
    if existing:
        return existing, {"unchanged": len(existing.nodes), "changed": 0, "added": 0, "removed": 0}, True
    prev = latest_version(db, document_key)
    version_number = prev.version_number + 1 if prev else 1
    parsed = parse_pdf(path)
    version = DocumentVersion(document_key=document_key, version_number=version_number,
                              source_filename=Path(path).name, source_sha256=file_hash)
    db.add(version); db.flush()
    key_to_db = {}
    for p in parsed:
        # Parent IDs are assigned after every node is inserted.
        row = SectionNode(version_id=version.id, logical_key=p.logical_key, heading=p.heading,
                          section_number=p.section_number, level=p.level, body_text=p.body_text,
                          content_hash=p.content_hash)
        db.add(row); db.flush()
        key_to_db[p.logical_key] = row
    for p in parsed:
        row = key_to_db[p.logical_key]
        if p.parent_key and p.parent_key in key_to_db:
            row.parent_id = key_to_db[p.parent_key].id
    db.flush()
    counts = {"unchanged": 0, "changed": 0, "added": 0, "removed": 0}
    if prev:
        old = {n.logical_key: n for n in prev.nodes}
        new = {n.logical_key: n for n in version.nodes}
        for k, n in new.items():
            if k not in old: counts["added"] += 1
            elif n.content_hash == old[k].content_hash: counts["unchanged"] += 1
            else: counts["changed"] += 1
        counts["removed"] = len(set(old) - set(new))
    else:
        counts["added"] = len(version.nodes)
    db.commit(); db.refresh(version)
    return version, counts, False

def node_to_dict(node, db, include_children=True):
    data = {"id": node.id, "version_id": node.version_id, "logical_key": node.logical_key,
            "heading": node.heading, "section_number": node.section_number, "level": node.level,
            "body_text": node.body_text, "content_hash": node.content_hash, "parent_id": node.parent_id}
    if include_children:
        data["children"] = [node_to_dict(c, db, True) for c in sorted(node.children, key=lambda x: x.id)]
    return data

def changed_status(db, node: SectionNode):
    versions = list(db.scalars(select(SectionNode).where(SectionNode.logical_key == node.logical_key)
                               .order_by(SectionNode.version_id)).all())
    if len(versions) <= 1:
        return {"changed": False, "status": "no_comparison", "message": "No earlier/later version exists for this logical node."}
    latest = versions[-1]
    base = versions[0]
    return {"changed": base.content_hash != latest.content_hash,
            "status": "changed" if base.content_hash != latest.content_hash else "unchanged",
            "compared_from_version_id": base.version_id, "compared_to_version_id": latest.version_id,
            "diff": list(difflib.unified_diff(base.body_text.splitlines(), latest.body_text.splitlines(),
                    fromfile=f"version-{base.version_id}", tofile=f"version-{latest.version_id}", lineterm=""))[:30]}

def create_selection(db, name, node_ids):
    rows = list(db.scalars(select(SectionNode).where(SectionNode.id.in_(node_ids))).all())
    if len(rows) != len(set(node_ids)):
        raise ValueError("One or more node IDs do not exist.")
    versions = {n.version_id for n in rows}
    if len(versions) != 1:
        raise ValueError("All selected nodes must belong to the same document version.")
    version = db.get(DocumentVersion, next(iter(versions)))
    selection = SavedSelection(name=name, document_key=version.document_key, version_id=version.id)
    db.add(selection); db.flush()
    for n in rows:
        db.add(SelectionItem(selection_id=selection.id, node_id=n.id, version_id=n.version_id,
             logical_key_snapshot=n.logical_key, heading_snapshot=n.heading,
             body_snapshot=n.body_text, content_hash_snapshot=n.content_hash))
    db.commit(); db.refresh(selection)
    return selection

def selection_text(selection):
    return "\n\n".join(f"## {i.heading_snapshot}\n{i.body_snapshot}" for i in selection.items)

def current_staleness(db, selection):
    latest = latest_version(db, selection.document_key)
    stale_items = []
    if not latest:
        return {"stale": True, "items": [], "reason": "No current document version"}
    current = {n.logical_key: n for n in latest.nodes}
    for item in selection.items:
        now = current.get(item.logical_key_snapshot)
        if now is None:
            stale_items.append({"logical_key": item.logical_key_snapshot, "status": "removed"})
        elif now.content_hash != item.content_hash_snapshot:
            stale_items.append({"logical_key": item.logical_key_snapshot, "status": "changed",
                "old_hash": item.content_hash_snapshot, "current_hash": now.content_hash})
    return {"stale": bool(stale_items), "selection_version_id": selection.version_id,
            "current_version_id": latest.id, "items": stale_items}

def generate_for_selection(db, selection, force=False):
    # Idempotency policy: return prior generation for the same selection unless force=true.
    if not force:
        prior = db.scalar(select(GenerationRecord).where(GenerationRecord.selection_id == selection.id)
                          .order_by(desc(GenerationRecord.id)))
        if prior:
            return prior, True
    source = selection_text(selection)
    cases, provider, warnings = call_llm(source)
    valid, validation_warnings = validate_cases(cases)
    warnings.extend(validation_warnings)
    payload = {"test_cases": valid}
    record = GenerationRecord(selection_id=selection.id, provider=provider,
        status="validated" if valid and not validation_warnings else ("partial" if valid else "failed"),
        source_hashes_json=json.dumps([i.content_hash_snapshot for i in selection.items]),
        result_json=json.dumps(payload, ensure_ascii=False), validation_warnings_json=json.dumps(warnings))
    db.add(record); db.commit(); db.refresh(record)
    # JSON store mirrors generated artifacts separately from relational traceability metadata.
    os.makedirs(GENERATIONS_STORE, exist_ok=True)
    with open(os.path.join(GENERATIONS_STORE, f"generation_{record.id}.json"), "w", encoding="utf-8") as f:
        json.dump({"generation_id": record.id, "selection_id": selection.id, "source_hashes":
                   [i.content_hash_snapshot for i in selection.items], "provider": provider,
                   "status": record.status, "result": payload, "warnings": warnings}, f, indent=2)
    return record, False
