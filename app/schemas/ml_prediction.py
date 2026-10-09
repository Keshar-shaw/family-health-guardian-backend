from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from enum import Enum
from datetime import datetime, timezone


class GenderEnum(str, Enum):
    male = "Male"
    female = "Female"
    other = "Other"


class SmokingHistoryEnum(str, Enum):
    never = "never"
    current = "current"
    former = "former"
    ever = "ever"
    not_current = "not current"
    no_info = "No Info"


class DiabetesPredictionRequest(BaseModel):
    age: float = Field(..., ge=0, le=120, description="Patient age in years")
    gender: GenderEnum = Field(..., description="Patient gender (Male, Female, Other)")
    hypertension: bool = Field(..., description="Whether patient is diagnosed with hypertension")
    heart_disease: bool = Field(..., description="Whether patient is diagnosed with heart disease")
    smoking_history: SmokingHistoryEnum = Field(..., description="Patient smoking history")
    bmi: float = Field(..., ge=10.0, le=80.0, description="Body Mass Index (BMI)")
    hba1c_level: float = Field(..., ge=3.0, le=20.0, description="Hemoglobin A1c level (HbA1c)")
    blood_glucose_level: float = Field(..., ge=30.0, le=600.0, description="Blood glucose level in mg/dL")
    family_id: Optional[str] = Field(None, description="Optional Family UUID to associate record with")
    family_member_id: Optional[str] = Field(None, description="Optional Family Member UUID (e.g. for dependents)")
    save_to_records: bool = Field(False, description="Whether to persist the result in health records")

    @field_validator('age', 'bmi', 'hba1c_level', 'blood_glucose_level', mode='before')
    @classmethod
    def validate_numeric_measurement(cls, v, info):
        if v is None:
            raise ValueError(f"{info.field_name} is required and cannot be null or missing")
        try:
            val = float(v)
        except (ValueError, TypeError):
            raise ValueError(f"{info.field_name} must be a valid numeric measurement")
        import math
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"{info.field_name} cannot be NaN or infinite")
        return val

    @field_validator('gender', mode='before')
    @classmethod
    def normalize_gender(cls, v):
        if isinstance(v, str):
            v_lower = v.strip().lower()
            if v_lower in ("male", "m"):
                return GenderEnum.male
            elif v_lower in ("female", "f"):
                return GenderEnum.female
            elif v_lower in ("other", "o"):
                return GenderEnum.other
        return v

    @field_validator('smoking_history', mode='before')
    @classmethod
    def normalize_smoking(cls, v):
        if isinstance(v, str):
            v_clean = v.strip().lower().replace("_", " ")
            if v_clean in ("no info", "no_info", "unknown", "na", "n/a"):
                return SmokingHistoryEnum.no_info
            for item in SmokingHistoryEnum:
                if item.value.lower() == v_clean:
                    return item
        return v


class DiabetesPredictionResponse(BaseModel):
    prediction: int = Field(..., description="0 for negative/low risk, 1 for positive/high risk")
    risk_label: str = Field(..., description="Human-readable risk label: 'Low Risk' or 'High Risk'")
    risk_probability: float = Field(..., description="Calculated probability between 0.0 and 1.0")
    risk_percentage: float = Field(..., description="Calculated percentage e.g. 89.0%")
    confidence_level: str = Field(..., description="'High Confidence', 'Moderate Confidence', or 'Low Confidence'")
    feature_summary: dict = Field(..., description="Summary of input values used for the inference")
    recommendations: List[str] = Field(..., description="Actionable health recommendations")
    assessed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    record_id: Optional[str] = Field(None, description="UUID of the saved prediction record if persisted")


class PredictionHistoryResponse(BaseModel):
    id: str = Field(..., description="Unique UUID of the prediction history record")
    user_id: str = Field(..., description="UUID of the authenticated user")
    family_id: Optional[str] = Field(None, description="Optional Family UUID")
    family_member_id: Optional[str] = Field(None, description="Optional Family Member UUID")
    prediction_type: str = Field("DIABETES", description="Type of disease prediction")
    model_version: str = Field("1.0.0", description="Model version")
    model_name: str = Field("RandomForestClassifier", description="Model algorithm name")
    input_measurements: dict = Field(..., description="Consented input measurements")
    prediction_result: int = Field(..., description="Binary prediction outcome (0 or 1)")
    risk_label: str = Field(..., description="'Low Risk' or 'High Risk'")
    risk_probability: float = Field(..., description="Calculated probability (0.0 to 1.0)")
    risk_percentage: float = Field(..., description="Calculated risk percentage")
    confidence_level: str = Field(..., description="Confidence label")
    recommendations: List[str] = Field(default_factory=list, description="Health recommendations")
    created_at: str = Field(..., description="Timestamp of prediction")


class HypertensionPredictionRequest(BaseModel):
    age: float = Field(..., ge=0, le=120, description="Patient age in years")
    gender: GenderEnum = Field(..., description="Patient gender (Male, Female, Other)")
    heart_disease: bool = Field(..., description="Whether patient is diagnosed with heart disease")
    smoking_history: SmokingHistoryEnum = Field(..., description="Patient smoking history")
    bmi: float = Field(..., ge=10.0, le=80.0, description="Body Mass Index (BMI)")
    hba1c_level: float = Field(..., ge=3.0, le=20.0, description="Hemoglobin A1c level (HbA1c)")
    blood_glucose_level: float = Field(..., ge=30.0, le=600.0, description="Blood glucose level in mg/dL")
    diabetes: bool = Field(..., description="Whether patient is diagnosed with diabetes")
    family_id: Optional[str] = Field(None, description="Optional Family UUID to associate record with")
    family_member_id: Optional[str] = Field(None, description="Optional Family Member UUID (e.g. for dependents)")
    save_to_records: bool = Field(False, description="Whether to persist the result in health records")

    @field_validator('age', 'bmi', 'hba1c_level', 'blood_glucose_level', mode='before')
    @classmethod
    def validate_numeric_measurement(cls, v, info):
        if v is None:
            raise ValueError(f"{info.field_name} is required and cannot be null or missing")
        try:
            val = float(v)
        except (ValueError, TypeError):
            raise ValueError(f"{info.field_name} must be a valid numeric measurement")
        import math
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"{info.field_name} cannot be NaN or infinite")
        return val

    @field_validator('gender', mode='before')
    @classmethod
    def normalize_gender(cls, v):
        if isinstance(v, str):
            v_lower = v.strip().lower()
            if v_lower in ("male", "m"):
                return GenderEnum.male
            elif v_lower in ("female", "f"):
                return GenderEnum.female
            elif v_lower in ("other", "o"):
                return GenderEnum.other
        return v

    @field_validator('smoking_history', mode='before')
    @classmethod
    def normalize_smoking(cls, v):
        if isinstance(v, str):
            v_clean = v.strip().lower().replace("_", " ")
            if v_clean in ("no info", "no_info", "unknown", "na", "n/a"):
                return SmokingHistoryEnum.no_info
            for item in SmokingHistoryEnum:
                if item.value.lower() == v_clean:
                    return item
        return v


class HypertensionPredictionResponse(BaseModel):
    prediction: int = Field(..., description="0 for negative/low risk, 1 for positive/high risk")
    risk_label: str = Field(..., description="Human-readable risk label: 'Low Risk' or 'High Risk'")
    risk_probability: float = Field(..., description="Calculated probability between 0.0 and 1.0")
    risk_percentage: float = Field(..., description="Calculated percentage e.g. 89.0%")
    confidence_level: str = Field(..., description="'High Confidence', 'Moderate Confidence', or 'Low Confidence'")
    feature_summary: dict = Field(..., description="Summary of input values used for the inference")
    recommendations: List[str] = Field(..., description="Actionable health recommendations")
    assessed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    record_id: Optional[str] = Field(None, description="UUID of the saved prediction record if persisted")


