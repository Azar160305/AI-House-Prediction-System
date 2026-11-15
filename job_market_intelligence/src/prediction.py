"""Salary inference using the fitted preprocessing and regression pipeline."""
from pathlib import Path
import joblib
import pandas as pd

def load_model(path):
    if not Path(path).is_file(): raise FileNotFoundError("No model found. Train from Salary Prediction using real data with salary values.")
    return joblib.load(path)

def predict(artifact,payload):
    row=pd.DataFrame([payload])
    return float(artifact["pipeline"].predict(row)[0])
