import json
import os
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, average_precision_score, confusion_matrix,
    classification_report
)

def train_and_evaluate_diabetes_model():
    backend_dir = Path(__file__).resolve().parent.parent
    dataset_path = backend_dir / "data" / "diabetes_prediction_dataset.csv"
    models_dir = backend_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading dataset from: {dataset_path}")
    df = pd.read_csv(dataset_path)
    print(f"Initial shape: {df.shape}")
    
    # 1. Deduplication
    df = df.drop_duplicates().reset_index(drop=True)
    print(f"Deduplicated shape: {df.shape}")
    
    y = df['diabetes'].astype(int)
    
    # Construct exact 13 features matching project get_dummies(drop_first=True) convention:
    gender_dummies = pd.get_dummies(df['gender'], prefix='gender', drop_first=True, dtype=int)
    smoking_dummies = pd.get_dummies(df['smoking_history'], prefix='smoking_history', drop_first=True, dtype=int)
    
    for col in ['gender_Male', 'gender_Other']:
        if col not in gender_dummies.columns:
            gender_dummies[col] = 0
            
    expected_smoking_dummies = [
        'smoking_history_current',
        'smoking_history_ever',
        'smoking_history_former',
        'smoking_history_never',
        'smoking_history_not current'
    ]
    for col in expected_smoking_dummies:
        if col not in smoking_dummies.columns:
            smoking_dummies[col] = 0
            
    numeric_df = pd.DataFrame({
        'age': df['age'].astype(float),
        'hypertension': df['hypertension'].astype(int),
        'heart_disease': df['heart_disease'].astype(int),
        'bmi': df['bmi'].astype(float),
        'HbA1c_level': df['HbA1c_level'].astype(float),
        'blood_glucose_level': df['blood_glucose_level'].astype(float)
    })
    
    feature_order = [
        'age',
        'hypertension',
        'heart_disease',
        'bmi',
        'HbA1c_level',
        'blood_glucose_level',
        'gender_Male',
        'gender_Other',
        'smoking_history_current',
        'smoking_history_ever',
        'smoking_history_former',
        'smoking_history_never',
        'smoking_history_not current'
    ]
    
    X = pd.concat([numeric_df, gender_dummies[['gender_Male', 'gender_Other']], smoking_dummies[expected_smoking_dummies]], axis=1)
    X = X[feature_order]
    
    print(f"Features matrix shape: {X.shape}")
    print(f"Features list: {list(X.columns)}")
    
    # 2. Stratified Train/Test Split (80/20)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )
    
    print(f"Train samples: {len(X_train)}, Test samples: {len(X_test)}")
    
    # 3. Model Benchmark Evaluation
    # Baseline 1: Dummy
    dummy = DummyClassifier(strategy='most_frequent')
    dummy.fit(X_train, y_train)
    dummy_acc = accuracy_score(y_test, dummy.predict(X_test))
    
    # Baseline 2: Logistic Regression (balanced)
    lr = LogisticRegression(max_iter=1000, class_weight='balanced', random_state=42)
    lr.fit(X_train, y_train)
    lr_pred = lr.predict(X_test)
    lr_prob = lr.predict_proba(X_test)[:, 1]
    lr_auc = roc_auc_score(y_test, lr_prob)
    lr_rec = recall_score(y_test, lr_pred)
    lr_prec = precision_score(y_test, lr_pred)
    
    # Main Model: Random Forest
    rf = RandomForestClassifier(
        n_estimators=100,
        max_depth=12,
        class_weight='balanced',
        random_state=42,
        n_jobs=-1
    )
    rf.fit(X_train, y_train)
    
    rf_pred = rf.predict(X_test)
    rf_prob = rf.predict_proba(X_test)[:, 1]
    
    rf_acc = accuracy_score(y_test, rf_pred)
    rf_bal_acc = balanced_accuracy_score(y_test, rf_pred)
    rf_prec = precision_score(y_test, rf_pred)
    rf_rec = recall_score(y_test, rf_pred)
    rf_f1 = f1_score(y_test, rf_pred)
    rf_auc = roc_auc_score(y_test, rf_prob)
    rf_ap = average_precision_score(y_test, rf_prob)
    cm = confusion_matrix(y_test, rf_pred)
    
    print("\n================ EVALUATION RESULTS ================")
    print(f"Dummy Accuracy:                 {dummy_acc:.4f}")
    print(f"Logistic Regression ROC-AUC:    {lr_auc:.4f} (Recall: {lr_rec:.4f}, Prec: {lr_prec:.4f})")
    print(f"Random Forest Accuracy:         {rf_acc:.4f}")
    print(f"Random Forest Balanced Acc:     {rf_bal_acc:.4f}")
    print(f"Random Forest Recall (Class 1): {rf_rec:.4f}")
    print(f"Random Forest Precision:        {rf_prec:.4f}")
    print(f"Random Forest F1-Score:         {rf_f1:.4f}")
    print(f"Random Forest ROC-AUC:          {rf_auc:.4f}")
    print(f"Random Forest PR-AUC (Avg Prec):{rf_ap:.4f}")
    print("\nConfusion Matrix:")
    print(cm)
    
    # Feature Importances
    feat_importances = dict(zip(feature_order, [float(v) for v in rf.feature_importances_]))
    sorted_importances = sorted(feat_importances.items(), key=lambda x: x[1], reverse=True)
    print("\nFeature Importances:")
    for feat, imp in sorted_importances:
        print(f"  {feat:30s}: {imp:.4f}")
        
    # Save Model Artifact (wrapped in dict matching production format)
    model_output_path = models_dir / "diabetes_model.pkl"
    artifact = {
        "model": rf,
        "features": feature_order
    }
    joblib.dump(artifact, model_output_path, compress=3)
    print(f"\nModel saved successfully to: {model_output_path}")
    
    # Save Metadata Artifact
    metadata = {
        "model_name": "RandomForestClassifier",
        "disease_target": "Type 2 Diabetes Mellitus",
        "model_version": "1.0.0",
        "feature_count": len(feature_order),
        "expected_features": feature_order,
        "feature_importances": feat_importances,
        "evaluation_metrics": {
            "test_samples": int(len(y_test)),
            "accuracy": round(float(rf_acc), 4),
            "balanced_accuracy": round(float(rf_bal_acc), 4),
            "precision": round(float(rf_prec), 4),
            "recall": round(float(rf_rec), 4),
            "f1_score": round(float(rf_f1), 4),
            "roc_auc": round(float(rf_auc), 4),
            "pr_auc": round(float(rf_ap), 4),
            "confusion_matrix": {
                "true_negative": int(cm[0][0]),
                "false_positive": int(cm[0][1]),
                "false_negative": int(cm[1][0]),
                "true_positive": int(cm[1][1])
            }
        },
        "decision_thresholds": {
            "low_risk": "< 0.25 (Preventive lifestyle)",
            "moderate_risk": "0.25 - 0.49 (Annual screening advised)",
            "high_risk": ">= 0.50 (Diagnostic oral glucose tolerance test advised)"
        },
        "dataset_metadata": {
            "source_file": "data/diabetes_prediction_dataset.csv",
            "license": "CC0 1.0 Universal (Public Domain)",
            "limitations": [
                "Cross-sectional survey without longitudinal glycemic monitoring.",
                "Statistical risk triage model only; not an FDA-cleared diagnostic device."
            ]
        }
    }
    
    metadata_output_path = models_dir / "diabetes_metadata.json"
    with open(metadata_output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"Metadata saved successfully to: {metadata_output_path}")

if __name__ == "__main__":
    train_and_evaluate_diabetes_model()
