"""
Campus Eye — Face Recognition Module
Uses InsightFace (buffalo_l) to generate 512-dim face embeddings.
Matches embeddings against pgvector with cosine similarity.
"""
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class RecognizedFace:
    bbox: tuple[int, int, int, int]   # x1, y1, x2, y2
    name: str
    role: str                          # student | invigilator | staff | unknown
    user_id: int | None
    confidence: float                  # cosine similarity 0–1


class FaceRecognizer:
    """
    Wraps InsightFace for detection + embedding generation.
    Provides sync methods used by the pipeline; DB queries are
    called from the async processor via run_in_executor.
    """

    def __init__(self):
        self._app = None
        self._threshold = get_settings().face_recognition_threshold
        self._model_dir = str(get_settings().model_dir)
        self._loaded = False

    def load(self):
        """Load InsightFace model (call once at startup)."""
        try:
            import insightface
            from insightface.app import FaceAnalysis

            self._app = FaceAnalysis(
                name="buffalo_l",
                root=self._model_dir,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            self._app.prepare(ctx_id=0, det_size=(640, 640))
            self._loaded = True
            logger.info("InsightFace buffalo_l model loaded.")
        except Exception as e:
            logger.error(f"Failed to load InsightFace: {e}. Face recognition disabled.")
            self._loaded = False

    def generate_embedding(self, image: np.ndarray) -> np.ndarray | None:
        """
        Generate a 512-dim embedding from a BGR numpy image.
        Returns None if no face is detected.
        """
        if not self._loaded or self._app is None:
            return None
        faces = self._app.get(image)
        if not faces:
            return None
        # Use the largest face
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        emb = face.normed_embedding  # already L2-normalised (512,)
        return emb.astype(np.float32)

    def generate_embedding_from_file(self, path: str) -> np.ndarray | None:
        """Load image from disk and generate embedding."""
        img = cv2.imread(path)
        if img is None:
            logger.warning(f"Could not read image: {path}")
            return None
        return self.generate_embedding(img)

    def detect_faces(self, image: np.ndarray) -> list[dict]:
        """
        Return raw InsightFace face objects for a frame.
        Each dict has: bbox, embedding, det_score.
        """
        if not self._loaded or self._app is None:
            return []
        faces = self._app.get(image)
        return [
            {
                "bbox": tuple(f.bbox.astype(int).tolist()),
                "embedding": f.normed_embedding.astype(np.float32),
                "det_score": float(f.det_score),
            }
            for f in faces
            if f.det_score > 0.5
        ]

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two L2-normalised vectors."""
        return float(np.dot(a, b))

    def match_embedding(
        self,
        query: np.ndarray,
        candidates: list[dict],   # [{"user_id", "name", "role", "embedding"}]
    ) -> RecognizedFace | None:
        """
        Find best match for a query embedding from a list of candidates.
        Returns RecognizedFace with role='unknown' if no match above threshold.
        """
        best_sim = -1.0
        best = None

        for c in candidates:
            emb = np.array(c["embedding"], dtype=np.float32)
            sim = self.cosine_similarity(query, emb)
            if sim > best_sim:
                best_sim = sim
                best = c

        if best and best_sim >= self._threshold:
            return RecognizedFace(
                bbox=(0, 0, 0, 0),      # caller fills in bbox
                name=best["name"],
                role=best["role"],
                user_id=best["user_id"],
                confidence=best_sim,
            )
        return None


@lru_cache(maxsize=1)
def get_face_recognizer() -> FaceRecognizer:
    """Singleton FaceRecognizer — loaded once and reused."""
    recognizer = FaceRecognizer()
    recognizer.load()
    return recognizer
