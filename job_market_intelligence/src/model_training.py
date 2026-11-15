"""Salary model comparison, validation, and artifact persistence."""
from pathlib import Path
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor,GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score
from sklearn.model_selection import train_test_split,cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer
from .feature_engineering import CATS,build_preprocessor,densify

FEATURES=CATS+["required_skills"]
def train_models(df,model_dir,report_dir,currency="Unknown",period="Unknown"):
    data=df.dropna(subset=["average_salary"]).loc[lambda x:x.average_salary>0]
    if len(data)<30: raise ValueError(f"At least 30 postings with reported salary are required; found {len(data)}.")
    source_rows=len(data)
    if len(data)>10000: data=data.sample(n=10000,random_state=42)
    X=data[FEATURES].fillna("Unknown"); y=data.average_salary.astype(float)
    xa,xb,ya,yb=train_test_split(X,y,test_size=.2,random_state=42)
    estimators={"Linear Regression":LinearRegression(),"Random Forest":RandomForestRegressor(n_estimators=200,min_samples_leaf=2,n_jobs=-1,random_state=42),"Gradient Boosting":GradientBoostingRegressor(random_state=42)}
    rows=[]; fitted={}
    for name,est in estimators.items():
        steps=[("preprocess",build_preprocessor())]
        if name=="Gradient Boosting": steps.append(("dense",FunctionTransformer(densify,accept_sparse=True)))
        steps.append(("model",est))
        pipe=Pipeline(steps)
        pipe.fit(xa,ya); pred=pipe.predict(xb)
        cv=-cross_val_score(pipe,xa,ya,cv=3,scoring="neg_mean_absolute_error",n_jobs=1).mean()
        rows.append({"model":name,"mae":mean_absolute_error(yb,pred),"mse":mean_squared_error(yb,pred),"rmse":np.sqrt(mean_squared_error(yb,pred)),"r2":r2_score(yb,pred),"cv_mae_mean":cv,"test_rows":len(yb)})
        fitted[name]=pipe
    result=pd.DataFrame(rows).sort_values(["mae","rmse"]); best=result.iloc[0]["model"]
    model_dir,report_dir=Path(model_dir),Path(report_dir); model_dir.mkdir(parents=True,exist_ok=True); report_dir.mkdir(parents=True,exist_ok=True)
    joblib.dump({"pipeline":fitted[best],"model_name":best,"features":FEATURES,"currency":currency,"period":period},model_dir/"salary_model.joblib")
    result.to_csv(report_dir/"model_metrics.csv",index=False)
    (report_dir/"model_report.json").write_text(json.dumps({"selected_model":best,"rows_used":len(data),"source_salary_rows":source_rows,"sampled_for_memory":source_rows>len(data),"currency":currency,"salary_period":period,"currency_period_note":"Values are in selected source currency and salary period; normalize before comparing datasets.","split":"80/20 random, state 42","metrics":rows},indent=2),encoding="utf-8")
    return result,best
