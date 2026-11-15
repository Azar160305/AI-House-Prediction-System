"""Large-file-friendly Streamlit job market intelligence dashboard."""
from pathlib import Path
import gc
import hashlib
import os
import sys
import uuid
import joblib
import pandas as pd
import plotly.express as px
import streamlit as st

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from src.data_cleaning import normalize_columns
from src.large_csv import inspect_job_csv,process_large_csv
from src.data_analysis import top_skills
from src.sql_operations import QUERIES,run_query,save_dataset
from src.model_training import train_models
from src.prediction import load_model,predict
from src.clustering import cluster_jobs

st.set_page_config(page_title="Job Market Intelligence",page_icon="📊",layout="wide")
st.markdown("<style>"+(ROOT/"assets"/"style.css").read_text(encoding="utf-8")+"</style>",unsafe_allow_html=True)
st.sidebar.title("Market intelligence")
st.sidebar.caption("Upload a CSV or select one from the local project folder")
page=st.sidebar.radio("Dashboard",["Home Dashboard","Job Market Overview","Salary Analysis","Skill Demand Analysis","Location-Based Analysis","Experience-Level Analysis","Salary Prediction","Model Performance"])

MAX_UPLOAD_BYTES=1024*1024*1024
@st.cache_data(max_entries=32,show_spinner=False)
def cached_csv_header(path,mtime_ns,size_bytes):
    # Only the small schema tuple is cached, never a second full DataFrame.
    return tuple(inspect_job_csv(path))

def copy_upload_to_disk(uploaded_file):
    if uploaded_file.size>MAX_UPLOAD_BYTES:
        raise ValueError("The selected CSV exceeds the configured 1,024 MB upload limit. Upload a file up to 1 GB or use a local CSV.")
    uploads_dir=Path(os.environ.get("JOB_MARKET_UPLOAD_DIR",ROOT/"data"/"uploads")); uploads_dir.mkdir(parents=True,exist_ok=True)
    original_name=Path(uploaded_file.name).name
    safe_name="".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in original_name) or "uploaded.csv"
    destination=uploads_dir/f"{uuid.uuid4().hex}_{safe_name}"
    progress=st.progress(0,text=f"Saving {original_name} to project storage…")
    total=max(int(uploaded_file.size),1); copied=0
    try:
        with destination.open("xb") as output:
            while True:
                block=uploaded_file.read(8*1024*1024)
                if not block: break
                output.write(block); copied+=len(block)
                progress.progress(min(copied/total,1.0),text=f"Saving upload · {copied/1024/1024:,.0f} / {total/1024/1024:,.0f} MB")
        if copied!=uploaded_file.size:
            raise IOError(f"Upload copy was incomplete ({copied:,} of {uploaded_file.size:,} bytes).")
        progress.empty()
        return destination,original_name,copied
    except Exception:
        destination.unlink(missing_ok=True)
        progress.empty()
        raise

local_files=sorted({p.resolve() for folder in (ROOT/"data"/"raw",ROOT.parent/"data"/"raw") if folder.exists() for p in folder.glob("*.csv") if p.is_file()})
if os.environ.get("JOB_MARKET_DATA"):
    configured=Path(os.environ["JOB_MARKET_DATA"]).resolve()
    if configured.is_file() and configured.suffix.lower()==".csv": local_files=[configured]+[p for p in local_files if p!=configured]
source_options=["Upload CSV"]+( ["Use local CSV"] if local_files else [])
source_mode=st.sidebar.radio("Dataset source",source_options,key="dataset_source_mode")
if source_mode=="Upload CSV":
    st.sidebar.caption("Upload limit: 1,024 MB. The original upload is preserved on disk.")
    if st.session_state.get("uploaded_csv_path") and not st.session_state.get("show_upload_widget",False):
        st.sidebar.info(f"Selected: {st.session_state.get('uploaded_csv_name','uploaded CSV')}")
        if st.sidebar.button("Upload a different CSV"):
            st.session_state["upload_widget_generation"]=st.session_state.get("upload_widget_generation",0)+1
            st.session_state["show_upload_widget"]=True
            st.rerun()
    else:
        upload_key=f"job_csv_upload_{st.session_state.get('upload_widget_generation',0)}"
        uploaded=st.sidebar.file_uploader("Choose a CSV file",type=["csv"],key=upload_key,help="Any CSV filename is accepted. Large files are copied to disk, then parsed in chunks.")
        if uploaded is not None:
            try:
                saved_path,original_name,file_bytes=copy_upload_to_disk(uploaded)
                st.session_state["uploaded_csv_path"]=str(saved_path)
                st.session_state["uploaded_csv_name"]=original_name
                st.session_state["uploaded_csv_size"]=file_bytes
                st.session_state["show_upload_widget"]=False
                st.session_state["upload_widget_generation"]=st.session_state.get("upload_widget_generation",0)+1
                del uploaded
                st.rerun()
            except Exception as exc:
                st.sidebar.error(f"Upload failed: {exc}")
    selected_path=st.session_state.get("uploaded_csv_path")
    display_name=st.session_state.get("uploaded_csv_name")
else:
    chosen=st.sidebar.selectbox("Local CSV",local_files,format_func=lambda p:f"{p.name} · {p.parent}")
    selected_path=str(chosen); display_name=chosen.name

df=None; file_size=0; raw_headers=()
source_path=None; source_version=""
if selected_path:
    csv_path=Path(selected_path)
    if csv_path.is_file():
        try:
            stat=csv_path.stat(); file_size=stat.st_size
            source_path=str(csv_path.resolve()); source_version=f"{stat.st_mtime_ns}:{stat.st_size}"
            signature=(str(csv_path.resolve()),stat.st_mtime_ns,stat.st_size)
            raw_headers=cached_csv_header(*signature)
            if st.session_state.get("dataset_signature")!=signature:
                st.session_state.pop("dataset_frame",None); gc.collect()
                cache_key=hashlib.sha256("|".join(map(str,signature)).encode("utf-8")).hexdigest()
                cache_dir=Path(os.environ.get("JOB_MARKET_CACHE_DIR",ROOT/"data"/"processed"/"parquet_cache"))
                parquet_path=cache_dir/f"{cache_key}.parquet"
                if parquet_path.is_file():
                    with st.spinner("Loading normalized Parquet cache into memory…"):
                        frame=pd.read_parquet(parquet_path,dtype_backend="pyarrow")
                else:
                    status=st.status("Validating CSV and reading in memory-bounded chunks…",expanded=True)
                    def progress(rows,chunks): status.update(label=f"Parsed {rows:,} unique postings across {chunks:,} chunks…",state="running")
                    frame,raw_headers=process_large_csv(csv_path,parquet_path,on_progress=progress)
                    status.update(label=f"Finished reading {len(frame):,} unique postings.",state="complete",expanded=False)
                st.session_state["dataset_frame"]=frame
                st.session_state["dataset_signature"]=signature
                st.session_state["dataset_columns_count"]=len(raw_headers)
                st.session_state["dataset_row_count"]=len(frame)
                del frame; gc.collect()
            df=st.session_state.get("dataset_frame")
        except Exception as exc:
            st.error(f"Could not load {display_name or csv_path.name}: {exc}")
    else:
        st.error(f"Selected CSV no longer exists: {csv_path}")

st.title("Job Market Intelligence & Salary Prediction")
if df is None:
    st.info("Choose a CSV in the sidebar or put any CSV in data/raw and select it as a local dataset. The original CSV is preserved.")
    st.stop()

info=st.columns(4)
info[0].metric("File",display_name or csv_path.name,help=str(csv_path))
info[1].metric("File size",f"{file_size/1024/1024:,.1f} MB")
info[2].metric("Rows loaded",f"{len(df):,}")
info[3].metric("Source columns",f"{len(raw_headers):,}")
st.caption("Columns were normalized automatically. Missing optional salary, skills, experience, and location fields are handled without synthetic values.")
with st.sidebar.expander("Filters",expanded=True):
    role_options=sorted(df.job_title.dropna().astype(str).unique())
    role_options=[v for v in role_options if v!="Unknown"]
    loc_options=sorted(df.location.dropna().astype(str).unique())
    loc_options=[v for v in loc_options if v!="Unknown"]
    exp_options=sorted(df.experience_level.dropna().astype(str).unique())
    exp_options=[v for v in exp_options if v!="Unknown"]
    roles=st.multiselect("Job role",role_options)
    locations=st.multiselect("Location",loc_options)
    levels=st.multiselect("Experience level",exp_options)
    currencies=sorted(df.salary_currency.dropna().astype(str).unique())
    periods=sorted(df.salary_period.dropna().astype(str).unique())
    currencies=currencies or ["Unknown"]
    periods=periods or ["Unknown"]
    default_currency=next((v for v in currencies if v!="Unknown"),currencies[0])
    default_period=next((v for v in periods if v in ("YEARLY","ANNUAL")),next((v for v in periods if v!="Unknown"),periods[0]))
    currency=st.selectbox("Salary currency",currencies,index=currencies.index(default_currency))
    period=st.selectbox("Salary period",periods,index=periods.index(default_period))

filtered=df
if roles: filtered=filtered[filtered.job_title.astype(str).isin(roles)]
if locations: filtered=filtered[filtered.location.astype(str).isin(locations)]
if levels: filtered=filtered[filtered.experience_level.astype(str).isin(levels)]
salary_df=filtered[(filtered.salary_currency.astype(str)==currency)&(filtered.salary_period.astype(str)==period)]
salary_values=pd.to_numeric(salary_df.average_salary,errors="coerce").dropna()
if currency=="Unknown" or period=="Unknown":
    st.warning("Salary currency or pay period is missing in the source. Salary comparisons and model training are restricted to the selected source labels.")

def money(value): return f"{currency} {value:,.0f}" if pd.notna(value) else "—"
def kpis():
    a,b,c,d=st.columns(4)
    a.metric("Job postings",f"{len(filtered):,}")
    b.metric("Unique job titles",f"{filtered.job_title.nunique():,}")
    c.metric("Mean listed salary",money(salary_values.mean()) if len(salary_values) else "Not listed")
    d.metric("Locations",f"{filtered.location.nunique():,}")

if page in ("Home Dashboard","Job Market Overview"):
    kpis()
    a,b=st.columns(2)
    role_counts=filtered.job_title.astype(str).value_counts().head(15).rename_axis("Job title").reset_index(name="Postings")
    a.subheader("Most posted job titles")
    a.plotly_chart(px.bar(role_counts.sort_values("Postings"),x="Postings",y="Job title",orientation="h",template="plotly_white"),width="stretch")
    work=filtered.remote_status.astype(str).value_counts().head(8).rename_axis("Work mode").reset_index(name="Postings")
    b.subheader("Remote and on-site signals")
    b.plotly_chart(px.pie(work,names="Work mode",values="Postings",hole=.45,template="plotly_white"),width="stretch")
    industries=filtered.industry.astype(str).value_counts().head(15).rename_axis("Industry").reset_index(name="Postings")
    st.subheader("Industry demand")
    st.plotly_chart(px.bar(industries.sort_values("Postings"),x="Postings",y="Industry",orientation="h",template="plotly_white"),width="stretch")
    month_data=filtered.dropna(subset=["posting_date"])
    if not month_data.empty:
        months=month_data.posting_date.astype("string[pyarrow]").str.slice(0,7)
        monthly=months.value_counts().sort_index().rename_axis("month").reset_index(name="Postings")
        st.subheader("Monthly posting trend")
        st.plotly_chart(px.line(monthly,x="month",y="Postings",markers=True,template="plotly_white"),width="stretch")
elif page=="Salary Analysis":
    st.subheader(f"Salary distribution · {currency} per {period}")
    if salary_values.empty: st.info("No salary values are available for the selected currency and pay period. The dashboard does not fill missing salaries.")
    else:
        st.metric("Records with salary",f"{len(salary_values):,}")
        st.plotly_chart(px.histogram(salary_df.dropna(subset=["average_salary"]),x="average_salary",color="experience_level",nbins=45,template="plotly_white"),width="stretch")
        by_role=salary_df.dropna(subset=["average_salary"]).groupby("job_title",observed=True).average_salary.agg(["mean","count"]).query("count >= 2").sort_values("mean",ascending=False).head(25).reset_index()
        st.plotly_chart(px.bar(by_role,x="mean",y="job_title",orientation="h",template="plotly_white",labels={"mean":f"Average salary ({currency}/{period})"}),width="stretch")
elif page=="Skill Demand Analysis":
    st.subheader("In-demand technical skills")
    key=("skills",source_path,source_version,currency,period,tuple(roles),tuple(locations),tuple(levels),len(filtered))
    if st.session_state.get("skill_cache_key")!=key:
        with st.spinner("Scanning the skills field and descriptions once for this filter set…"):
            st.session_state["skill_cache_result"]=top_skills(filtered)
            st.session_state["skill_cache_key"]=key
    skills=st.session_state["skill_cache_result"]
    if skills.empty: st.info("No recognized technical skills were found in the available skills or description fields.")
    else:
        a,b=st.columns(2)
        a.plotly_chart(px.bar(skills.sort_values("postings"),x="postings",y="skill",orientation="h",template="plotly_white"),width="stretch")
        b.plotly_chart(px.scatter(skills.dropna(subset=["average_salary"]),x="postings",y="average_salary",size="postings",hover_name="skill",template="plotly_white",labels={"average_salary":f"Associated mean ({currency}/{period})"}),width="stretch")
    st.caption("A skill is counted at most once per posting using a fixed technology keyword list. Description scanning may take a little time on first use.")
elif page=="Location-Based Analysis":
    st.subheader("Job opportunity and listed pay by location")
    loc=filtered.groupby("location",observed=True).agg(postings=("job_title","size"),average_salary=("average_salary","mean")).sort_values("postings",ascending=False).head(40).reset_index()
    st.plotly_chart(px.scatter(loc,x="postings",y="average_salary",size="postings",hover_name="location",template="plotly_white",labels={"average_salary":f"Mean ({currency}/{period})"}),width="stretch")
    st.dataframe(loc,width="stretch",hide_index=True)
elif page=="Experience-Level Analysis":
    st.subheader("Experience level and salary")
    exp=salary_df.groupby("experience_level",observed=True).agg(postings=("job_title","size"),salary_records=("average_salary","count"),average_salary=("average_salary","mean")).reset_index()
    if exp.salary_records.sum()==0: st.info("No salary data for the selected currency and pay period.")
    else: st.plotly_chart(px.bar(exp,x="experience_level",y="average_salary",color="postings",template="plotly_white",labels={"average_salary":f"Mean ({currency}/{period})"}),width="stretch")
    st.dataframe(exp,width="stretch",hide_index=True)
elif page=="Salary Prediction":
    st.subheader("Salary estimate from postings")
    st.warning("This is a statistical estimate from listed salaries, not a guaranteed offer. Estimate units follow the selected source currency and period.")
    artifact_path=ROOT/"models"/"salary_model.joblib"
    artifact=None
    try: artifact=load_model(artifact_path)
    except FileNotFoundError: st.info("No trained model yet. Use the real loaded salary data to train below.")
    choose=lambda col: sorted(s for s in df[col].dropna().astype(str).unique() if s and s!="Unknown") or ["Unknown"]
    with st.form("salary_prediction"):
        a,b=st.columns(2)
        title=a.selectbox("Job role",choose("job_title"))
        exp=b.selectbox("Experience",choose("experience_level"))
        loc=a.selectbox("Location",choose("location"))
        employment=b.selectbox("Employment type",choose("employment_type"))
        industry=a.selectbox("Industry",choose("industry"))
        skills=b.text_input("Technical skills",placeholder="Python | SQL | AWS")
        submit=st.form_submit_button("Predict salary",type="primary")
    if submit:
        if not artifact: st.error("Train a model first.")
        else:
            payload={"job_title":title,"experience_level":exp,"location":loc,"employment_type":employment,"industry":industry,"required_skills":skills}
            if artifact.get("currency",currency)!=currency or artifact.get("period",period)!=period:
                st.error(f"The saved model uses {artifact.get('currency','Unknown')} per {artifact.get('period','Unknown')}; select matching source units or retrain.")
            else:
                try: st.metric(f"Estimate ({currency} / {period})",money(predict(artifact,payload)))
                except Exception as exc: st.error(f"Prediction failed: {exc}")
    if st.button("Train and compare models"):
        try:
            with st.spinner("Training on the selected real salary currency and period…"):
                metrics,best=train_models(salary_df,ROOT/"models",ROOT/"data"/"processed",currency,period)
            st.success(f"Selected {best} by held-out MAE. Model and metrics saved.")
            st.dataframe(metrics,width="stretch",hide_index=True)
        except Exception as exc: st.error(f"Model training failed: {exc}")
elif page=="Model Performance":
    metrics_path=ROOT/"data"/"processed"/"model_metrics.csv"
    st.subheader("Salary model evaluation")
    if metrics_path.is_file():
        st.dataframe(pd.read_csv(metrics_path),width="stretch",hide_index=True)
        st.caption(f"Measured for {currency} per {period}; 80/20 holdout and training-fold cross-validation. Scores belong to the source data used for training.")
    else: st.info("No evaluation report yet. Train from Salary Prediction after loading salary-bearing rows.")
    st.subheader("K-means job clusters")
    if st.button("Analyze skill and salary clusters"):
        try:
            clustered=cluster_jobs(salary_df)
            def common(values):
                terms=values.fillna("").astype(str).str.lower().str.split(r"[|,;/\n]+",regex=True).explode().str.strip()
                terms=terms[terms.ne("")]
                return ", ".join(terms.value_counts().head(5).index)
            summary=clustered.groupby("cluster").agg(postings=("job_title","size"),median_salary=("average_salary","median"),common_roles=("job_title",lambda x:", ".join(x.value_counts().head(3).index)),common_skills=("required_skills",common),experience_levels=("experience_level",lambda x:", ".join(x.value_counts().head(4).index))).reset_index()
            st.dataframe(summary,width="stretch",hide_index=True)
            st.caption("Cluster descriptions, experience mix, and median salary are descriptive; clusters are exploratory groups, not validated job categories.")
        except Exception as exc: st.error(f"Clustering failed: {exc}")

with st.expander("SQLite analytical queries"):
    query=st.selectbox("Query",list(QUERIES))
    if st.button("Save local dataset to SQLite and run query"):
        try:
            db_path=ROOT/"database"/"job_market.db"
            save_dataset(df,db_path)
            st.dataframe(run_query(query,db_path),width="stretch",hide_index=True)
        except Exception as exc: st.error(f"SQL analysis failed: {exc}")
