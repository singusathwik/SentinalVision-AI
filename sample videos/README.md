# Moving people sample

Source: OpenCV's vtest.avi sample, downloaded from https://github.com/opencv/opencv/blob/4.x/samples/data/vtest.avi on 2026-10-16. Original bytes and hash are recorded in source.json. This is existing pedestrian footage, not generated motion or the static bus fixture.

- opencv-pedestrians-original.avi: original 79.5-second source.
- people-walking-20s.mp4: first 20 seconds, H264, 768 x 576 at 10 fps; use this for uploads.
- people-walking-20s-annotated.mp4: actual YOLO11n / ByteTrack output.
- detection-result.json: saved video/job IDs, frame counts and browser playback verification.
- annotated-preview.jpg: annotated frame at 5 seconds.

The retained app sample is **people-walking-clean-labels.mp4**. Open Video analysis and choose **Watch detection results** beside that video name. To rerun, leave Optional alerts unchecked for detection only, or select **Person enters the walkway (walking sample)** to also generate area-entry observations. Then click Analyze. Duplicate uploads and their older app results were removed during the requested cleanup; the original local files and historical verification reports remain in this folder.

Verification: 200 frames processed; person detections appeared in all 200; browser playback advanced successfully and reported 20 seconds. 17 person track IDs and 17 demo zone events were recorded. Track IDs are not a unique-person count. No annotated ground truth was used, so these results do not establish accuracy. The yellow polygon is a demonstration region, not a real restricted area. Source repository availability is not a blanket claim about redistribution rights.

## Updated label rendering

The latest result is `people-walking-clean-labels-annotated.mp4`, available in Video analysis under the video name `people-walking-clean-labels.mp4`. It uses compact class/track-ID labels, thin boxes, stable per-track colors and connector lines when a label moves away from its box. Confidence remains in the stored detections. Earlier output files retain the old renderer.

All 200 frames of the updated sample were checked: zero overlapping label rectangles and zero out-of-frame label rectangles. The 5s/10s/15s frames were visually inspected; browser playback was verified. This is a result for this sample, not a guarantee for arbitrarily dense crowds where available label space can be exhausted. See clean-labels-result.json. Python tests: 70 passed; Ruff and mypy passed.
