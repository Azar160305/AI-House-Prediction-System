"""Memory-aware CSV ingestion and LinkedIn job-postings normalization."""
from pathlib import Path
import re
import pandas as pd

ALIASES = {
    "posting_id": ["job_id", "posting id", "id"],
    "job_title": ["title", "job title", "job_title", "role", "position"],
    "company_name": ["company name", "company", "company_name", "employer"],
    "company_id": ["company_id", "company id"],
    "location": ["location", "job location", "city"],
    "country": ["country", "country code"],
    "experience_level": ["formatted experience level", "experience level", "seniority", "experience", "level"],
    "employment_type": ["formatted work type", "employment type", "employment_type", "work type", "type"],
    "required_skills": ["required skills", "skills", "skill", "skills desc", "technical skills", "required_skills"],
    "minimum_salary": ["minimum salary", "min salary", "min_salary", "salary min", "salary_min"],
    "maximum_salary": ["maximum salary", "max salary", "max_salary", "salary max", "salary_max"],
    "average_salary": ["average salary", "avg salary", "med salary", "median salary", "salary", "average_salary"],
    "salary_currency": ["currency", "salary currency", "salary_currency"],
    "salary_period": ["pay period", "salary period", "pay_period", "salary_period"],
    "industry": ["industry", "sector"],
    "job_description": ["job description", "description", "job_description"],
    "remote_status": ["remote status", "remote", "remote allowed", "remote_allowed", "work mode", "remote_status"],
    "posting_date": ["posting date", "date posted", "posted date", "listed time", "original listed time", "posted", "posting_date"],
}

def _key(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()

ALIAS_LOOKUP = {_key(alias): canonical for canonical, aliases in ALIASES.items() for alias in aliases}

def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Standardize common LinkedIn and generic job-posting column names."""
    rename, seen = {}, set()
    for col in frame.columns:
        canonical = ALIAS_LOOKUP.get(_key(col))
        if canonical and canonical not in seen:
            rename[col] = canonical
            seen.add(canonical)
    df = frame.rename(columns=rename).copy()
    text_columns = ["posting_id", "job_title", "company_name", "company_id", "location", "country", "experience_level", "employment_type", "required_skills", "salary_currency", "salary_period", "industry", "job_description", "remote_status", "posting_date"]
    for col in text_columns:
        if col not in df:
            df[col] = pd.NA
        df[col] = df[col].astype("string[pyarrow]").str.strip().replace("", pd.NA)
    for col in ("job_title", "company_name", "location", "country", "experience_level", "employment_type", "salary_currency", "salary_period", "industry", "remote_status"):
        df[col] = df[col].fillna("Unknown")
    for col in ("required_skills", "job_description"):
        df[col] = df[col].fillna("")
    for col in ("minimum_salary", "maximum_salary", "average_salary"):
        if col not in df:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col].astype("string[pyarrow]").str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce").astype("float32")
    # Use reported median, else the mean of the two reported bounds; never invent a salary.
    df["average_salary"] = df["average_salary"].fillna((df["minimum_salary"] + df["maximum_salary"]) / 2)
    df["salary_currency"] = df["salary_currency"].fillna("Unknown").str.upper()
    df["salary_period"] = df["salary_period"].fillna("Unknown").str.upper()
    exp = df["experience_level"].str.lower()
    df["experience_level"] = df["experience_level"].mask(exp.str.contains("intern", na=False), "Internship")
    df["experience_level"] = df["experience_level"].mask(exp.str.contains("entry|associate", na=False), "Entry / Associate")
    df["experience_level"] = df["experience_level"].mask(exp.str.contains("mid|senior", na=False), "Mid / Senior")
    df["experience_level"] = df["experience_level"].mask(exp.str.contains("director", na=False), "Director")
    df["experience_level"] = df["experience_level"].mask(exp.str.contains("executive", na=False), "Executive")
    remote = df["remote_status"].str.lower()
    df["remote_status"] = df["remote_status"].mask(remote.isin(["1", "1.0", "true", "yes"]), "Remote")
    df["remote_status"] = df["remote_status"].mask(remote.isin(["0", "0.0", "false", "no"]), "Not marked remote")
    raw_date = df["posting_date"]
    numeric_date = pd.to_numeric(raw_date, errors="coerce")
    if numeric_date.notna().mean() > .8 and numeric_date.notna().any():
        magnitude = numeric_date.dropna().abs().median()
        unit = "ms" if magnitude >= 1e11 else "s" if magnitude >= 1e8 else None
        dates = pd.to_datetime(numeric_date, unit=unit, errors="coerce", utc=True) if unit else pd.to_datetime(raw_date, errors="coerce", utc=True)
    else:
        dates = pd.to_datetime(raw_date, errors="coerce", utc=True)
    df["posting_date"] = dates.dt.tz_localize(None)
    if df["posting_id"].notna().any():
        valid_ids = df["posting_id"].notna()
        duplicate_id = valid_ids & df["posting_id"].duplicated(keep="first")
        df = df.loc[~duplicate_id]
    else:
        identity = [c for c in ("job_title", "company_name", "company_id", "location", "posting_date") if df[c].notna().any() and (c == "posting_date" or (df[c].astype("string") != "Unknown").any())]
        if identity:
            df = df.drop_duplicates(subset=identity, keep="first")
    for col in ("experience_level", "employment_type", "salary_currency", "salary_period", "industry", "remote_status", "country"):
        if df[col].nunique(dropna=True) < 500:
            df[col] = df[col].astype("category")
    return df.reset_index(drop=True)

def load_dataset(path: str | Path) -> pd.DataFrame:
    """Read recognized columns only, with Arrow strings and low-memory CSV parsing."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Job postings CSV was not found at: {path}")
    if path.suffix.lower() != ".csv":
        raise ValueError("Local dataset must be a CSV file.")
    header = pd.read_csv(path, nrows=0, encoding_errors="replace").columns.tolist()
    wanted, seen = [], set()
    for col in header:
        canonical = ALIAS_LOOKUP.get(_key(col))
        if canonical and canonical not in seen:
            wanted.append(col)
            seen.add(canonical)
    if not wanted:
        raise ValueError("No recognized job-posting columns were found in the CSV header.")
    df = pd.read_csv(path, usecols=wanted, low_memory=True, memory_map=True, dtype_backend="pyarrow", encoding_errors="replace", on_bad_lines="warn")
    if df.empty:
        raise ValueError("The job postings CSV contains no data rows.")
    return normalize_columns(df)
