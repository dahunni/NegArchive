import os
import numpy as np
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session

DEEPFACE_ENABLED = os.getenv("DEEPFACE_ENABLED", "true").lower() == "true"
FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.7"))

if DEEPFACE_ENABLED:
    try:
        from deepface import DeepFace
        DEEPFACE_AVAILABLE = True
    except Exception:
        DEEPFACE_AVAILABLE = False
else:
    DEEPFACE_AVAILABLE = False

from ..models import ImageAsset, Face, Person


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def detect_and_embed(image_path: str) -> List[Tuple[Tuple[int, int, int, int], Optional[np.ndarray]]]:
    """Return list of (bbox, embedding) tuples. Embedding may be None if disabled/unavailable."""
    results: List[Tuple[Tuple[int, int, int, int], Optional[np.ndarray]]] = []
    if DEEPFACE_AVAILABLE:
        try:
            # Using RetinaFace detector and ArcFace embeddings via represent
            faces = DeepFace.extract_faces(img_path=image_path, detector_backend="retinaface", enforce_detection=False)
            for f in faces:
                x, y, w, h = int(f["facial_area"]["x"]), int(f["facial_area"]["y"]), int(f["facial_area"]["w"]), int(f["facial_area"]["h"])
                # represent returns embeddings across models; pick default (ArcFace)
                try:
                    rep = DeepFace.represent(img_path=image_path, detector_backend="retinaface", enforce_detection=False)
                    # DeepFace.represent can return list of dict with 'embedding'
                    emb = None
                    if isinstance(rep, list) and len(rep) > 0 and "embedding" in rep[0]:
                        emb = np.array(rep[0]["embedding"], dtype=np.float32)
                except Exception:
                    emb = None
                results.append(((x, y, w, h), emb))
            return results
        except Exception:
            pass
    # Fallback: no embeddings
    return results


def person_prototypes(db: Session) -> List[Tuple[int, np.ndarray]]:
    """Compute prototypes per person as mean of their face embeddings."""
    prototypes: List[Tuple[int, np.ndarray]] = []
    persons = db.query(Person).all()
    for p in persons:
        embs: List[np.ndarray] = []
        for f in p.faces:
            if f.embedding and isinstance(f.embedding.get("v"), list):
                embs.append(np.array(f.embedding["v"], dtype=np.float32))
        if embs:
            proto = np.mean(np.stack(embs), axis=0)
            prototypes.append((p.id, proto))
    return prototypes


def assign_person(db: Session, face: Face) -> None:
    """Assign closest known person to face when similarity exceeds threshold."""
    if not face.embedding or not isinstance(face.embedding.get("v"), list):
        return
    q = np.array(face.embedding["v"], dtype=np.float32)
    best_person_id = None
    best_score = 0.0
    for pid, proto in person_prototypes(db):
        score = _cosine(q, proto)
        if score > best_score:
            best_score = score
            best_person_id = pid
    if best_person_id is not None and best_score >= FACE_MATCH_THRESHOLD:
        face.person_id = best_person_id


def process_image(db: Session, image: ImageAsset) -> int:
    """Detect faces on an image asset, store faces and embeddings, attempt auto-assignment.
    Returns number of faces indexed.
    """
    path = image.path
    faces = detect_and_embed(path)
    count = 0
    for (x, y, w, h), emb in faces:
        f = Face(
            image_id=image.id,
            bbox_x=x,
            bbox_y=y,
            bbox_w=w,
            bbox_h=h,
            embedding=(
                {"model": "arcface", "v": emb.tolist()} if emb is not None else None
            ),
        )
        db.add(f)
        db.flush()
        assign_person(db, f)
        count += 1
    db.commit()
    return count