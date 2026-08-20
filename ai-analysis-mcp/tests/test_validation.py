from app.validation import compute_engine_health, validate_grounding


class TestValidateGrounding:
    def test_grounded_with_matching_refs(self):
        assert validate_grounding(["EV-1", "EV-2"], ["EV-1", "EV-2", "EV-3"], False) == "grounded"

    def test_insufficient_evidence_is_grounded_even_with_no_refs(self):
        assert validate_grounding([], ["EV-1"], True) == "grounded"

    def test_no_refs_but_claims_conclusion_is_rejected(self):
        assert validate_grounding([], ["EV-1"], False) == "rejected_no_evidence"

    def test_hallucinated_ref_is_rejected(self):
        assert validate_grounding(["EV-999"], ["EV-1", "EV-2"], False) == "rejected_ungrounded"

    def test_partial_hallucination_is_rejected(self):
        assert validate_grounding(["EV-1", "EV-999"], ["EV-1", "EV-2"], False) == "rejected_ungrounded"


class TestEngineHealth:
    def test_no_calls_yet(self):
        h = compute_engine_health([], window=20, threshold=0.3)
        assert h["calls_in_window"] == 0
        assert h["circuit_breaker_tripped"] is False

    def test_healthy_rate_does_not_trip(self):
        recent = ["grounded"] * 18 + ["rejected_ungrounded"] * 2
        h = compute_engine_health(recent, window=20, threshold=0.3)
        assert h["rejection_rate"] == 0.1
        assert h["circuit_breaker_tripped"] is False

    def test_high_rejection_rate_trips_breaker(self):
        recent = ["grounded"] * 5 + ["rejected_ungrounded"] * 10
        h = compute_engine_health(recent, window=20, threshold=0.3)
        assert h["circuit_breaker_tripped"] is True

    def test_small_sample_does_not_trip_even_at_high_rate(self):
        # 2 calls, both rejected — 100% rate but too small a sample to act on
        recent = ["rejected_ungrounded", "rejected_ungrounded"]
        h = compute_engine_health(recent, window=20, threshold=0.3)
        assert h["circuit_breaker_tripped"] is False

    def test_window_trims_to_most_recent(self):
        recent = ["rejected_ungrounded"] * 30 + ["grounded"] * 20
        h = compute_engine_health(recent, window=20, threshold=0.3)
        assert h["calls_in_window"] == 20
        assert h["rejection_rate"] == 0.0

    def test_engine_error_counts_as_rejection(self):
        recent = ["grounded"] * 10 + ["engine_error"] * 10
        h = compute_engine_health(recent, window=20, threshold=0.3)
        assert h["rejection_rate"] == 0.5
        assert h["circuit_breaker_tripped"] is True
