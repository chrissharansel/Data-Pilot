"""Turns uploaded files into (a) LangChain Documents for RAG and (b) a profile for tabular data."""
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings

TABULAR = {".csv", ".xlsx", ".xls"}
TEXTUAL = {".pdf", ".txt", ".md", ".docx"}
SUPPORTED = TABULAR | TEXTUAL


@dataclass
class ParsedFile:
    kind: str                                 # "tabular" | "document"
    documents: list[Document] = field(default_factory=list)
    profile: dict | None = None               # per-sheet stats for tabular files
    pages: int | None = None


def _jsonable(v):
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if np.isnan(v) else float(v)
    if v is None or (not isinstance(v, (str, bytes)) and pd.isna(v)):
        return None
    return v if isinstance(v, (int, float, bool, str)) else str(v)


def profile_frame(df: pd.DataFrame, name: str) -> dict:
    cols = [{"name": str(c), "dtype": str(df[c].dtype), "nulls": int(df[c].isna().sum()),
             "unique": int(df[c].nunique(dropna=True))} for c in df.columns]
    numeric = df.select_dtypes(include="number")
    stats = {}
    if not numeric.empty:
        desc = numeric.describe().T
        stats = {str(i): {k: _jsonable(v) for k, v in row.items()} for i, row in desc.iterrows()}
    preview = [{str(k): _jsonable(v) for k, v in r.items()} for r in df.head(10).to_dict("records")]
    return {"sheet": name, "rows": int(len(df)), "columns": cols, "numeric_stats": stats, "preview": preview}


def _frame_to_documents(df: pd.DataFrame, filename: str, sheet: str) -> list[Document]:
    label = filename + (f" [{sheet}]" if sheet else "")
    p = profile_frame(df, sheet)
    summary = [f"Dataset {label}: {p['rows']} rows, {len(p['columns'])} columns.",
               "Columns: " + "; ".join(f"{c['name']} ({c['dtype']}, {c['nulls']} nulls, {c['unique']} unique)" for c in p["columns"])]
    for col, st in p["numeric_stats"].items():
        summary.append(f"{col}: min={st.get('min')}, mean={st.get('mean')}, max={st.get('max')}, std={st.get('std')}")
    docs = [Document(page_content="\n".join(summary),
                     metadata={"filename": filename, "location": f"{sheet or 'data'} summary", "type": "summary"})]

    capped, n = df.head(settings.max_embedded_rows), settings.rows_per_chunk
    for start in range(0, len(capped), n):
        block = capped.iloc[start:start + n]
        loc = f"{sheet + ' ' if sheet else ''}rows {start + 1}-{start + len(block)}"
        docs.append(Document(page_content=f"{label} {loc}\n" + block.to_csv(index=False),
                             metadata={"filename": filename, "location": loc, "type": "rows"}))
    return docs


def _split(text: str, filename: str, location: str) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    return [Document(page_content=t, metadata={"filename": filename, "location": location, "type": "text"})
            for t in splitter.split_text(text) if t.strip()]


def parse_file(path: Path, original_name: str) -> ParsedFile:
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED))}")

    if ext == ".csv":
        df = pd.read_csv(path, encoding_errors="replace")
        return ParsedFile("tabular", _frame_to_documents(df, original_name, ""), {"sheets": [profile_frame(df, "data")]})

    if ext in {".xlsx", ".xls"}:
        docs, profiles = [], []
        for name, df in pd.read_excel(path, sheet_name=None).items():
            docs += _frame_to_documents(df, original_name, str(name))
            profiles.append(profile_frame(df, str(name)))
        return ParsedFile("tabular", docs, {"sheets": profiles})

    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        docs: list[Document] = []
        for i, page in enumerate(reader.pages, start=1):
            docs += _split(page.extract_text() or "", original_name, f"page {i}")
        return ParsedFile("document", docs, pages=len(reader.pages))

    if ext == ".docx":
        import docx
        text = "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
        return ParsedFile("document", _split(text, original_name, "document"))

    return ParsedFile("document", _split(path.read_text(encoding="utf-8", errors="replace"), original_name, "text"))
