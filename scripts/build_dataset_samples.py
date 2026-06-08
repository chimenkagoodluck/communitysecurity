
from __future__ import annotations

import argparse
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "dataset_samples"
IMAGES_DIR = OUT_DIR / "images"
LABELS_DIR = OUT_DIR / "labels"

API = "https://datasets-server.huggingface.co"
HF_GUNS = "Subh775/WeaponDetection"            # 29-class, gun/knife rich
HF_ARMED = "Subh775/WeaponDetection_Grouped"   # GUN / KNIFE / PERSON

# Canonical classes -> the YOLO class ids written to label files.
CANON_CLASSES = ["person", "gun", "knife", "machete", "weapon"]
CANON_ID = {c: i for i, c in enumerate(CANON_CLASSES)}


def canonical(name: str) -> str | None:
    
    n = name.strip().lower()
    if any(k in n for k in ("machete", "matchet", "celurit", "clurit", "panga",
                            "parang", "golok", "cutlass")):
        return "machete"
    if any(k in n for k in ("pistol", "handgun", "rifle", "shotgun", "gun",
                            "heavy", "long gun", "larga")):
        return "gun"
    if "knife" in n:
        return "knife"
    if any(k in n for k in ("person", "aggressor", "victim", "armed")):
        return "person"
    if "weapon" in n:
        return "weapon"
    return None  # Blood / Hand / Stabbing / violence / al -> skip



def _get_bytes(url: str, tries: int = 6) -> bytes:
   
    delay = 2.0
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cssa-dataset-builder"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            # 429 (rate limit) and 5xx (transient gateway/server) are retryable.
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                print(f"[i] HTTP {e.code}, backing off {delay:.0f}s…")
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            raise
        except Exception:
            if attempt < tries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            raise
    raise RuntimeError(f"giving up on {url}")


def _get_json(url: str) -> dict:
    return json.loads(_get_bytes(url))



def hf_category_names(dataset: str, config: str, split: str) -> list[str]:
    d = _get_json(f"{API}/first-rows?dataset={urllib.parse.quote(dataset)}"
                  f"&config={config}&split={split}")
    objects = next(f for f in d["features"] if f["name"] == "objects")
    return objects["type"]["category"]["feature"]["names"]


def hf_rows(dataset: str, config: str, split: str, offset: int, length: int) -> list[dict]:
    url = (f"{API}/rows?dataset={urllib.parse.quote(dataset)}"
           f"&config={config}&split={split}&offset={offset}&length={length}")
    return _get_json(url).get("rows", [])


def to_yolo_lines(objects: dict, width: int, height: int, names: list[str]) -> list[str]:
    """COCO [x,y,w,h] absolute -> YOLO '<id> <xc> <yc> <w> <h>' normalised."""
    lines: list[str] = []
    bboxes = objects.get("bbox") or []
    cats = objects.get("category") or []
    for bb, cat in zip(bboxes, cats):
        name = names[cat] if 0 <= cat < len(names) else str(cat)
        canon = canonical(name)
        if canon is None or width <= 0 or height <= 0:
            continue
        x, y, w, h = bb
        xc = (x + w / 2) / width
        yc = (y + h / 2) / height
        nw, nh = w / width, h / height
        xc, yc, nw, nh = (min(max(v, 0.0), 1.0) for v in (xc, yc, nw, nh))
        if nw <= 0 or nh <= 0:
            continue
        lines.append(f"{CANON_ID[canon]} {xc:.6f} {yc:.6f} {nw:.6f} {nh:.6f}")
    return lines


def _ids(lines: list[str]) -> set[int]:
    return {int(ln.split()[0]) for ln in lines}


def pull_hf(dataset: str, split: str, want: int, keep, scan_limit: int,
            counter: "Counter", page: int = 100) -> int:
    
    config = "default"
    names = hf_category_names(dataset, config, split)
    print(f"[i] {dataset}: {len(names)} source classes -> {CANON_CLASSES}")
    kept = scanned = offset = 0
    while kept < want and scanned < scan_limit:
        rows = hf_rows(dataset, config, split, offset, page)
        if not rows:
            break
        for item in rows:
            scanned += 1
            row = item["row"]
            w, h = row.get("width", 0), row.get("height", 0)
            lines = to_yolo_lines(row.get("objects", {}), w, h, names)
            if not lines or not keep(_ids(lines)):
                continue
            src = (row.get("image") or {}).get("src")
            if not src:
                continue
            try:
                data = _get_bytes(src)
            except Exception as exc:
                print(f"[warn] image download failed: {exc}")
                continue
            counter.write(data, lines)
            kept += 1
            time.sleep(0.25)  # be polite to the assets host
            if kept >= want:
                break
        offset += page
        print(f"[i]   scanned {scanned}, kept {kept}/{want}")
        time.sleep(0.5)
    if kept < want:
        print(f"[warn] {dataset}: only kept {kept}/{want} (scan limit / scarcity)")
    return kept



def pull_roboflow_machete(workspace: str, project: str, version: int | None,
                          api_key: str, want: int, counter: "Counter") -> int:
    
    base = "https://api.roboflow.com"
    info = _get_json(f"{base}/{workspace}/{project}?api_key={api_key}")
    versions = info.get("versions") or []
    if version is None:
        if not versions:
            raise RuntimeError("no versions found for this Roboflow project")
        # pick the newest version id
        version = max(int(str(v["id"]).split("/")[-1]) for v in versions)
    print(f"[i] roboflow {workspace}/{project} v{version}: requesting yolov8 export…")

    export_url = f"{base}/{workspace}/{project}/{version}/yolov8?api_key={api_key}"
    link = None
    for attempt in range(8):
        d = _get_json(export_url)
        link = (d.get("export") or {}).get("link")
        if link:
            break
        # export still generating
        print(f"[i]   export generating… ({d.get('export', {}).get('progress', '?')})")
        time.sleep(4)
    if not link:
        raise RuntimeError("Roboflow export link never became available")

    print("[i]   downloading export zip…")
    raw = _get_bytes(link)
    zf = zipfile.ZipFile(io.BytesIO(raw))

    # read class names from data.yaml
    names: list[str] = []
    for n in zf.namelist():
        if n.endswith("data.yaml"):
            txt = zf.read(n).decode("utf-8", "replace")
            names = _parse_yaml_names(txt)
            break
    print(f"[i]   roboflow source classes: {names or '(unknown -> assume machete)'}")

    # gather (image, label) pairs across splits
    pairs: list[tuple[str, str]] = []
    members = set(zf.namelist())
    for n in members:
        if "/labels/" in n and n.endswith(".txt"):
            img = None
            stem = n[: -len(".txt")].replace("/labels/", "/images/")
            for ext in (".jpg", ".jpeg", ".png"):
                if stem + ext in members:
                    img = stem + ext
                    break
            if img:
                pairs.append((img, n))
    pairs.sort()

    kept = 0
    for img_name, lbl_name in pairs:
        if kept >= want:
            break
        raw_lines = zf.read(lbl_name).decode("utf-8", "replace").splitlines()
        out_lines: list[str] = []
        for ln in raw_lines:
            parts = ln.split()
            if len(parts) != 5:
                continue
            try:
                cid = int(float(parts[0]))
            except ValueError:
                continue
            src_name = names[cid] if 0 <= cid < len(names) else "machete"
            canon = canonical(src_name) or "machete"  # machete-only dataset
            out_lines.append(f"{CANON_ID[canon]} {parts[1]} {parts[2]} {parts[3]} {parts[4]}")
        if not out_lines:
            continue
        counter.write(zf.read(img_name), out_lines)
        kept += 1
    print(f"[i]   machete: kept {kept}/{want} images")
    return kept


def _parse_yaml_names(txt: str) -> list[str]:
    """Tiny data.yaml 'names:' parser (list or {idx: name} forms)."""
    names: list[str] = []
    in_names = False
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith("names:"):
            rest = s[len("names:"):].strip()
            if rest.startswith("["):
                inner = rest.strip("[]")
                return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
            in_names = True
            continue
        if in_names:
            if s.startswith("-"):
                names.append(s[1:].strip().strip("'\""))
            elif s and s[0].isdigit() and ":" in s:
                names.append(s.split(":", 1)[1].strip().strip("'\""))
            elif s and not s.startswith("#"):
                break
    return names



class Counter:
    """Writes sample_NNN.jpg/.txt sequentially and tallies per-class boxes."""

    def __init__(self) -> None:
        self.n = 0
        self.class_counts = {c: 0 for c in CANON_CLASSES}
        self.armed_person_imgs = 0

    def write(self, image_bytes: bytes, lines: list[str]) -> None:
        self.n += 1
        stem = f"sample_{self.n:03d}"
        (IMAGES_DIR / f"{stem}.jpg").write_bytes(image_bytes)
        (LABELS_DIR / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        ids = _ids(lines)
        for ln in lines:
            self.class_counts[CANON_CLASSES[int(ln.split()[0])]] += 1
        if CANON_ID["person"] in ids and (CANON_ID["gun"] in ids or CANON_ID["knife"] in ids
                                          or CANON_ID["machete"] in ids):
            self.armed_person_imgs += 1



def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--guns", type=int, default=32, help="gun images to keep")
    ap.add_argument("--knives", type=int, default=8, help="knife images to keep")
    ap.add_argument("--armed", type=int, default=22, help="armed-person images (person+weapon)")
    ap.add_argument("--machete", type=int, default=22, help="machete images to keep")
    ap.add_argument("--scan-limit", type=int, default=8000)
    ap.add_argument("--roboflow-key", default=os.environ.get("ROBOFLOW_API_KEY", ""))
    ap.add_argument("--rf-workspace", default="a-fadfk")
    ap.add_argument("--rf-project", default="machete-celurit")
    ap.add_argument("--rf-version", type=int, default=None)
    args = ap.parse_args()

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    for old in list(IMAGES_DIR.glob("sample_*.jpg")) + list(LABELS_DIR.glob("sample_*.txt")):
        old.unlink()

    counter = Counter()
    sources: dict[str, str] = {}


    print("\n== Source 1a: knives (Subh775/WeaponDetection) ==")
    n_k = pull_hf(
        HF_GUNS, "train", args.knives,
        keep=lambda ids: CANON_ID["knife"] in ids,
        scan_limit=args.scan_limit, counter=counter)
    print("\n== Source 1b: guns (Subh775/WeaponDetection) ==")
    n_g = pull_hf(
        HF_GUNS, "train", args.guns,
        keep=lambda ids: (CANON_ID["gun"] in ids and CANON_ID["knife"] not in ids),
        scan_limit=args.scan_limit, counter=counter)
    sources["guns_knives"] = f"{n_g} gun + {n_k} knife images"

 
    print("\n== Source 2: armed-person (Subh775/WeaponDetection_Grouped) ==")
    n_ap = pull_hf(
        HF_ARMED, "train", args.armed,
        keep=lambda ids: (CANON_ID["person"] in ids
                          and (CANON_ID["gun"] in ids or CANON_ID["knife"] in ids)),
        scan_limit=args.scan_limit, counter=counter)
    sources["armed_person"] = f"{n_ap} images"


    print("\n== Source 3: machete (Roboflow) ==")
    if args.roboflow_key:
        try:
            n_m = pull_roboflow_machete(
                args.rf_workspace, args.rf_project, args.rf_version,
                args.roboflow_key, args.machete, counter)
            sources["machete"] = f"{n_m} images"
        except Exception as exc:
            print(f"[ERROR] machete pull failed: {exc}")
            sources["machete"] = f"FAILED ({exc})"
    else:
        print("[skip] no Roboflow API key (--roboflow-key / $ROBOFLOW_API_KEY); "
              "machete NOT added. README will document this honestly.")
        sources["machete"] = "not sourced (no Roboflow API key supplied)"

    (OUT_DIR / "classes.txt").write_text("\n".join(CANON_CLASSES) + "\n", encoding="utf-8")
    _write_readme(counter, sources, args)

    print(f"\n[OK] wrote {counter.n} images + labels to {OUT_DIR}")
    print(f"[OK] per-class box counts: {counter.class_counts}")
    print(f"[OK] armed-person images (person + weapon): {counter.armed_person_imgs}")


def _write_readme(counter: "Counter", sources: dict, args) -> None:
    cc = counter.class_counts
    machete_status = sources.get("machete", "")
    machete_sourced = machete_status.endswith("images") and not machete_status.startswith("0")

    if machete_sourced:
        machete_block = (
            f"- **MACHETE** — Roboflow Universe **{args.rf_workspace}/{args.rf_project}** "
            f"({cc['machete']} boxes). Real images, original author annotations, "
            "converted to our YOLO class ids.\n"
            f"  https://universe.roboflow.com/{args.rf_workspace}/{args.rf_project}  License: CC-BY-4.0\n"
            "  ```bibtex\n"
            "  @misc{machete_celurit,\n"
            "    title  = {Machete-Celurit Dataset},\n"
            f"    author = {{{args.rf_workspace}}},\n"
            f"    howpublished = {{\\url{{https://universe.roboflow.com/{args.rf_workspace}/{args.rf_project}}}}},\n"
            "    note   = {Roboflow Universe}, year = {2023}\n"
            "  }\n"
            "  ```"
        )
    else:
        machete_block = (
            "- **MACHETE** — **NOT YET SOURCED.** No machete-labelled dataset is reachable\n"
            "  through the keyless Hugging Face datasets-server pipeline (searched: machete,\n"
            "  matchet, panga, parang, golok, cutlass, celurit, melee/sharp/bladed weapon —\n"
            "  no usable hits). Real machete data exists on **Roboflow Universe** but needs a\n"
            "  free API key to download. We deliberately did **not** mislabel knives as\n"
            "  machetes. To add it, supply a key and re-run:\n"
            "  ```powershell\n"
            "  python scripts/build_dataset_samples.py --roboflow-key YOUR_KEY\n"
            "  ```\n"
            "  Recommended source: https://universe.roboflow.com/a-fadfk/machete-celurit (CC-BY-4.0)."
        )

    txt = f"""# Dataset Samples — Weapons, Machetes & Armed Persons

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
| person | {cc['person']} |
| gun | {cc['gun']} |
| knife | {cc['knife']} |
| machete | {cc['machete']} |
| weapon | {cc['weapon']} |

- **Total images:** {counter.n}
- **Armed-person images** (≥1 person box AND ≥1 weapon box in the same image): **{counter.armed_person_imgs}**

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
  @misc{{yolov7test_weapon_detection,
    title  = {{Weapon Detection Object Detection Model}},
    author = {{yolov7test}},
    howpublished = {{\\url{{https://universe.roboflow.com/yolov7test-pdxwq/weapon-detection-m7tpo}}}},
    year   = {{2022}}
  }}
  ```
- **ARMED-PERSON** — **Subh775/WeaponDetection_Grouped** (classes GUN / KNIFE /
  PERSON). We kept only images that contain **both** a person box **and** a weapon
  box, giving genuine person-with-weapon samples ({counter.armed_person_imgs} images).
  https://huggingface.co/datasets/Subh775/WeaponDetection_Grouped  License: CC-BY-4.0
{machete_block}

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
"""
    (OUT_DIR / "README.md").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
