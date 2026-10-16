# Dataset and research protocol

No industrial dataset has been acquired. The executed demo repeats the public Ultralytics bus image; COCO8 is only an eight-image training smoke fixture. Neither supports industrial accuracy or tracking-performance claims. Do not redistribute sample imagery without checking its underlying rights. Download it locally with `scripts/demo.py`.

## Preparation

Supply a JSON manifest with `license`, `source`, `names` and `samples`. Each sample contains `image`, `label` and `group`. Paths follow sibling `images/<name>.jpg` and `labels/<name>.txt` layout. Labels contain YOLO rows `class cx cy width height`. Source video or scene identity is the group; never split individual frames.

`python ml/training/prepare.py manifest.json --output data/prepared` decodes every image, validates boxes/classes, rejects exact decoded-pixel duplicates and corruption, hashes image pixels/annotations and assigns stable group-level splits. It rejects empty splits. A conservative dHash plus grayscale-distance screen rejects possible near duplicates across source groups; review flagged pairs and source IDs. Four 16-bit hash-band indexes generate candidates for the exact Hamming-radius-3 screen, followed by grayscale distance. Colliding buckets can still have quadratic worst-case work; this is not a universal linear-time guarantee or a provenance audit. The tool cannot infer incorrectly supplied source IDs.

Create a local pointer with `python scripts/dataset_version.py prepared.dvc --directory data/prepared`; verify it with `python scripts/dataset_version.py prepared.dvc`. Commit the small pointer, never footage or weights. DVC/diskcache were removed after the dependency audit; this narrow tool reads JSON and hashes bytes, and does not implement remote push/checkout. COCO8 pointer verification passed for 20 local files.

## Training and evaluation

```
python ml/training/train.py --data data/prepared/dataset.yaml --epochs 50 --device cpu
python ml/evaluation/detection.py --data data/prepared/dataset.yaml --models yolo11n.pt path/to/best.pt --split val
```

The training script uses real transfer learning, seed 42, deterministic mode, checkpoints, augmentation defaults, patience 10 and MLflow parameter/metric/artifact logging. Use `--device 0` for a separately provisioned CUDA installation. Resume interrupted compatible runs with `--model path/to/last.pt --resume`. Completed stripped checkpoints are not an optimizer-resume test. Custom training and resume recovery have not been executed.

Freeze the model, threshold, rules and calibration using validation sources. Evaluate once on untouched test sources. Report per-class support and AP, confusion matrices, false negatives, camera/site distribution and annotation uncertainty. COCO8 smoke metrics must not appear as product accuracy.

## Event protocol

`python ml/evaluation/events.py labels.json` accepts `predictions`, `truth`, `hours` and optional `tolerance`. Events require video ID, rule ID and onset timestamp. Matching is one-to-one within the post-onset window. Report precision, recall, F1, false alarms/video-hour and time to detection. Annotate event intervals and track identity if overlapping same-rule events are possible; the legacy onset matcher does not resolve actor-level overlap. Use `intervals.py` for actor-mapped positive intervals, temporal IoU maximum-cardinality one-to-one matching, signed onset error and false alarms/video-hour. Inputs must supply externally mapped actor IDs; tracker IDs are not automatically ground-truth identity.

RQ1–RQ5 and ablations are specified in `configs/experiments.yaml`. MOT17 acquisition and TrackEval MOTA/IDF1/HOTA runs need labeled data. `mot_export.py` exports stored normalized trajectories with explicit source FPS. `uncertainty.py` bootstraps independent video clusters (at least two positive-duration videos); independence and sample adequacy still need review. `ablation.py` replays 32 downstream confidence/persistence/sampling/exit-grace combinations on frozen validation tracks. Detector/back-end/tracker-threshold changes require regenerating tracks, not relabeling these results. No numerical outcomes are invented for these questions.

Run `python scripts/verify_research.py` for executable synthetic smoke verification of those three CLIs. Output files are named `synthetic-*` and must never be cited as industrial findings. The event bootstrap input contains `video_hours: {video_id: hours}`, `predictions`, `truth` and `scope`; the replay input contains rules, zones, timestamped tracks and scope. Use actual source FPS for MOT export, never approximate live receive-time output as benchmark frame indices.

## Upstream experiments

`python ml/evaluation/upstream.py <video> configs/upstream-smoke.json --output data/upstream-smoke --max-frames 5` creates fresh YOLO/tracker sessions per configuration and exports tracks for replay. It supports model/backend, input resolution, confidence, frame sampling and supported tracker thresholds. Source/model hashes and configurations are recorded. Three CPU configurations were executed: PyTorch 320 ByteTrack, PyTorch 640 BoT-SORT with sampling, and ONNX 640 ByteTrack. These five-frame fixture runs prove execution only; they do not establish an accuracy ranking. See `docs/results/upstream-smoke.json`.

`python ml/evaluation/intervals.py input.json --output result.json` expects predictions/truth with video_id, rule_id, actor_id, start/end and positive hours; optional minimum_iou defaults to 0.1 (freeze this threshold before test evaluation). Independent calibration check points and explicit PPE association also have synthetic integration tests. Neither substitutes for measured ground-plane validation or labeled industrial actors.
