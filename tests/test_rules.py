from loopgen.utils import has_chinese, is_counter_or_timer
from loopgen.vision import track_detections


def test_counter_timer_rules():
    assert is_counter_or_timer("01")
    assert is_counter_or_timer("00:30")
    assert is_counter_or_timer("3/10")
    assert not is_counter_or_timer("每组8次")
    assert has_chinese("每组8次")


def test_tracking_merges_same_visual_text():
    rows = [
        {"time":0.0,"text":"收紧核心","score":.95,"bbox":[.2,.2,.6,.28],"numeric":False,"has_zh":True},
        {"time":1.0,"text":"收紧核心","score":.96,"bbox":[.205,.2,.605,.28],"numeric":False,"has_zh":True},
        {"time":2.0,"text":"收紧核心","score":.93,"bbox":[.2,.2,.6,.28],"numeric":False,"has_zh":True},
    ]
    tracks = track_detections(rows, fps=1.0)
    assert len(tracks) == 1
    assert tracks[0]["observations"] == 3
    assert tracks[0]["start"] <= 0.01
    assert tracks[0]["end"] >= 2.5
