from shared.rules.aggregation import aggregate_places, channel_rating, job_status

from .factories import evidence, ref


def test_same_channel_three_mentions_is_one_vote() -> None:
    # §8 필수: 같은 채널이 같은 장소를 3번 언급 → 1표
    refs = [ref("v1", "ch1"), ref("v2", "ch2")]
    evs = [evidence("P", "ch1", "v1", s) for s in (10, 200, 400)]
    [agg] = aggregate_places(evs, refs)
    assert agg.channels_visited == 1
    assert agg.denominator == 2


def test_mentioned_only_channel_is_not_a_visit() -> None:
    # §8 필수: MENTIONED만 있는 채널 → 방문으로 세지 않음
    refs = [ref("v1", "ch1"), ref("v2", "ch2")]
    evs = [
        evidence("P", "ch1", "v1", visit="VISITED"),
        evidence("P", "ch2", "v2", visit="MENTIONED", ratings={"taste": "POSITIVE"}),
    ]
    [agg] = aggregate_places(evs, refs)
    assert agg.channels_visited == 1
    assert agg.visited_channel_ids == {"ch1"}
    assert agg.ratings["taste"].positive == 0  # 언급만 한 채널의 평가는 세지 않음(결정 0003-1)


def test_failed_video_excluded_from_denominator_and_partial() -> None:
    # §8 필수: 영상 1개 FAILED → 분모에서 제외, 상태 PARTIAL
    refs = [ref("v1", "ch1"), ref("v2", "ch2"), ref("v3", "ch3", state="FAILED")]
    [agg] = aggregate_places([evidence("P", "ch1", "v1")], refs)
    assert agg.denominator == 2
    assert job_status(refs) == "PARTIAL"


def test_failed_video_replaced_successfully_is_not_partial() -> None:
    refs = [ref("v1", "ch1"), ref("v3", "ch3", state="FAILED"), ref("v4", "ch4", replaces="v3")]
    assert job_status(refs) == "SUCCEEDED"


def test_failed_replacement_stays_partial() -> None:
    refs = [
        ref("v1", "ch1"),
        ref("v3", "ch3", state="FAILED"),
        ref("v4", "ch4", state="FAILED", replaces="v3"),
    ]
    assert job_status(refs) == "PARTIAL"


def test_job_status_running_failed_succeeded_skipped() -> None:
    assert job_status([ref("v1", "ch1"), ref("v2", "ch2", state="ANALYZING")]) == "RUNNING"
    assert job_status([ref("v1", "ch1", state="FAILED")]) == "FAILED"
    assert job_status([]) == "FAILED"
    assert job_status([ref("v1", "ch1"), ref("v2", "ch2", state="SKIPPED")]) == "SUCCEEDED"


def test_conflict_within_channel_is_mixed() -> None:
    assert channel_rating(["POSITIVE", "NEGATIVE"]) == "MIXED"
    assert channel_rating(["POSITIVE", "NONE", "UNDETERMINED"]) == "POSITIVE"
    assert channel_rating(["NONE", "UNDETERMINED"]) == "NONE"


def test_ratings_counted_per_channel_and_none_is_not_positive() -> None:
    refs = [ref("v1", "ch1"), ref("v2", "ch2"), ref("v3", "ch3")]
    evs = [
        evidence("P", "ch1", "v1", 10, ratings={"taste": "POSITIVE"}),
        evidence("P", "ch1", "v1", 20, ratings={"taste": "POSITIVE"}),
        evidence("P", "ch2", "v2", ratings={"taste": "POSITIVE", "wait": "NEGATIVE"}),
        evidence("P", "ch2", "v2", 30, ratings={"wait": "POSITIVE"}),
        evidence("P", "ch3", "v3", ratings={"taste": "NONE"}),
    ]
    [agg] = aggregate_places(evs, refs)
    assert agg.ratings["taste"].model_dump() == {"positive": 2, "negative": 0, "mixed": 0}
    assert agg.ratings["wait"].model_dump() == {"positive": 0, "negative": 0, "mixed": 1}


def test_evidence_outside_job_scope_is_ignored() -> None:
    refs = [ref("v1", "ch1"), ref("v2", "ch2", state="FAILED")]
    evs = [
        evidence("P", "ch1", "v1"),
        evidence("P", "ch2", "v2"),  # 실패한 영상
        evidence("P", "ch9", "v9"),  # 이 작업에 없는 영상
        evidence("P", "ch1", "v1", 50, version="v0-old"),  # 다른 분석 버전
        evidence("Q", "ch1", "v1", match="UNCONFIRMED"),
    ]
    aggs = aggregate_places(evs, refs)
    assert [a.place_id for a in aggs] == ["P"]
    assert aggs[0].channels_visited == 1
    assert len(aggs[0].evidence) == 1
