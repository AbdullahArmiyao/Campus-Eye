"""
Quick diagnostic: opens webcam, runs YOLO at various confidence levels,
and prints everything it detects each frame.
Hold your phone in front of the camera to test.
Press Q to quit.
"""
import sys
import time
import cv2
import torch
import ultralytics.nn.tasks as _tasks

# PyTorch 2.6 fix
if hasattr(torch.serialization, "add_safe_globals"):
    torch.serialization.add_safe_globals([
        _tasks.DetectionModel,
        _tasks.PoseModel,
        _tasks.SegmentationModel,
    ])

from ultralytics import YOLO

CONF = float(sys.argv[1]) if len(sys.argv) > 1 else 0.15   # very low for testing
WATCH_CLASSES = {67: "cell phone", 73: "book", 74: "clock", 63: "laptop", 0: "person"}

print(f"Loading YOLOv8n at conf={CONF}...")
model = YOLO("yolov8n.pt")
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("ERROR: Cannot open webcam 0"); sys.exit(1)

print("Webcam open. Hold your phone in front of the camera. Press Q to quit.\n")
last_print = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break

    results = model(frame, conf=CONF, verbose=False)

    now = time.time()
    items = []
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            cls_id = int(box.cls[0])
            name = model.names.get(cls_id, str(cls_id))
            conf_score = float(box.conf[0])
            items.append((name, conf_score, cls_id))

    if now - last_print > 0.5:   # print 2x per second
        if items:
            hits = [(n, f"{c:.0%}") for n, c, _ in items]
            exam_hits = [(n, f"{c:.0%}") for n, c, i in items if i in WATCH_CLASSES]
            print(f"All detections: {hits}")
            if exam_hits:
                print(f"  >>> EXAM OBJECTS: {exam_hits} <<<")
        else:
            print("(nothing detected)")
        last_print = now

    # Annotate frame
    annotated = results[0].plot()
    cv2.imshow("YOLO test — press Q to quit", annotated)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
