# Fitness reference specification

Hai cặp ground-truth do người dùng cung cấp:

1. `TikVideo.App_7639727995498235752.mp4` → bản dịch thủ công `tạ tay.mov`.
2. `SnapVideoTools-1785236300021.mp4` → bản dịch thủ công `thon vai, gọn cằm, gọn bắp tay.mov`.

## Các invariant LoopGen phải giữ

- Full timeline: không cắt thành short reel, không reorder scene.
- Không thêm hook/card/CTA/keyword không tồn tại trong nguồn.
- Dialogue được Việt hóa bằng voice, nên subtitle hội thoại Trung ở đáy không tạo thêm overlay.
- Graphic liên quan fitness được Việt hóa tại/near vị trí gốc.
- Counter/timer/index giữ nguyên.
- Logo, watermark, username, hashtag, brand/packaging/object text bị bỏ.
- Một text graphic kéo dài nhiều giây = một tracked object, không sinh box mới mỗi sample frame.
- Tối đa 2 localization overlay cùng lúc; ưu tiên text lớn/ổn định/hữu ích.
- Output preserve source resolution/FPS và duration (sai số mux nhỏ cho phép), không ép 1080x1920.

## Timing target

OCR sample 1 fps nhưng start time back-date khoảng 0.48 s; mục tiêu visual translation không trễ quá khoảng nửa giây so với graphic gốc trong đa số scene.

## Performance target

Gemini calls không scale theo số frame. Dialogue dùng 1 batch; visual semantic classification dùng 1 batch. OCR frame-level là local RapidOCR.
