"""
Campus Eye — Model Pre-downloader
Run once before starting the app to cache all model weights locally.
"""
import os
import sys
from pathlib import Path

MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)


def download_yolo_models():
    print("▸ Downloading YOLOv8 detection models...")
    try:
        # PyTorch 2.6+ changed weights_only default to True — allowlist YOLO globals
        import torch
        import ultralytics.nn.tasks as _ult_tasks
        if hasattr(torch.serialization, "add_safe_globals"):
            torch.serialization.add_safe_globals([
                _ult_tasks.DetectionModel,
                _ult_tasks.PoseModel,
                _ult_tasks.SegmentationModel,
            ])
        from ultralytics import YOLO
        import shutil

        # Download yolov8s (preferred — better accuracy)
        print("  ▸ yolov8s.pt (preferred detection model)...")
        model_s = YOLO("yolov8s.pt")
        dest_s = MODEL_DIR / "yolov8s.pt"
        if not dest_s.exists():
            src_s = Path(model_s.ckpt_path) if hasattr(model_s, "ckpt_path") else Path("yolov8s.pt")
            if src_s.exists():
                shutil.copy(src_s, dest_s)
        print(f"  ✔ yolov8s.pt → {dest_s}")

        # Download yolov8n (fallback — faster, lower accuracy)
        print("  ▸ yolov8n.pt (fallback detection model)...")
        model_n = YOLO("yolov8n.pt")
        dest_n = MODEL_DIR / "yolov8n.pt"
        if not dest_n.exists():
            src_n = Path(model_n.ckpt_path) if hasattr(model_n, "ckpt_path") else Path("yolov8n.pt")
            if src_n.exists():
                shutil.copy(src_n, dest_n)
        print(f"  ✔ yolov8n.pt → {dest_n}")

        print("▸ Downloading YOLOv8n-pose model...")
        pose = YOLO("yolov8n-pose.pt")
        dest_pose = MODEL_DIR / "yolov8n-pose.pt"
        if not dest_pose.exists():
            src_pose = Path("yolov8n-pose.pt")
            if src_pose.exists():
                shutil.copy(src_pose, dest_pose)
        print(f"  ✔ yolov8n-pose.pt → {dest_pose}")
    except Exception as e:
        print(f"  ✗ YOLO download failed: {e}")
        print("    Run manually: python -c \"from ultralytics import YOLO; YOLO('yolov8s.pt')\"")

def download_insightface_models():
    print("▸ Downloading InsightFace buffalo_l model (~300 MB)...")
    try:
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(
            name="buffalo_l",
            root=str(MODEL_DIR),
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=-1, det_size=(640, 640))
        print("  ✔ InsightFace buffalo_l downloaded.")
        # Clean up the zip file InsightFace leaves behind to save ~288 MB
        zip_path = MODEL_DIR / "models" / "buffalo_l.zip"
        if zip_path.exists():
            zip_path.unlink()
            print("  ✔ Removed buffalo_l.zip (already extracted).")
    except Exception as e:
        print(f"  ✗ InsightFace download failed: {e}")
        print("    It will auto-download on first use.")


def download_mediapipe():
    print("▸ Verifying MediaPipe installation...")
    try:
        import mediapipe as mp
        _ = mp.solutions.face_mesh.FaceMesh(max_num_faces=1)
        print("  ✔ MediaPipe Face Mesh ready.")
    except Exception as e:
        print(f"  ✗ MediaPipe check failed: {e}")


if __name__ == "__main__":
    print("=" * 50)
    print("  Campus Eye — Model Downloader")
    print("=" * 50)
    download_yolo_models()
    download_insightface_models()
    download_mediapipe()
    print("\nAll models ready. You can now start the application.")
