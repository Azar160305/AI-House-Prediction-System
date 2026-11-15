"""Chunked, disk-backed ingestion for large job-market CSV uploads."""
from pathlib import Path
import sqlite3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from .data_cleaning import ALIAS_LOOKUP, _key, normalize_columns

CHUNK_ROWS = 50_000

def inspect_job_csv(path):
    """Return raw headers and raise a helpful error for unrelated CSV files."""
    path=Path(path)
    try:
        headers=pd.read_csv(path,nrows=0,encoding_errors="replace").columns.tolist()
    except Exception as exc:
        raise ValueError(f"Could not read the CSV header: {exc}") from exc
    if not headers:
        raise ValueError("The CSV has no column headers.")
    canonical={ALIAS_LOOKUP.get(_key(col)) for col in headers}
    canonical.discard(None)
    has_job_field=bool(canonical.intersection({"job_title","job_description","required_skills"}))
    has_context=bool(canonical.intersection({"company_name","company_id","location","country","experience_level","employment_type","industry","minimum_salary","maximum_salary","average_salary"}))
    if not (has_job_field and has_context):
        raise ValueError("This CSV does not appear to contain useful job-market data. Include a job title, description, or skills field plus a location, company, experience, industry, employment type, or salary field.")
    return headers

def _useful_columns(headers):
    selected=[]; seen=set()
    for col in headers:
        canonical=ALIAS_LOOKUP.get(_key(col))
        if canonical and canonical not in seen:
            selected.append(col); seen.add(canonical)
    return selected

def _dedupe_keys(frame):
    ids=frame["posting_id"].astype("string[pyarrow]")
    id_keys="id:"+ids
    identity=[c for c in ("job_title","company_name","company_id","location","posting_date","required_skills","minimum_salary","maximum_salary") if c in frame]
    row_hash=pd.util.hash_pandas_object(frame[identity],index=False).astype("uint64").astype("string[pyarrow]")
    return id_keys.where(ids.notna(),"row:"+row_hash)

def _keep_first_chunk_occurrence(frame,connection):
    keys=_dedupe_keys(frame)
    unique=keys.drop_duplicates().tolist()
    cursor=connection.cursor()
    cursor.execute("DELETE FROM incoming_keys")
    cursor.executemany("INSERT OR IGNORE INTO incoming_keys(key) VALUES (?)",((str(key),) for key in unique))
    new_keys={row[0] for row in cursor.execute("SELECT incoming_keys.key FROM incoming_keys LEFT JOIN seen_keys USING(key) WHERE seen_keys.key IS NULL")}
    cursor.execute("INSERT OR IGNORE INTO seen_keys(key) SELECT key FROM incoming_keys")
    connection.commit()
    return frame.loc[keys.isin(new_keys)]

def process_large_csv(source_path,parquet_path,on_progress=None,chunk_rows=CHUNK_ROWS):
    """Read CSV chunks, normalize/deduplicate, then load one Arrow-backed frame.

    The source remains unchanged. The full normalized frame is not cached by
    Streamlit; intermediate row batches are written to a Parquet cache on disk.
    """
    source_path=Path(source_path); parquet_path=Path(parquet_path)
    if not source_path.is_file(): raise FileNotFoundError(f"CSV file not found: {source_path}")
    headers=inspect_job_csv(source_path); selected=_useful_columns(headers)
    if not selected: raise ValueError("No recognized job-market columns were found.")
    parquet_path.parent.mkdir(parents=True,exist_ok=True)
    temp_path=parquet_path.with_suffix(parquet_path.suffix+".tmp")
    seen_path=parquet_path.with_suffix(".seen.sqlite")
    writer=None; rows_written=0; seen=None
    try:
        seen=sqlite3.connect(seen_path)
        seen.execute("CREATE TABLE IF NOT EXISTS seen_keys (key TEXT PRIMARY KEY)")
        seen.execute("CREATE TEMP TABLE incoming_keys (key TEXT PRIMARY KEY)")
        reader=pd.read_csv(source_path,usecols=selected,chunksize=chunk_rows,low_memory=True,memory_map=True,dtype_backend="pyarrow",encoding_errors="replace",on_bad_lines="warn")
        for chunk_number,raw in enumerate(reader,start=1):
            frame=normalize_columns(raw)
            frame=_keep_first_chunk_occurrence(frame,seen)
            if frame.empty: continue
            # Stable Arrow string types avoid per-chunk category dictionaries in Parquet.
            for col in frame.select_dtypes(include="category").columns:
                frame[col]=frame[col].astype("string[pyarrow]")
            table=pa.Table.from_pandas(frame,preserve_index=False)
            if writer is None: writer=pq.ParquetWriter(temp_path,table.schema,compression="zstd",use_dictionary=True)
            else: table=table.cast(writer.schema)
            writer.write_table(table,row_group_size=chunk_rows)
            rows_written+=len(frame)
            if on_progress: on_progress(rows_written,chunk_number)
        if writer is not None: writer.close(); writer=None
        if rows_written==0: raise ValueError("The CSV contains no usable job-posting records.")
        temp_path.replace(parquet_path)
    except Exception:
        if writer is not None: writer.close()
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        if seen is not None: seen.close()
        seen_path.unlink(missing_ok=True)
    result=pd.read_parquet(parquet_path,dtype_backend="pyarrow")
    return result,headers
