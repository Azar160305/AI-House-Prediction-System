# Job Market Intelligence & Salary Prediction

Streamlit dashboard for job-posting demand, skills, salary distributions, locations, experience levels, SQLite queries, salary model comparison, and K-means clusters.

## Upload or select a local CSV

The sidebar defaults to **Upload CSV**, accepts different CSV filenames, and supports files up to 1,024 MB. Choose **Use local CSV** to select any CSV under `data/raw/`; the workspace-level `data/raw/` folder beside the project is also scanned. The original local CSV remains read-only. Uploaded files are preserved under `data/uploads/` with a unique stored name.

The loader reads recognized LinkedIn columns only, uses pandas' low-memory parser and Arrow-backed strings in 50,000-row chunks, uses float32 salary columns, removes duplicates by posting ID across chunk boundaries (with a fallback row identity), and writes normalized batches to a disk-backed Parquet cache. The full DataFrame is held once in the active session rather than `st.cache_data`; Streamlit caches only the small header metadata. A changed CSV invalidates the processed cache. The dashboard shows the filename, file size, source column count, and number of unique records loaded.

Recognized LinkedIn columns include `job_id`, `title`, `company_id`, `location`, `formatted_experience_level`, `formatted_work_type`, `skills_desc`, `min_salary`, `max_salary`, `med_salary`, `currency`, `pay_period`, `remote_allowed`, and `listed_time`. Missing salary stays missing. Average salary uses a reported median when available or the arithmetic mean of real minimum and maximum salary bounds when both exist. Currency and pay period stay attached to the source value; the dashboard filters comparisons and model training to one selected currency and period at a time.

## Run in VS Code (PowerShell)

Open the `job_market_intelligence` folder in VS Code, then run:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py
```

Open the local address printed by Streamlit, normally http://localhost:8501. If PowerShell blocks activation, use:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

The project config at `.streamlit/config.toml` sets Streamlit's `server.maxUploadSize` to 1,024 MB. Restart the Streamlit process after changing configuration. Uploads are copied to `data/uploads/` in 8 MB blocks with a progress bar. The upload widget is then cleared from the page and the saved file is parsed in 50,000-row pandas chunks into a disk-backed Parquet cache. The original CSV is preserved. The full DataFrame is kept once per session; only the small CSV header is stored in `st.cache_data`, avoiding a second cached DataFrame copy in RAM.

The sidebar accepts any CSV filename. Choose **Upload CSV** or choose **Use local CSV** to select a CSV under `data/raw/`. Header validation requires a job title, description, or skills column plus at least one job-market context field. Invalid files show a specific error. Missing optional salary, skills, experience, or location data is allowed; unavailable analyses show an empty-state message.

## Dashboard pages

- Home Dashboard and Job Market Overview: total postings, role demand, industry demand, work-mode signals, and monthly trend.
- Salary Analysis: distribution and average by role for the selected currency and period.
- Skill Demand Analysis: demand and associated listed pay from a fixed keyword list over skills or descriptions.
- Location-Based Analysis and Experience-Level Analysis: posting counts and salary comparisons.
- Salary Prediction: Linear Regression, Random Forest, and Gradient Boosting comparison; prediction with the saved preprocessing/model pipeline.
- Model Performance: MAE, MSE, RMSE, R², cross-validation MAE, and exploratory K-means skill/salary clusters.

For memory usage, model fitting uses a reproducible random sample of up to 10,000 real salary-bearing rows, and K-means up to 30,000, when the dataset is larger. The report records the source row count and whether model sampling occurred. The complete dataset remains available to dashboard analytics.

## Notes

Salary estimates are not guaranteed compensation. Do not compare mixed currencies or pay periods. Some LinkedIn distributions provide skills in a separate file; this app uses the skills/description fields available in the loaded CSV. Review the source dataset's license and terms before redistribution.
