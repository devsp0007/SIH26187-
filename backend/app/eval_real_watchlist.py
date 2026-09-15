import sys
sys.path.insert(0, '.')
import json
import cv2
import numpy as np
from pathlib import Path
from backend.app.detection_tracking import WatchlistFaceRecognizer

models_dir = Path("backend/models")
watchlist_dir = Path("backend/watchlist")
artifact_dir = Path(r"C:\Users\DELL\.gemini\antigravity-ide\brain\70aab743-360d-42c8-a6e5-4bffd177aac7")

recognizer = WatchlistFaceRecognizer(watchlist_dir=watchlist_dir, models_dir=models_dir, cosine_threshold=0.48)

print("=" * 80)
print("1. WATCHLIST PROFILE INGESTION & FACE LOCALIZATION REPORT")
print("=" * 80)

watchlist_files = sorted(list(watchlist_dir.iterdir()))
detection_results = {}

for p in watchlist_files:
    if p.suffix.lower() not in [".jpg", ".jpeg", ".png"]:
        continue
    img = cv2.imread(str(p))
    if img is None:
        print(f"[FAIL] {p.name}: Unable to decode image.")
        continue
    
    h, w = img.shape[:2]
    name = p.stem.replace("_", " ").strip().title()
    
    # Run YuNet detection directly
    recognizer.detector.setInputSize((w, h))
    _, faces = recognizer.detector.detect(img)
    num_faces = len(faces) if faces is not None else 0
    
    if num_faces > 0:
        best_face = max(faces, key=lambda f: f[14])
        fx, fy, fw, fh = best_face[:4]
        conf = float(best_face[14])
        has_embedding = name in recognizer.watchlist_embeddings
        emb_norm = float(np.linalg.norm(recognizer.watchlist_embeddings[name])) if has_embedding else 0.0
        
        detection_results[name] = {
            "file": p.name,
            "resolution": f"{w}x{h}",
            "faces_found": num_faces,
            "detection_conf": conf,
            "face_box": [round(float(fx), 1), round(float(fy), 1), round(float(fw), 1), round(float(fh), 1)],
            "embedding_cached": has_embedding,
            "embedding_dim": len(recognizer.watchlist_embeddings[name]) if has_embedding else 0,
        }
        print(f" [+] Profile: {name:<12} | File: {p.name:<14} | Dim: {w}x{h:<5} | Faces: {num_faces} | Detection Conf: {conf*100:.1f}% | Embedding: {'128-D OK' if has_embedding else 'MISSING'}")
    else:
        detection_results[name] = {
            "file": p.name,
            "resolution": f"{w}x{h}",
            "faces_found": 0,
            "detection_conf": 0.0,
            "embedding_cached": False,
        }
        print(f" [!] Profile: {name:<12} | File: {p.name:<14} | Dim: {w}x{h:<5} | Faces: 0 (FAILED DETECTION)")

print("\n" + "=" * 80)
print("2. CROSS-MATCH SIMILARITY MATRIX (PAIRWISE DISTINCT PEOPLE TEST)")
print("=" * 80)

names = sorted(list(recognizer.watchlist_embeddings.keys()))
n = len(names)

print(f"Evaluating all {n * (n - 1) // 2} distinct pairwise comparisons (Threshold: {recognizer.cosine_threshold:.2f})...\n")

matrix = {}
cross_pair_scores = []

header = f"{'Profile':<12}" + "".join([f"{name[:8]:>10}" for name in names])
print(header)
print("-" * len(header))

for i, name1 in enumerate(names):
    row_str = f"{name1:<12}"
    matrix[name1] = {}
    feat1 = recognizer.watchlist_embeddings[name1]
    
    for j, name2 in enumerate(names):
        feat2 = recognizer.watchlist_embeddings[name2]
        score = float(recognizer.recognizer.match(feat1, feat2, cv2.FaceRecognizerSF_FR_COSINE))
        matrix[name1][name2] = round(score, 4)
        
        if i == j:
            row_str += f"{'-- (Self)':>10}"
        else:
            row_str += f"{score:>10.3f}"
            if i < j:
                cross_pair_scores.append((name1, name2, score))
                
    print(row_str)

print("\n" + "-" * 80)
print("PAIRWISE COLLISION & SEPARATION AUDIT (ALL DISTINCT PAIRS):")
print("-" * 80)

collisions = 0
for name1, name2, score in cross_pair_scores:
    status = "DISTINCT (NO COLLISION)" if score < recognizer.cosine_threshold else "COLLISION / FALSE MATCH"
    if score >= recognizer.cosine_threshold:
        collisions += 1
    margin = recognizer.cosine_threshold - score
    print(f" - {name1:<10} vs {name2:<10} : Cosine Sim = {score:+.4f} | Margin below threshold = {margin:+.4f} -> {status}")

max_pair = max(cross_pair_scores, key=lambda x: x[2])
min_pair = min(cross_pair_scores, key=lambda x: x[2])
mean_sim = np.mean([s[2] for s in cross_pair_scores])

print("-" * 80)
print(f" Summary of Cross-Match Separation:")
print(f"  * Total Distinct Pairs Tested : {len(cross_pair_scores)}")
print(f"  * False Positive Collisions  : {collisions} ({(collisions/len(cross_pair_scores))*100:.1f}%)")
print(f"  * Highest Cross-Similarity    : {max_pair[0]} vs {max_pair[1]} ({max_pair[2]:.4f})")
print(f"  * Lowest Cross-Similarity     : {min_pair[0]} vs {min_pair[1]} ({min_pair[2]:.4f})")
print(f"  * Mean Cross-Similarity       : {mean_sim:.4f} (Safety Margin to 0.380: {recognizer.cosine_threshold - mean_sim:.4f})")

print("\n" + "=" * 80)
print("3. LIVE WEBCAM CAPTURE & IDENTIFICATION TEST")
print("=" * 80)

cap = cv2.VideoCapture(0)
live_result = {}

if not cap.isOpened():
    print("[!] Live Webcam: NOT ACCESSIBLE (Hardware camera not available).")
    live_result["webcam_available"] = False
else:
    # Warm up camera for auto-exposure & white balance
    for _ in range(15):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    
    if not ret or frame is None:
        print("[!] Live Webcam: Failed to read frame.")
        live_result["webcam_available"] = True
        live_result["frame_captured"] = False
    else:
        fh, fw = frame.shape[:2]
        live_result["webcam_available"] = True
        live_result["frame_captured"] = True
        live_result["resolution"] = f"{fw}x{fh}"
        
        # Test full face recognition pipeline on this fresh live frame
        recognizer.detector.setInputSize((fw, fh))
        _, faces = recognizer.detector.detect(frame)
        
        annotated = frame.copy()
        
        if faces is None or len(faces) == 0:
            print(f"[+] Webcam Grab Successful ({fw}x{fh}) - No person / face detected in current camera view.")
            live_result["face_detected"] = False
            live_result["message"] = "Camera is active, but no face was in front of the lens during this capture."
        else:
            best_face = max(faces, key=lambda f: f[14])
            fx, fy, fw_box, fh_box = map(int, best_face[:4])
            det_conf = float(best_face[14])
            
            aligned = recognizer.recognizer.alignCrop(frame, best_face)
            feat = recognizer.recognizer.feature(aligned)
            
            # Compare with all 5 watchlist embeddings
            scores = {}
            for wname, wfeat in recognizer.watchlist_embeddings.items():
                s = float(recognizer.recognizer.match(feat, wfeat, cv2.FaceRecognizerSF_FR_COSINE))
                scores[wname] = s
                
            best_match_name = max(scores, key=scores.get)
            best_score = scores[best_match_name]
            
            is_identified = best_score >= recognizer.cosine_threshold
            identity_str = best_match_name if is_identified else "UNKNOWN"
            
            live_result["face_detected"] = True
            live_result["detection_confidence"] = det_conf
            live_result["face_bbox"] = [fx, fy, fw_box, fh_box]
            live_result["scores_by_profile"] = {k: round(v, 4) for k, v in scores.items()}
            live_result["identified_as"] = identity_str
            live_result["best_candidate"] = best_match_name
            live_result["best_cosine_confidence"] = round(best_score, 4)
            live_result["decision"] = "CONFIRMED WATCHLIST MEMBER" if is_identified else "UNLISTED / BELOW THRESHOLD"
            
            print(f"[+] Live Face Detected! Confidence: {det_conf*100:.1f}% | BBox: [{fx}, {fy}, {fw_box}, {fh_box}]")
            print("    Pairwise Live Scores Against All 5 Watchlist Members:")
            for wname, s in scores.items():
                match_flag = "<- BEST MATCH" if wname == best_match_name else ""
                print(f"     - {wname:<10}: {s:+.4f} (Threshold: 0.380) {match_flag}")
            print(f"\n    FINAL DECISION: {identity_str} (Cosine Confidence: {best_score:.3f} / {best_score*100:.1f}%) -> {live_result['decision']}")
            
            # Draw annotation on frame
            box_color = (0, 255, 0) if is_identified else (255, 255, 0)
            cv2.rectangle(annotated, (fx, fy), (fx + fw_box, fy + fh_box), box_color, 2)
            label = f"{identity_str} ({int(best_score*100)}%)" if is_identified else f"UNKNOWN ({int(best_score*100)}%)"
            cv2.putText(annotated, label, (fx, max(20, fy - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2)

        # Save annotated live capture
        save_path = artifact_dir / "live_webcam_face_test.jpg"
        cv2.imwrite(str(save_path), annotated)
        print(f"[+] Saved live frame evidence to: {save_path}")

print("=" * 80)
