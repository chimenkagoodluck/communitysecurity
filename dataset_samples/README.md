# Dataset Samples — Weapons, Machetes & Armed Persons

Real, openly-licensed sample images with YOLO-format labels, assembled for the
Community Security Alert System (CSSA) defense. It covers the classes the
supervisor named: **guns, knives, machetes, and armed persons** (a person boxed
together with a weapon). Each image in `images/` has a matching label file in
`labels/` (`<class_id> <x_center> <y_center> <width> <height>`, normalised 0–1).

Class ids (`classes.txt`):

| id | class |
|----|-------|
| 0 | person |
| 1 | gun |
| 2 | knife |
| 3 | machete |
| 4 | weapon |

## Current class distribution (honest, current)

| class | box instances |
|-------|---------------|
| person | 29 |
| gun | 80 |
| knife | 7 |
| machete | 26 |
| weapon | 0 |

- **Total images:** 83
- **Armed-person images** (≥1 person box AND ≥1 weapon box in the same image): **22**

> The `weapon` class (id 4) is a generic catch-all kept for forward-compatibility
> with the app's class scheme. No current source emits a generically-labelled
> "weapon" box (everything resolves to person/gun/knife/machete), so its count is
> legitimately 0 — it is not a missing or dropped label.

## Sources & Citations (real images + real labels only)

- **GUN / KNIFE** — **Subh775/WeaponDetection** on the Hugging Face Hub, derived
  from "weapon-detection" on Roboflow Universe by *yolov7test*. Boxes (COCO) were
  remapped to our canonical classes and converted to YOLO format.
  https://huggingface.co/datasets/Subh775/WeaponDetection  License: CC-BY-4.0
  ```bibtex
  @misc{yolov7test_weapon_detection,
    title  = {Weapon Detection Object Detection Model},
    author = {yolov7test},
    howpublished = {\url{https://universe.roboflow.com/yolov7test-pdxwq/weapon-detection-m7tpo}},
    year   = {2022}
  }
  ```
- **ARMED-PERSON** — **Subh775/WeaponDetection_Grouped** (classes GUN / KNIFE /
  PERSON). We kept only images that contain **both** a person box **and** a weapon
  box, giving genuine person-with-weapon samples (22 images).
  https://huggingface.co/datasets/Subh775/WeaponDetection_Grouped  License: CC-BY-4.0
- **MACHETE** — Roboflow Universe **a-fadfk/machete-celurit** (26 boxes). Real images, original author annotations, converted to our YOLO class ids.
  https://universe.roboflow.com/a-fadfk/machete-celurit  License: CC-BY-4.0
  ```bibtex
  @misc{machete_celurit,
    title  = {Machete-Celurit Dataset},
    author = {a-fadfk},
    howpublished = {\url{https://universe.roboflow.com/a-fadfk/machete-celurit}},
    note   = {Roboflow Universe}, year = {2023}
  }
  ```

All images and original annotations belong to their respective authors;
redistribution here is with attribution under the licenses above.

## How this folder was built

A single multi-source builder pulls from the sources above (HF datasets-server
REST API for 1 & 2; Roboflow REST export API for 3), remaps every box to the
canonical class ids and writes normalised YOLO labels:

```powershell
# guns/knives + armed-person (no key needed)
python scripts/build_dataset_samples.py
# add real machete boxes from Roboflow (free API key)
python scripts/build_dataset_samples.py --roboflow-key YOUR_KEY
```

Counts above are produced by that script; re-run to rebuild or resize.
