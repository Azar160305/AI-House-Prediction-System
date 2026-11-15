"""K-means grouping over posting skill/title features and salary."""
import pandas as pd
from scipy.sparse import hstack,csr_matrix
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler

def cluster_jobs(df,k=5):
    data=df.dropna(subset=["average_salary"]).copy()
    if len(data)<max(10,k): raise ValueError(f"At least {max(10,k)} salary-bearing postings are needed.")
    if len(data)>30000: data=data.sample(n=30000,random_state=42)
    text=data.required_skills.fillna("").astype(str)+" "+data.job_title.fillna("").astype(str)
    skills=TfidfVectorizer(max_features=500).fit_transform(text)
    pay=StandardScaler().fit_transform(data[["average_salary"]])
    data["cluster"]=KMeans(n_clusters=k,n_init=10,random_state=42).fit_predict(hstack([skills,csr_matrix(pay)]))
    return data
