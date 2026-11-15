"""Shared salary model features and prediction row builder."""
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from scipy import sparse
from sklearn.preprocessing import OneHotEncoder,FunctionTransformer

CATS=["job_title","experience_level","location","employment_type","industry"]
def flatten_column(x): return x.ravel()
def densify(x): return x.toarray() if sparse.issparse(x) else x

def build_preprocessor():
    cats=Pipeline([("impute",SimpleImputer(strategy="constant",fill_value="Unknown")),("encode",OneHotEncoder(handle_unknown="ignore",min_frequency=10,max_categories=500))])
    skills=Pipeline([("impute",SimpleImputer(strategy="constant",fill_value="")),("flatten",FunctionTransformer(flatten_column,validate=False)),("tfidf",TfidfVectorizer(max_features=500,ngram_range=(1,2),token_pattern=r"(?u)\b\w[\w+#.\-]*\b"))])
    return ColumnTransformer([("categories",cats,CATS),("skills",skills,["required_skills"])])
