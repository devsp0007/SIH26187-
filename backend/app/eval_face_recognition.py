import sys
from pathlib import Path
import cv2
import numpy as np

# Ensure project root and backend dir are in sys.path
backend_dir = Path(__file__).resolve().parent.parent
project_root = backend_dir.parent
for p in [str(project_root), str(backend_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from backend.app.face_engine import WatchlistFaceRecognizer
except ImportError:
    try:
        from app.face_engine import WatchlistFaceRecognizer
    except ImportError:
        from face_engine import WatchlistFaceRecognizer

models_dir = backend_dir / "models"
watchlist_dir = backend_dir / "watchlist"

recognizer = WatchlistFaceRecognizer(watchlist_dir=watchlist_dir, models_dir=models_dir, cosine_threshold=0.48)
print(f"[+] Loaded Watchlist with {len(recognizer.watchlist_embeddings)} identities: {list(recognizer.watchlist_embeddings.keys())}")

# Find any available watchlist sample images
img_files = list(watchlist_dir.glob("*.png")) + list(watchlist_dir.glob("*.jpg"))
if len(img_files) >= 1:
    img_a_path = img_files[0]
    img_a = cv2.imread(str(img_a_path))
    h, w = img_a.shape[:2]
    name_a, conf_a, coords_a = recognizer.identify_face_in_person_crop(img_a, (0, 0, w, h))
    print(f"[*] Test 1 (Known Member - {img_a_path.stem}): Match={name_a}, Cosine Confidence={conf_a:.3f}, BBox={coords_a}")

if len(img_files) >= 2:
    img_b_path = img_files[1]
    img_b = cv2.imread(str(img_b_path))
    h, w = img_b.shape[:2]
    name_b, conf_b, coords_b = recognizer.identify_face_in_person_crop(img_b, (0, 0, w, h))
    print(f"[*] Test 2 (Known Member - {img_b_path.stem}): Match={name_b}, Cosine Confidence={conf_b:.3f}, BBox={coords_b}")

# 3. Negative Test C: Unlisted Face (Unknown Person)
unlisted_img = np.zeros((400, 300, 3), dtype=np.uint8)
unlisted_img[:] = (50, 50, 50)
cv2.circle(unlisted_img, (150, 150), 75, (160, 140, 120), -1)
cv2.circle(unlisted_img, (120, 130), 10, (20, 20, 20), -1)
cv2.circle(unlisted_img, (180, 130), 10, (20, 20, 20), -1)
cv2.circle(unlisted_img, (150, 160), 8, (120, 100, 80), -1)
cv2.line(unlisted_img, (130, 185), (170, 185), (80, 40, 40), 4)

name_c, conf_c, coords_c = recognizer.identify_face_in_person_crop(unlisted_img, (0, 0, 300, 400))
print(f"[*] Test 3 (Unlisted / Unknown Person): Match={name_c}, Cosine Confidence={conf_c:.3f}, BBox={coords_c}")

# 4. Cross-Match Test: Pairwise separation
identities = list(recognizer.watchlist_embeddings.keys())
if len(identities) >= 2:
    id1, id2 = identities[0], identities[1]
    feat1 = recognizer.watchlist_embeddings[id1]
    feat2 = recognizer.watchlist_embeddings[id2]
    cross_sim = float(recognizer.recognizer.match(feat1, feat2, cv2.FaceRecognizerSF_FR_COSINE))
    print(f"[*] Cross-Identity Similarity ({id1} vs {id2}): {cross_sim:.4f} (Threshold: {recognizer.cosine_threshold}) -> {'MISMATCH/DISTINCT (CORRECT)' if cross_sim < recognizer.cosine_threshold else 'COLLISION (FALSE MATCH)'}")

