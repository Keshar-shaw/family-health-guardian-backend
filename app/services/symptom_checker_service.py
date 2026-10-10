import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
import joblib

logger = logging.getLogger(__name__)

class SymptomCheckerService:
    _instance: Optional["SymptomCheckerService"] = None

    def __init__(self):
        self._model = None
        self._symptoms: List[str] = []
        self._disease_metadata: Dict[str, Any] = {}
        self._is_loaded = False

    @classmethod
    def get_instance(cls) -> "SymptomCheckerService":
        if cls._instance is None:
            cls._instance = SymptomCheckerService()
        return cls._instance

    def _resolve_paths(self):
        project_root = Path(__file__).resolve().parent.parent.parent
        models_dir = project_root / "models"
        model_path = models_dir / "multi_disease_model.pkl"
        symptoms_path = models_dir / "symptoms_list.json"
        metadata_path = models_dir / "disease_metadata.json"
        return model_path, symptoms_path, metadata_path

    def load_model(self, force_reload: bool = False) -> None:
        if self._is_loaded and not force_reload:
            return

        model_path, symptoms_path, metadata_path = self._resolve_paths()

        if not model_path.is_file():
            raise FileNotFoundError(f"Multi-disease model file not found: {model_path}")
        if not symptoms_path.is_file():
            raise FileNotFoundError(f"Symptoms list file not found: {symptoms_path}")
        if not metadata_path.is_file():
            raise FileNotFoundError(f"Disease metadata file not found: {metadata_path}")

        logger.info("Loading Multi-Disease Symptom Checker ML Model from %s", model_path)
        try:
            self._model = joblib.load(model_path)
        except Exception as e:
            logger.error("Failed to load multi-disease model: %s", e)
            raise RuntimeError(f"Failed to load multi-disease model: {e}") from e

        with open(symptoms_path, "r", encoding="utf-8") as f:
            sym_data = json.load(f)
            self._symptoms = sym_data.get("symptoms", [])

        with open(metadata_path, "r", encoding="utf-8") as f:
            self._disease_metadata = json.load(f)

        self._is_loaded = True
        logger.info("Multi-Disease model loaded successfully with %d symptoms and %d diseases",
                    len(self._symptoms), len(self._disease_metadata))

    def get_symptoms(self) -> List[str]:
        if not self._is_loaded:
            self.load_model()
        return list(self._symptoms)

    def get_disease_metadata(self) -> Dict[str, Any]:
        if not self._is_loaded:
            self.load_model()
        return dict(self._disease_metadata)

    def predict(self, selected_symptoms: List[str], top_k: int = 3) -> Dict[str, Any]:
        """
        Predict probable diseases based on user reported symptoms.
        Returns top_k predicted diseases with probability scores, descriptions, and precautions.
        """
        if not self._is_loaded:
            self.load_model()

        if not selected_symptoms:
            raise ValueError("At least one symptom must be selected for diagnosis.")

        # Normalize symptom strings (lowercase, stripped, spaces to underscores)
        normalized_selected = {s.strip().lower().replace(" ", "_") for s in selected_symptoms}

        # Validate symptoms against supported symptoms
        known_symptoms = set(self._symptoms)
        matched = [s for s in normalized_selected if s in known_symptoms]
        unknown = [s for s in normalized_selected if s not in known_symptoms]

        if not matched:
            raise ValueError(
                f"None of the provided symptoms are recognized. Supported examples: 'chills', 'high_fever', 'cough', 'headache'"
            )

        # Build feature vector matching 131 columns expected by RandomForest
        row = {sym: 1 if sym in matched else 0 for sym in self._symptoms}
        input_df = pd.DataFrame([row])

        # Inference
        probabilities = self._model.predict_proba(input_df)[0]
        classes = self._model.classes_

        top_indices = np.argsort(probabilities)[::-1][:top_k]

        predictions = []
        for idx in top_indices:
            disease = str(classes[idx])
            prob = float(probabilities[idx])
            prob_percent = round(prob * 100, 2)
            meta = self._disease_metadata.get(disease, {})

            predictions.append({
                "disease": disease,
                "confidence_percent": prob_percent,
                "description": meta.get("description", "No specific clinical description available."),
                "precautions": meta.get("precautions", ["Consult a physician for clinical evaluation."])
            })

        top_prediction = predictions[0] if predictions else None

        return {
            "top_disease": top_prediction["disease"] if top_prediction else "Unknown",
            "confidence_percent": top_prediction["confidence_percent"] if top_prediction else 0.0,
            "matched_symptoms": matched,
            "unrecognized_symptoms": unknown,
            "top_predictions": predictions,
            "emergency_recommendation": (
                "Seek immediate emergency medical attention if experiencing difficulty breathing, chest pain, or severe confusion."
                if any(s in matched for s in ["breathlessness", "chest_pain", "coma", "altered_sensorium"])
                else "Please review these findings with a licensed healthcare provider."
            )
        }

symptom_checker_service = SymptomCheckerService.get_instance()
