"""Vectorized descriptive analysis helpers for large job-posting tables."""
import re
import pandas as pd

SKILL_TERMS = ["python", "sql", "excel", "power bi", "tableau", "aws", "azure", "gcp", "machine learning", "deep learning", "pytorch", "tensorflow", "spark", "snowflake", "docker", "kubernetes", "java", "javascript", "react", "git", "linux", "statistics", "r", "pandas", "scikit-learn"]

def top_skills(df, n=10):
    skills = df["required_skills"].fillna("").astype("string[pyarrow]").str.lower()
    desc = df["job_description"].fillna("").astype("string[pyarrow]").str.lower()
    text = skills.where(skills.str.len() > 0, desc)
    records=[]
    salaries=pd.to_numeric(df["average_salary"],errors="coerce")
    for skill in SKILL_TERMS:
        pattern=r"(?:^|[^a-z0-9])"+re.escape(skill)+r"(?:$|[^a-z0-9])"
        found=text.str.contains(pattern,regex=True,na=False)
        count=int(found.sum())
        if count:
            records.append({"skill":skill,"postings":count,"average_salary":salaries[found].mean()})
    return pd.DataFrame(records).sort_values("postings",ascending=False).head(n) if records else pd.DataFrame(columns=["skill","postings","average_salary"])
