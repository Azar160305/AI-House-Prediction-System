"""SQLite persistence and query layer."""
from pathlib import Path
import sqlite3
import pandas as pd

QUERIES={
 "Top paying roles":"SELECT job_title, ROUND(AVG(average_salary),0) avg_salary, COUNT(*) postings FROM job_postings WHERE average_salary IS NOT NULL GROUP BY job_title HAVING COUNT(*)>=2 ORDER BY avg_salary DESC LIMIT 10",
 "Most demanded skills":"SELECT skill, COUNT(DISTINCT job_id) postings FROM skills GROUP BY skill ORDER BY postings DESC LIMIT 10",
 "Average salary by location":"SELECT location, ROUND(AVG(average_salary),0) avg_salary, COUNT(*) postings FROM job_postings WHERE average_salary IS NOT NULL GROUP BY location ORDER BY avg_salary DESC LIMIT 25",
 "Salary by experience":"SELECT experience_level, ROUND(AVG(average_salary),0) avg_salary, COUNT(*) postings FROM job_postings WHERE average_salary IS NOT NULL GROUP BY experience_level ORDER BY avg_salary DESC",
 "Industry demand":"SELECT industry, COUNT(*) postings FROM job_postings GROUP BY industry ORDER BY postings DESC LIMIT 25",
 "Remote percentage":"SELECT ROUND(100.0*SUM(CASE WHEN LOWER(remote_status)='remote' THEN 1 ELSE 0 END)/COUNT(*),1) remote_pct, COUNT(*) total FROM job_postings",
 "Monthly demand":"SELECT substr(posting_date,1,7) month, COUNT(*) postings FROM job_postings WHERE posting_date IS NOT NULL GROUP BY month ORDER BY month",
 "Highest paying companies":"SELECT company_name, ROUND(AVG(average_salary),0) avg_salary, COUNT(*) postings FROM job_postings WHERE average_salary IS NOT NULL GROUP BY company_name HAVING COUNT(*)>=2 ORDER BY avg_salary DESC LIMIT 10",
}

def save_dataset(df,path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path)
    try:
        cols=["job_title","company_name","location","country","experience_level","employment_type","required_skills","minimum_salary","maximum_salary","average_salary","salary_currency","salary_period","industry","remote_status","posting_date"]
        data=df[cols].copy(); data.to_sql("job_postings",conn,if_exists="replace",index_label="id",chunksize=50000)
        conn.execute("CREATE TABLE IF NOT EXISTS skills (job_id INTEGER, skill TEXT)")
        conn.execute("DELETE FROM skills")
        # Keep database write memory bounded by parsing/inserting rows in batches.
        cursor=conn.cursor(); batch=[]
        for job_id,cell in enumerate(df.required_skills.fillna(""),start=0):
            for skill in re_split(cell): batch.append((job_id,skill))
            if len(batch)>=50000: cursor.executemany("INSERT INTO skills VALUES (?,?)",batch); batch.clear()
        if batch: cursor.executemany("INSERT INTO skills VALUES (?,?)",batch)
        conn.commit()
    finally: conn.close()

def re_split(value):
    import re
    return [x.strip().lower() for x in re.split(r"[|,;/\n]+",str(value)) if x.strip()]

def run_query(name,path):
    if name not in QUERIES: raise KeyError(name)
    with sqlite3.connect(path) as conn: return pd.read_sql_query(QUERIES[name],conn)
