from app.parser import parse_pdf, digest, ParsedNode
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

def test_v1_v2_both_parse_and_have_document_root():
    v1=parse_pdf(str(DATA/"ct200_manual.pdf"))
    v2=parse_pdf(str(DATA/"ct200_manual_v2.pdf"))
    assert v1 and v2
    assert v1[0].logical_key == "document"
    assert any(n.section_number == "2.1.1.1" for n in v1)
    assert any(n.section_number == "2.1.1.1" for n in v2)

def test_out_of_order_sections_are_kept_in_source_order_not_dropped():
    nodes=parse_pdf(str(DATA/"ct200_manual.pdf"))
    keys=[n.section_number for n in nodes]
    assert "3.4" in keys and "3.3" in keys
    assert keys.index("3.4") < keys.index("3.3")

def test_missing_intermediate_parent_attaches_to_nearest_existing_ancestor():
    nodes=parse_pdf(str(DATA/"ct200_manual.pdf"))
    target=next(n for n in nodes if n.section_number=="2.1.1.1")
    by_key={n.logical_key:n for n in nodes}
    assert target.parent_key=="2.1"
    assert by_key[target.parent_key].section_number=="2.1"

def test_content_hash_changes_when_threshold_text_changes():
    assert digest("battery below 15%") != digest("battery below 10%")

def test_v2_has_structural_additions_and_changed_content():
    v1=parse_pdf(str(DATA/"ct200_manual.pdf")); v2=parse_pdf(str(DATA/"ct200_manual_v2.pdf"))
    a={n.logical_key:n for n in v1}; b={n.logical_key:n for n in v2}
    assert any(k in a and k in b and a[k].content_hash != b[k].content_hash for k in a)
    assert any(k not in a for k in b)
