from fastapi.testclient import TestClient
import pytest
from app.main import app

client = TestClient(app)

def test_get_symptoms_library():
    response = client.get("/api/v1/predictions/symptoms")
    assert response.status_code == 200
    data = response.json()
    assert "total_symptoms" in data
    assert data["total_symptoms"] == 131
    assert "symptoms" in data
    assert "cough" in data["symptoms"]
    assert "high_fever" in data["symptoms"]

def test_get_diseases_metadata():
    response = client.get("/api/v1/predictions/diseases")
    assert response.status_code == 200
    data = response.json()
    assert "total_diseases" in data
    assert data["total_diseases"] == 41
    assert "diseases" in data
    assert "Diabetes " in data["diseases"] or "Malaria" in data["diseases"]

def test_post_symptom_checker_valid():
    payload = {
        "symptoms": ["chills", "high_fever", "sweating", "headache"],
        "top_k": 3
    }
    response = client.post("/api/v1/predictions/symptom-checker", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "top_disease" in data
    assert "confidence_percent" in data
    assert "matched_symptoms" in data
    assert len(data["top_predictions"]) <= 3
    for pred in data["top_predictions"]:
        assert "disease" in pred
        assert "confidence_percent" in pred
        assert "description" in pred
        assert "precautions" in pred

def test_post_symptom_checker_emergency_flag():
    payload = {
        "symptoms": ["breathlessness", "chest_pain", "high_fever"],
        "top_k": 2
    }
    response = client.post("/api/v1/predictions/symptom-checker", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "emergency" in data["emergency_recommendation"].lower()

def test_post_symptom_checker_empty_symptoms():
    payload = {
        "symptoms": [],
        "top_k": 3
    }
    response = client.post("/api/v1/predictions/symptom-checker", json=payload)
    assert response.status_code == 422

def test_post_symptom_checker_unrecognized_symptoms():
    payload = {
        "symptoms": ["non_existent_symptom_xyz_123"],
        "top_k": 3
    }
    response = client.post("/api/v1/predictions/symptom-checker", json=payload)
    assert response.status_code == 422
